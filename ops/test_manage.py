#!/usr/bin/env python3
"""Filesystem/operation regression tests; temporary files, no real Docker calls."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import manage


class ManageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wainak-manage-test-')
        self.root = Path(self.temp.name)
        self.runtime = self.root / '.runtime'
        self.backups = self.root / 'backups'
        self.patch = patch.multiple(manage, ROOT=self.root, RUNTIME=self.runtime, BACKUPS=self.backups)
        self.patch.start()
        self.old_umask = os.umask(0o077)

    def tearDown(self):
        os.umask(self.old_umask)
        self.patch.stop()
        self.temp.cleanup()

    def prepare(self):
        with patch.object(manage, 'deployment_exists', return_value=False):
            manage.main(['init'])

    def archive(self, content=b'synthetic backup'):
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        path = self.root / 'source.dump'
        path.write_bytes(content)
        path.with_suffix('.json').write_text(json.dumps({
            'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}))
        return path

    def test_status_missing_runtime_has_no_mutation(self):
        with patch.object(manage, 'run') as docker:
            with self.assertRaises(FileNotFoundError):
                manage.main(['status'])
        self.assertEqual(list(self.root.iterdir()), [])
        docker.assert_not_called()

    def test_missing_deployed_secret_is_not_replaced(self):
        with patch.object(manage, 'deployment_exists', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'secret is missing'):
                manage.main(['init'])
        self.assertFalse((self.runtime / 'db_password').exists())

    def test_lock_is_held_before_init(self):
        events = []

        @contextmanager
        def lock(**kwargs):
            events.append('locked')
            yield
            events.append('released')

        with patch.object(manage, 'operation_lock', lock), patch.object(manage, 'init', lambda: events.append('init')):
            manage.main(['init'])
        self.assertEqual(events, ['locked', 'init', 'released'])

    def test_second_operation_cannot_acquire_lock(self):
        self.prepare()
        with manage.operation_lock():
            with self.assertRaises(BlockingIOError):
                with manage.operation_lock():
                    self.fail('second lock acquired')

    def test_status_never_initializes_or_changes_secret(self):
        self.prepare()
        secret = self.runtime / 'db_password'
        before = secret.read_bytes()
        with patch.object(manage, 'verify_auth') as auth, patch.object(manage, 'run'), patch.object(manage, 'init') as init:
            manage.main(['status'])
        auth.assert_called_once_with('wainak')
        init.assert_not_called()
        self.assertEqual(secret.read_bytes(), before)

    def test_untrusted_source_rejected_even_with_valid_checksum(self):
        path = self.archive()
        with self.assertRaisesRegex(RuntimeError, 'trusted source'):
            with manage.verified_archive(path):
                self.fail('untrusted archive accepted')

    def test_source_replaced_after_verification_cannot_change_snapshot(self):
        path = self.archive(b'original synthetic bytes')
        with manage.verified_archive(path, trusted_source=True) as archive:
            path.unlink()
            path.write_bytes(b'replacement file')
            self.assertEqual(archive.read(), b'original synthetic bytes')

    def test_source_mutated_in_place_cannot_change_snapshot(self):
        path = self.archive(b'original synthetic bytes')
        with manage.verified_archive(path, trusted_source=True) as archive:
            path.write_bytes(b'changed in place')
            self.assertEqual(archive.read(), b'original synthetic bytes')

    def test_corruption_or_independent_digest_mismatch_is_rejected(self):
        path = self.archive()
        with self.assertRaisesRegex(RuntimeError, 'Expected SHA256'):
            with manage.verified_archive(path, trusted_source=True, expected_sha256='0' * 64):
                pass
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'integrity'):
            with manage.verified_archive(path, trusted_source=True):
                pass

    def test_symlink_archive_rejected(self):
        path = self.archive()
        other = path.with_name('original.dump')
        path.rename(other)
        path.symlink_to(other)
        with self.assertRaises(OSError):
            with manage.verified_archive(path, trusted_source=True):
                pass

    def test_manifest_must_be_an_object(self):
        path = self.archive()
        path.with_suffix('.json').write_text('[]')
        with self.assertRaisesRegex(RuntimeError, 'manifest object'):
            with manage.verified_archive(path, trusted_source=True):
                pass

    def test_fifo_archive_rejected_without_blocking(self):
        path = self.archive()
        path.unlink()
        os.mkfifo(path)
        with self.assertRaisesRegex(RuntimeError, 'regular file'):
            with manage.verified_archive(path, trusted_source=True):
                pass

    def test_existing_destination_not_modified(self):
        path = self.archive()
        with patch.object(manage, 'sql', return_value='1') as query, patch.object(manage, 'run') as restore:
            with self.assertRaisesRegex(RuntimeError, 'already exists'):
                manage.restore_empty(path, 'wainak_restore_existing', trusted_source=True)
        self.assertEqual(query.call_count, 1)
        self.assertTrue(query.call_args.args[0].startswith('SELECT '))
        restore.assert_not_called()

    def test_destination_racing_creation_never_runs_restore(self):
        path = self.archive()
        with patch.object(manage, 'sql', side_effect=['', RuntimeError('concurrent create')]), patch.object(manage, 'run') as restore:
            with self.assertRaisesRegex(RuntimeError, 'concurrent create'):
                manage.restore_empty(path, 'wainak_restore_race', trusted_source=True)
        restore.assert_not_called()

    def test_drill_secret_is_independent_and_cleaned_on_error(self):
        path = self.archive()
        primary = self.runtime / 'db_password'
        primary.write_text('synthetic-primary-' + 'x' * 40 + '\n')
        mounts = []

        def fail_run(command, **kwargs):
            mount = command[command.index('--mount') + 1]
            source = Path(mount.split('src=')[1].split(',dst=')[0])
            mounts.append(source)
            self.assertNotEqual(source, primary)
            self.assertNotEqual(source.read_bytes(), primary.read_bytes())
            self.assertEqual(source.stat().st_mode & 0o777, 0o600)
            raise RuntimeError('synthetic Docker failure')

        with patch.object(manage, 'configuration', return_value={'services': {'db': {'image': 'test'}}}), patch.object(manage, 'run', fail_run), patch.object(manage, 'cleanup_drill_container') as cleanup:
            with self.assertRaisesRegex(RuntimeError, 'synthetic Docker failure'):
                manage.restore_drill(path, trusted_source=True)
        self.assertEqual(len(mounts), 1)
        cleanup.assert_called_once()
        self.assertFalse(mounts[0].exists())
        self.assertTrue(primary.exists())

    def test_auth_errors_do_not_include_child_output_or_secret(self):
        self.prepare()
        failure = manage.subprocess.CompletedProcess([], 2, b'SENSITIVE_CHILD_STDOUT', b'SENSITIVE_CHILD_STDERR')
        with patch.object(manage.subprocess, 'run', return_value=failure):
            with self.assertRaisesRegex(RuntimeError, 'authentication failed') as error:
                manage.verify_auth()
        self.assertNotIn('SENSITIVE', str(error.exception))

    def test_drill_container_and_secret_are_cleaned_after_restore_error(self):
        path = self.archive()
        commands = []
        mounts = []

        def fake_run(command, **kwargs):
            commands.append(command)
            if command[:2] == ['docker', 'run']:
                mount = command[command.index('--mount') + 1]
                mounts.append(Path(mount.split('src=')[1].split(',dst=')[0]))
            if 'pg_restore' in command:
                raise RuntimeError('synthetic restore failure')
            return manage.subprocess.CompletedProcess(command, 0)

        ready = manage.subprocess.CompletedProcess([], 0)
        with patch.object(manage, 'configuration', return_value={'services': {'db': {'image': 'test'}}}), patch.object(manage, 'run', fake_run), patch.object(manage.subprocess, 'run', return_value=ready), patch.object(manage, 'cleanup_drill_container') as cleanup:
            with self.assertRaisesRegex(RuntimeError, 'synthetic restore failure'):
                manage.restore_drill(path, trusted_source=True)
        cleanup.assert_called_once()
        self.assertFalse(mounts[0].exists())

    def test_failed_docker_start_cleans_created_owned_container_by_id(self):
        path = self.archive()
        commands = []
        token = None

        def fake_run(command, **kwargs):
            nonlocal token
            commands.append(command)
            if command[:2] == ['docker', 'run']:
                token = command[command.index('--label') + 1].split('=', 1)[1]
                raise manage.subprocess.CalledProcessError(125, command)
            return manage.subprocess.CompletedProcess(command, 0)

        def fake_output(command):
            if command[:3] == ['docker', 'ps', '-a']:
                return 'owned-container-id'
            return token

        with patch.object(manage, 'configuration', return_value={'services': {'db': {'image': 'test'}}}), patch.object(manage, 'run', fake_run), patch.object(manage, 'output', fake_output):
            with self.assertRaises(manage.subprocess.CalledProcessError):
                manage.restore_drill(path, trusted_source=True)
        self.assertIn(['docker', 'rm', '-f', 'owned-container-id'], commands)
        self.assertEqual(list(self.runtime.glob('restore-secret-*')), [])

    def test_cleanup_does_not_remove_same_name_with_other_owner_label(self):
        with patch.object(manage, 'output', side_effect=['unrelated-container-id', 'different-operation']), patch.object(manage, 'run') as remove:
            manage.cleanup_drill_container('wainak-restore-drill-test', 'our-operation')
        remove.assert_not_called()

    def test_cleanup_with_no_created_container_does_not_remove_anything(self):
        with patch.object(manage, 'output', return_value=''), patch.object(manage, 'run') as remove:
            manage.cleanup_drill_container('wainak-restore-drill-test', 'our-operation')
        remove.assert_not_called()

    def test_cleanup_docker_query_failure_is_reported(self):
        with patch.object(manage, 'output', side_effect=RuntimeError('Docker unavailable')), patch.object(manage, 'run') as remove:
            with self.assertRaisesRegex(RuntimeError, 'Docker unavailable'):
                manage.cleanup_drill_container('wainak-restore-drill-test', 'our-operation')
        remove.assert_not_called()


if __name__ == '__main__':
    unittest.main()
