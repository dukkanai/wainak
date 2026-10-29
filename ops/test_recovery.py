#!/usr/bin/env python3
"""Integration test in a separate, disposable Compose project. Synthetic data only."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import manage


def main():
    os.umask(0o077)
    source = manage.ROOT / 'compose.yaml'
    with tempfile.TemporaryDirectory(prefix='wainek-recovery-test-') as directory:
        root = Path(directory)
        project = 'wainek-test-' + secrets.token_hex(4)
        original = source.read_text()
        if original.count('name: wainak\n') != 1:
            raise RuntimeError('Disposable project boundary cannot be established')
        (root / 'compose.yaml').write_text(original.replace('name: wainak\n', f'name: {project}\n', 1))
        manage.ROOT = root
        manage.RUNTIME = root / '.runtime'
        manage.BACKUPS = root / 'backups'
        manage.COMPOSE = ['docker', 'compose', '--project-directory', str(root), '-f', str(root / 'compose.yaml')]
        try:
            manage.main(['up'])
            manage.main(['status'])
            password = manage.RUNTIME / 'db_password'
            original_secret = password.read_bytes()  # synthetic test project only
            password.write_text('intentionally-wrong-synthetic-password-' + 'x' * 32 + '\n')
            try:
                manage.main(['status'])
            except RuntimeError as error:
                assert 'authentication failed' in str(error)
            else:
                raise AssertionError('Wrong credential was accepted')
            password.write_bytes(original_secret)
            password.unlink()
            try:
                manage.main(['init'])
            except RuntimeError as error:
                assert 'secret is missing' in str(error)
            else:
                raise AssertionError('Missing deployed secret was regenerated')
            assert not password.exists()
            password.write_bytes(original_secret)
            manage.main(['status'])
            manage.sql("CREATE TABLE recovery_fixture (id int PRIMARY KEY, label text NOT NULL, amount numeric(8,2));"
                       "INSERT INTO recovery_fixture VALUES (1, 'وينك اختبار الاستعادة', 15.00), (2, 'synthetic', 1.00);")
            archive = manage.backup()
            expected = manage.sql('SELECT json_agg(t ORDER BY id) FROM recovery_fixture t;')
            try:
                manage.sql('CREATE DATABASE wainak_restore_existing;', 'postgres')
                manage.sql("CREATE FUNCTION marker() RETURNS integer LANGUAGE sql AS 'SELECT 42';", 'wainak_restore_existing')
                manage.restore_empty(archive, 'wainak_restore_existing', trusted_source=True)
            except RuntimeError as error:
                assert 'already exists' in str(error)
            else:
                raise AssertionError('Nonempty destination was accepted')
            assert manage.sql('SELECT marker();', 'wainak_restore_existing') == '42'
            assert manage.sql('SELECT json_agg(t ORDER BY id) FROM recovery_fixture t;') == expected
            corrupt = archive.with_name('corrupt.dump')
            corrupt.write_bytes(archive.read_bytes() + b'corruption')
            corrupt.with_suffix('.json').write_text(archive.with_suffix('.json').read_text())
            try:
                with manage.verified_archive(corrupt, trusted_source=True):
                    pass
            except RuntimeError:
                pass
            else:
                raise AssertionError('Corrupt backup was accepted')
            manage.restore_drill(archive, trusted_source=True)
            manage.restore_empty(archive, 'wainak_restore_verified', trusted_source=True)
            actual = manage.sql('SELECT json_agg(t ORDER BY id) FROM recovery_fixture t;', 'wainak_restore_verified')
            assert json.loads(actual) == json.loads(expected), 'Restored data mismatch'
            assert manage.sql("SELECT datconnlimit FROM pg_database WHERE datname='wainak_restore_verified';", 'postgres') == '0'
            assert manage.sql('SELECT json_agg(t ORDER BY id) FROM recovery_fixture t;') == expected

            def race():
                try:
                    manage.restore_empty(archive, 'wainak_restore_race', trusted_source=True)
                    return 'restored'
                except (RuntimeError, subprocess.CalledProcessError):
                    return 'rejected'

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: race(), range(2)))
            assert sorted(results) == ['rejected', 'restored'], results
            assert manage.sql('SELECT json_agg(t ORDER BY id) FROM recovery_fixture t;', 'wainak_restore_race') == expected

            invalid = archive.with_name('invalid-format.dump')
            invalid.write_bytes(b'not a PostgreSQL archive')
            invalid.with_suffix('.json').write_text(json.dumps({'sha256': manage.digest(invalid), 'bytes': invalid.stat().st_size}))
            try:
                manage.restore_empty(invalid, 'wainak_restore_failed', trusted_source=True)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError('Invalid archive format was accepted')
            assert manage.sql("SELECT datconnlimit FROM pg_database WHERE datname='wainak_restore_failed';", 'postgres') == '0'
            assert manage.sql('SELECT json_agg(t ORDER BY id) FROM recovery_fixture t;') == expected
            print('PASS: real TCP credential validation, missing-secret refusal, independent drill, NEW-database restore, concurrent creation, failure isolation, Arabic text and amounts.')
        finally:
            # This generated project contains only this test's synthetic data.
            manage.run(manage.COMPOSE + ['down', '--volumes'], stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
