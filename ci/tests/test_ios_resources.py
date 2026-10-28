"""Real tiny filesystem controls; no compiler, network, cache or server cleanup."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

CI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CI))
sys.path.insert(0, str(CI / 'ios'))
import resources as r
import build as b
import test_ios_recipe as fixtures


class ResourceAccountingTests(unittest.TestCase):
    def test_fixed_roots_logical_total_and_no_nested_subtotal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            values = iter((11, 12, 13, 14, 120))
            measure = Mock(side_effect=lambda p: next(values))
            got = r.budget_snapshot(root, root/'app', root/'flutter', 100, measure)
            self.assertEqual(got['components'], {'work': 11, 'app_build': 12,
                'app_dart_tool': 13, 'app_ios_ephemeral': 14, 'flutter_growth': 20})
            self.assertEqual(got['total_logical_bytes'], 70)
            self.assertEqual(got['limit_bytes'], 8589934592)
            self.assertFalse(got['hard_quota'])
            self.assertEqual(measure.call_count, 5)

    def test_flutter_shrink_never_offsets_other_roots(self):
        with tempfile.TemporaryDirectory() as td:
            got = r.budget_snapshot(Path(td), Path(td), Path(td), 100,
                                    Mock(side_effect=[7, 2, 3, 4, 90]))
            self.assertEqual(got['total_logical_bytes'], 16)
            self.assertEqual(got['components']['flutter_growth'], 0)

    def test_over_budget_receipt_survives_same_fail_closed_gate(self):
        with tempfile.TemporaryDirectory() as td:
            runner = b.Runner.__new__(b.Runner)
            runner.work = runner.flutter = Path(td)
            runner.flutter_start = 100
            runner.cancelled = False
            with patch.object(b, 'size', side_effect=[r.LIMIT + 1, 0, 0, 0, 100]):
                with self.assertRaisesRegex(b.GateError, '^workspace_budget$'):
                    runner.guard()
            self.assertEqual(runner.resource_snapshot['total_logical_bytes'], r.LIMIT + 1)

    def test_logical_sparse_bytes_not_allocated_substitution(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'sparse'
            with p.open('wb') as f:
                f.truncate(1024 * 1024)
            self.assertGreaterEqual(r.tree_size(Path(td)), 1024 * 1024)

    def test_retirement_diagnostics_allow_fixed_labels_not_private_text(self):
        self.assertEqual(r.retirement_error(r.GateError('native_retirement_drift')),
                         {'type': 'GateError', 'gate': 'native_retirement_drift'})
        self.assertEqual(r.retirement_error(r.GateError('/private/canary')), {'type': 'GateError'})
        self.assertEqual(r.retirement_error(PermissionError(13, '/private/canary')),
                         {'type': 'PermissionError', 'errno': 13})

    def test_io_failure_does_not_leave_old_numeric_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            runner = b.Runner.__new__(b.Runner)
            runner.work = runner.flutter = Path(td)
            runner.flutter_start = 0
            runner.cancelled = False
            runner.resource_snapshot = {'old': True}
            with patch.object(b, 'size', side_effect=PermissionError(13, 'private')):
                with self.assertRaises(PermissionError):
                    runner.guard()
            self.assertIsNone(runner.resource_snapshot)


class NativeRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root/'.ci-work'
        self.work.mkdir(mode=0o700)
        self.native = self.work/'native'
        self.native.mkdir(mode=0o700)
        self.anchor = r.identity(self.work.stat())
        self.command = {'label': 'native', 'status': 'PASS', 'exit_code': 0,
                        'primary': None, 'cleanup_errors': []}
        fixture = fixtures.IOSRecipeChecks('test_exact_two_static_slices_and_config')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        shutil.copytree(fixture.root, self.native/'Archivebridge.xcframework')
        for name in ('logs', 'licenses'):
            (self.native/name).mkdir()
            (self.native/name/'evidence').write_text('retained public fixture')
        (self.native/'commands.json').write_text('[]\n')
        (self.native/'licenses.json').write_text('{}\n')
        for name in r.TARGETS:
            if name.endswith('.tar.gz'):
                (self.native/name).write_text('temporary public fixture')
            else:
                (self.native/name).mkdir()
                (self.native/name/'nested').mkdir()
                (self.native/name/'nested'/'entry').write_text('temporary public fixture')
        # Deliberately retained roots outside the evidence-hash subset.
        for name in ('gomodcache', 'tmp', 'host-tests', 'binding', 'tools-module'):
            (self.native/name).mkdir()
            (self.native/name/'keep').write_text(name)
        self.result = {
            'status': 'PASS_UNSIGNED_NATIVE_BUILD_ONLY', 'native_runtime_test': False,
            'final_budget_audit': 'PASS', 'final_audit_errors': [],
            'resource_final_audit_failed': False,
            'commands_manifest_sha256': self.digest(self.native/'commands.json'),
            'licenses_manifest_sha256': self.digest(self.native/'licenses.json'),
            'artifact_files': r.inventory(self.native/'Archivebridge.xcframework'),
        }
        self.save_result()

    def digest(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def save_result(self):
        (self.native/'result.json').write_text(json.dumps(self.result))

    def retire(self, **kwargs):
        return r.retire_native_tools(self.work, self.anchor, self.command, **kwargs)

    def assert_all_targets(self):
        self.assertTrue(all((self.native/name).exists() for name in r.TARGETS))

    def assert_preflight_rejects(self):
        with self.assertRaises((r.GateError, OSError)):
            self.retire()
        self.assertTrue((self.native/r.TARGETS[0]).exists())
        self.assertFalse((self.work/'native-retirement.json').exists())

    def test_success_exact_five_preserves_evidence_and_other_native_inputs(self):
        before = {p.relative_to(self.native).as_posix(): self.digest(p)
                  for p in self.native.rglob('*') if p.is_file() and p.relative_to(self.native).parts[0] not in r.TARGETS}
        receipt = self.retire()
        self.assertEqual(receipt['status'], 'PASS')
        self.assertEqual(receipt['retired'], list(r.TARGETS))
        self.assertTrue(receipt['retained_evidence_verified'])
        self.assertTrue(all(not (self.native/name).exists() for name in r.TARGETS))
        for name, digest in before.items():
            self.assertEqual(self.digest(self.native/name), digest)
        self.assertEqual(json.loads((self.work/'native-retirement.json').read_text()), receipt)

    def test_failed_native_never_retires(self):
        self.command['status'] = 'FAILED'
        self.assert_preflight_rejects()
        self.assert_all_targets()

    def test_uncertain_group_cleanup_never_retires(self):
        self.command['cleanup_errors'] = [{'type': 'UnverifiedProcessGroup'}]
        self.assert_preflight_rejects()

    def test_native_final_audit_must_have_passed(self):
        self.result['final_budget_audit'] = 'FAILED'
        self.save_result()
        self.assert_preflight_rejects()

    def test_commands_receipt_hash_drift(self):
        (self.native/'commands.json').write_text('[0]')
        self.assert_preflight_rejects()

    def test_license_receipt_hash_drift(self):
        (self.native/'licenses.json').write_text('{"changed":true}')
        self.assert_preflight_rejects()

    def test_artifact_inventory_drift(self):
        (self.native/'Archivebridge.xcframework/Info.plist').write_text('changed')
        self.assert_preflight_rejects()

    def test_late_target_symlink_preflight_before_any_delete(self):
        shutil.rmtree(self.native/'bin')
        outside = self.root/'outside'
        outside.mkdir()
        marker = outside/'marker'
        marker.write_text('preserve')
        (self.native/'bin').symlink_to(outside, target_is_directory=True)
        self.assert_preflight_rejects()
        self.assertEqual(marker.read_text(), 'preserve')

    def test_nested_symlink_rejected(self):
        p = self.native/'gocache/nested/entry'
        p.unlink()
        p.symlink_to(self.native/'result.json')
        self.assert_preflight_rejects()

    def test_external_hardlink_rejected(self):
        p = self.native/'bin/nested/entry'
        p.unlink()
        marker = self.root/'outside-marker'
        marker.write_text('preserve')
        os.link(marker, p)
        self.assert_preflight_rejects()
        self.assertEqual(marker.read_text(), 'preserve')

    def test_fifo_rejected_without_open_or_block(self):
        p = self.native/'bin/nested/entry'
        p.unlink()
        os.mkfifo(p)
        self.assert_preflight_rejects()

    def test_readonly_directory_no_chmod_fallback(self):
        p = self.native/'bin/nested'
        p.chmod(0o500)
        try:
            self.assert_preflight_rejects()
            self.assertEqual(p.stat().st_mode & 0o777, 0o500)
        finally:
            p.chmod(0o700)  # Fixture restoration only, never production helper.

    def test_readonly_regular_file_can_unlink_without_permission_change(self):
        (self.native/r.TARGETS[0]).chmod(0o400)
        self.assertEqual(self.retire()['status'], 'PASS')

    def test_missing_target_rejected_not_silently_skipped(self):
        shutil.rmtree(self.native/'bin')
        self.assert_preflight_rejects()

    def test_owner_mismatch_check_fails_closed(self):
        info = Mock(st_dev=self.work.stat().st_dev, st_uid=os.geteuid()+1)
        with self.assertRaises(r.GateError):
            r._check_info(info, self.work.stat().st_dev)

    def test_cross_device_check_fails_closed(self):
        info = Mock(st_dev=self.work.stat().st_dev+1, st_uid=os.geteuid())
        with self.assertRaises(r.GateError):
            r._check_info(info, self.work.stat().st_dev)

    def test_detected_mount_rejected_before_delete(self):
        actual = r.os.path.ismount
        with patch.object(r.os.path, 'ismount', side_effect=lambda p: Path(p) == self.native/'bin' or actual(p)):
            self.assert_preflight_rejects()

    def test_work_identity_drift_rejected(self):
        self.anchor = (self.anchor[0], self.anchor[1] + 1)
        self.assert_preflight_rejects()

    def test_work_symlink_boundary_rejected(self):
        alias = self.root/'alias'
        alias.symlink_to(self.work, target_is_directory=True)
        with self.assertRaises(r.GateError):
            r.retire_native_tools(alias, self.anchor, self.command)
        self.assert_all_targets()

    def test_target_drift_after_preflight_rejected(self):
        original = r._remove
        def drift(*args):
            (self.native/r.TARGETS[0]).write_text('changed size')
            return original(*args)
        with patch.object(r, '_remove', side_effect=drift):
            with self.assertRaises(r.GateError):
                self.retire()
        self.assert_all_targets()
        self.assertEqual(json.loads((self.work/'native-retirement.json').read_text())['status'], 'FAILED')

    def test_partial_delete_failure_is_failed_and_not_replayable(self):
        original = r._remove
        calls = []
        def fail(parent, name, *args):
            calls.append(name)
            if len(calls) == 3:
                raise PermissionError(13, 'private fixture')
            return original(parent, name, *args)
        with patch.object(r, '_remove', side_effect=fail):
            with self.assertRaises(PermissionError):
                self.retire()
        receipt = json.loads((self.work/'native-retirement.json').read_text())
        self.assertEqual(receipt['status'], 'FAILED')
        self.assertEqual(receipt['retired'], list(r.TARGETS[:2]))
        self.assertNotIn('private fixture', json.dumps(receipt))
        with self.assertRaises((r.GateError, OSError)):
            self.retire()
        self.assertTrue((self.native/'gocache').is_dir())

    def test_success_cannot_be_replayed(self):
        self.retire()
        with self.assertRaises((r.GateError, OSError)):
            self.retire()

    def test_retained_file_drift_aborts_after_deletion(self):
        original = r._remove
        def drift(*args):
            result = original(*args)
            (self.native/'licenses/evidence').write_text('changed')
            return result
        with patch.object(r, '_remove', side_effect=drift):
            with self.assertRaises(r.GateError):
                self.retire()
        self.assertEqual(json.loads((self.work/'native-retirement.json').read_text())['status'], 'FAILED')

    def test_cancellation_before_deletion_preserves_all_targets(self):
        with self.assertRaises(KeyboardInterrupt):
            self.retire(check=Mock(side_effect=KeyboardInterrupt))
        self.assert_all_targets()

    def test_actual_process_death_cannot_create_success_or_enable_replay(self):
        script = """
import json, os, sys
sys.path[:0] = [sys.argv[1], sys.argv[2]]
import resources as r
original = r._remove
def stop(*args):
    original(*args)
    os._exit(23)
r._remove = stop
r.retire_native_tools(sys.argv[3], tuple(json.loads(sys.argv[4])), json.loads(sys.argv[5]))
"""
        child = subprocess.run([sys.executable, '-B', '-c', script, str(CI), str(CI/'ios'),
                                str(self.work), json.dumps(self.anchor), json.dumps(self.command)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(child.returncode, 23, child.stderr.decode())
        self.assertEqual(json.loads((self.work/'native-retirement.json').read_text())['status'], 'FAILED')
        with self.assertRaises((r.GateError, OSError)):
            self.retire()
        self.assertTrue((self.native/'toolchain').is_dir())

    def test_directory_swap_after_preflight_never_follows_external_target(self):
        original = r._remove
        outside = self.root/'external-directory'
        outside.mkdir()
        marker = outside/'marker'
        marker.write_text('preserve')
        def swap(parent, name, *args):
            if name == 'toolchain':
                (self.native/name).rename(self.native/'moved-toolchain-fixture')
                (self.native/name).symlink_to(outside, target_is_directory=True)
            return original(parent, name, *args)
        with patch.object(r, '_remove', side_effect=swap):
            with self.assertRaises(r.GateError):
                self.retire()
        self.assertEqual(marker.read_text(), 'preserve')
        self.assertEqual(json.loads((self.work/'native-retirement.json').read_text())['status'], 'FAILED')

    def test_receipt_preexists_refuses_delete_without_overwrite(self):
        receipt = self.work/'native-retirement.json'
        receipt.write_text('existing fixture evidence')
        with self.assertRaises(FileExistsError):
            self.retire()
        self.assert_all_targets()
        self.assertEqual(receipt.read_text(), 'existing fixture evidence')

    def test_retirement_deadline_fails_without_delete(self):
        with patch.object(r.time, 'monotonic', side_effect=[0, 121]):
            with self.assertRaisesRegex(r.GateError, 'native_retirement_timeout'):
                self.retire()
        self.assert_all_targets()

    def test_no_fd_leak_on_success(self):
        before = len(os.listdir('/dev/fd'))
        self.retire()
        self.assertEqual(len(os.listdir('/dev/fd')), before)

    def test_no_fd_leak_on_preflight_error(self):
        (self.native/'bin/nested/entry').unlink()
        os.mkfifo(self.native/'bin/nested/entry')
        before = len(os.listdir('/dev/fd'))
        self.assert_preflight_rejects()
        self.assertEqual(len(os.listdir('/dev/fd')), before)


if __name__ == '__main__':
    unittest.main()
