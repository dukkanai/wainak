"""Cache policy and tiny metadata fixtures; no Xcode/compiler/network execution."""
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

CI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CI))
sys.path.insert(0, str(CI/'ios'))
import build as b
import resources as r
import verify as v

CANARY = 'PRIVATE_PATH_AND_CONTENT_DO_NOT_EMIT'


class CachePolicyTests(unittest.TestCase):
    def settings(self, tests=False):
        names = ['Runner', 'RunnerTests'] if tests else ['Runner']
        return [{'target': name, 'buildSettings': {key: 'NO' for key in v.UNCACHED_SETTINGS}}
                for name in names]

    def test_exact_three_controls(self):
        self.assertEqual(v.UNCACHED_SETTINGS, ('COMPILATION_CACHE_ENABLE_CACHING',
            'CLANG_ENABLE_COMPILE_CACHE', 'SWIFT_ENABLE_COMPILE_CACHE'))

    def test_device_settings_and_compile_share_all_no_controls(self):
        base = ['/usr/bin/xcodebuild', '-scheme', 'Runner', *b.SIGNING]
        settings, compile = b.xcode_commands(base, 'iphoneos')
        self.assertEqual(settings[:-2], compile)
        self.assertEqual(compile[-1], 'build')
        self.assertEqual(settings[-2:], ['-showBuildSettings', '-json'])
        for key in v.UNCACHED_SETTINGS:
            self.assertEqual(settings.count(key+'=NO'), 1)
            self.assertEqual(compile.count(key+'=NO'), 1)
        for flag in b.SIGNING:
            self.assertIn(flag, settings)
            self.assertIn(flag, compile)
        self.assertEqual(base, ['/usr/bin/xcodebuild', '-scheme', 'Runner', *b.SIGNING])

    def test_simulator_test_action_shares_all_controls(self):
        settings, compile = b.xcode_commands(['/usr/bin/xcodebuild'], 'iphonesimulator')
        self.assertEqual(compile[-1], 'build-for-testing')
        self.assertIn('build-for-testing', settings)
        self.assertEqual(settings[:-2], compile)
        self.assertNotIn('test', compile)
        self.assertNotIn('test-without-building', compile)

    def test_unknown_sdk_rejected(self):
        with self.assertRaises(v.GateError):
            b.xcode_commands(['/usr/bin/xcodebuild'], 'macosx')

    def test_duplicate_cache_override_rejected(self):
        for key in v.UNCACHED_SETTINGS:
            for value in ('YES', 'NO'):
                with self.subTest(key=key, value=value), self.assertRaises(v.GateError):
                    b.xcode_commands(['/usr/bin/xcodebuild', key+'='+value], 'iphoneos')

    def test_other_module_driver_security_settings_not_disabled(self):
        settings, compile = b.xcode_commands(['/usr/bin/xcodebuild'], 'iphoneos')
        expected = {key+'=NO' for key in v.UNCACHED_SETTINGS}
        self.assertEqual({arg for arg in compile if '=' in arg}, expected)
        self.assertFalse(any('MODULE' in arg or 'INTEGRATED_DRIVER' in arg or 'SANITIZ' in arg
                             for arg in settings))

    def test_device_effective_settings_pass(self):
        got = v.uncached_settings(self.settings(), 'iphoneos')
        self.assertEqual(got['targets_checked'], 1)
        self.assertEqual(got['settings'], {key: 'NO' for key in v.UNCACHED_SETTINGS})

    def test_simulator_requires_and_checks_runner_tests(self):
        got = v.uncached_settings(self.settings(True), 'iphonesimulator')
        self.assertEqual(got['targets_checked'], 2)

    def test_missing_test_target_fails_closed(self):
        with self.assertRaisesRegex(v.GateError, 'cache_policy_test_target_missing'):
            v.uncached_settings(self.settings(), 'iphonesimulator')

    def test_all_target_cache_values_enforced(self):
        for key in v.UNCACHED_SETTINGS:
            for target in range(2):
                for value in ('YES', '', 'false', 0, False, None):
                    rows = self.settings(True)
                    rows[target]['buildSettings'][key] = value
                    with self.subTest(key=key, target=target, value=value), self.assertRaises(v.GateError):
                        v.uncached_settings(rows, 'iphonesimulator')

    def test_missing_value_fails_closed(self):
        for key in v.UNCACHED_SETTINGS:
            rows = self.settings()
            del rows[0]['buildSettings'][key]
            with self.subTest(key=key), self.assertRaises(v.GateError):
                v.uncached_settings(rows, 'iphoneos')

    def test_malformed_shapes_and_duplicate_targets_rejected(self):
        cases = [None, {}, [], [None], [{'target': 'Runner'}],
                 [{'target': 'Runner', 'buildSettings': []}],
                 [{'target': 4, 'buildSettings': {}}],
                 self.settings()+self.settings(),
                 [{'target': 'NotRunner', 'buildSettings': {key: 'NO' for key in v.UNCACHED_SETTINGS}}]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(v.GateError):
                v.uncached_settings(rows, 'iphoneos')

    def test_public_receipt_never_contains_arbitrary_target_names(self):
        rows = self.settings(True)
        rows.append({'target': CANARY, 'buildSettings': {key: 'NO' for key in v.UNCACHED_SETTINGS}})
        self.assertNotIn(CANARY, json.dumps(v.uncached_settings(rows, 'iphonesimulator')))

    def test_gate_failure_emits_fixed_reason_without_private_values(self):
        rows = self.settings()
        rows[0]['buildSettings'][v.UNCACHED_SETTINGS[0]] = CANARY
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(v.GateError):
                b.cache_policy_receipt(rows, 'iphoneos')
        self.assertIn('compile_cache_enabled_or_unknown', out.getvalue())
        self.assertNotIn(CANARY, out.getvalue())

    def test_invalid_sdk_diagnostic_is_redacted(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(v.GateError):
                b.cache_policy_receipt(self.settings(), CANARY)
        self.assertIn('unknown', out.getvalue())
        self.assertNotIn(CANARY, out.getvalue())

    def test_diagnostic_failure_does_not_replace_cache_gate(self):
        with patch.object(b, 'emit', side_effect=PermissionError(13, CANARY)):
            with self.assertRaisesRegex(v.GateError, 'cache_policy_test_target_missing'):
                b.cache_policy_receipt(self.settings(), 'iphonesimulator')


class LargeFileMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.work = self.root/'.ci-work'
        self.work.mkdir()

    def make(self, relative, size=1, sparse=False):
        path = self.work/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as f:
            if sparse:
                f.truncate(size)
            else:
                f.write(b'x'*size)
        return path

    def test_sparse_metadata_not_metric_substitution(self):
        path = self.make('home/Library/Developer/Xcode/DerivedData/CompilationCache.noindex/'+CANARY+'.index',
                         1024*1024, True)
        got = r.large_file_summary(self.work)
        self.assertTrue(got['complete'])
        row = got['rows'][0]
        self.assertEqual(row['role'], 'home_compilation_cache')
        self.assertEqual(row['name_kind'], 'index_suffix')
        self.assertEqual(row['logical_bytes'], path.stat().st_size)
        self.assertEqual(row['allocated_bytes'], path.stat().st_blocks*512)
        self.assertEqual(row['allocation_below_logical'], row['allocated_bytes'] < row['logical_bytes'])
        self.assertGreaterEqual(r.tree_size(self.work), 1024*1024)
        self.assertNotIn(CANARY, json.dumps(got))
        self.assertNotIn(str(self.root), json.dumps(got))

    def test_largest_eight_sorted_and_bounded(self):
        for i in range(16):
            self.make(CANARY+str(i), i+1)
        got = r.large_file_summary(self.work)
        self.assertEqual(len(got['rows']), 8)
        self.assertEqual([x['logical_bytes'] for x in got['rows']], list(range(16, 8, -1)))
        self.assertEqual(got['scanned_regular_files'], 16)
        self.assertNotIn(CANARY, json.dumps(got))

    def test_symlink_and_fifo_not_opened_or_followed(self):
        external = self.root/CANARY
        external.write_text(CANARY)
        (self.work/'link').symlink_to(external)
        os.mkfifo(self.work/'pipe')
        got = r.large_file_summary(self.work)
        self.assertEqual(got['rows'], [])
        self.assertEqual(external.read_text(), CANARY)

    def test_root_symlink_fails_without_following(self):
        target = self.root/'other'
        target.mkdir()
        (target/CANARY).write_text(CANARY)
        alias = self.root/'link'
        alias.symlink_to(target, target_is_directory=True)
        got = r.large_file_summary(alias)
        self.assertFalse(got['complete'])
        self.assertEqual(got['rows'], [])
        self.assertNotIn(CANARY, json.dumps(got))

    def test_hardlink_count_exposed_without_deduplication(self):
        path = self.make('one', 11)
        os.link(path, self.work/'two')
        got = r.large_file_summary(self.work)
        self.assertEqual(len(got['rows']), 2)
        self.assertTrue(all(row['hard_links'] == 2 for row in got['rows']))
        self.assertGreaterEqual(r.tree_size(self.work), 22)

    def test_permission_failure_is_bounded_and_redacted(self):
        with patch.object(r.os, 'open', side_effect=PermissionError(errno.EACCES, CANARY, '/'+CANARY)):
            got = r.large_file_summary(self.work)
        self.assertEqual(got['availability'], 'incomplete')
        self.assertEqual(got['error'], {'type': 'PermissionError', 'errno': errno.EACCES})
        self.assertNotIn(CANARY, json.dumps(got))

    def test_deadline_is_incomplete_not_full_topk_claim(self):
        self.make('file', 1)
        with patch.object(r.time, 'monotonic', side_effect=[0, 2]):
            got = r.large_file_summary(self.work)
        self.assertEqual(got['reason'], 'deadline')
        self.assertFalse(got['complete'])

    def test_entry_limit_is_incomplete(self):
        self.make('a')
        self.make('b')
        got = r.large_file_summary(self.work, maximum_entries=1)
        self.assertEqual(got['reason'], 'entry_limit')
        self.assertEqual(got['visited_entries'], 1)
        self.assertFalse(got['complete'])

    def test_depth_limit_is_incomplete(self):
        self.make('/'.join(['d']*66)+'/a')
        got = r.large_file_summary(self.work)
        self.assertEqual(got['reason'], 'depth_limit')
        self.assertFalse(got['complete'])

    def test_regular_file_contents_never_opened(self):
        self.make('file', 4)
        original = r.os.open
        def only_dirs(path, flags, *args, **kwargs):
            self.assertTrue(flags & os.O_DIRECTORY)
            return original(path, flags, *args, **kwargs)
        with patch.object(r.os, 'open', side_effect=only_dirs):
            got = r.large_file_summary(self.work)
        self.assertTrue(got['complete'])
        self.assertEqual(got['scanned_regular_files'], 1)

    def test_literal_prefix_boundary_not_confused(self):
        self.assertEqual(r._diagnostic_role('derived-iphoneos/ModuleCache.noindex/file'), 'device_module_cache')
        self.assertEqual(r._diagnostic_role('derived-iphoneos/ModuleCache.noindex-INJECT/file'), 'device_derived')
        self.assertEqual(r._diagnostic_role('derived-iphoneos-INJECT/file'), 'other_work')

    def test_all_roles_and_suffixes_are_fixed_labels(self):
        self.make('derived-iphonesimulator/CompilationCache.noindex/'+CANARY+'.data', 3)
        self.make('home/'+CANARY+'.db', 2)
        self.make(CANARY, 1)
        rows = r.large_file_summary(self.work)['rows']
        self.assertEqual([x['role'] for x in rows], ['simulator_compilation_cache', 'home_other', 'other_work'])
        self.assertEqual([x['name_kind'] for x in rows], ['data_suffix', 'database_suffix', 'other'])
        self.assertNotIn(CANARY, json.dumps(rows))

    def test_invalid_diagnostic_bounds_rejected(self):
        for kwargs in ({'maximum_rows': 0}, {'maximum_rows': 9}, {'maximum_entries': 0},
                       {'maximum_entries': 100001}, {'seconds': 0}, {'seconds': 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(v.GateError):
                r.large_file_summary(self.work, **kwargs)

    def test_fd_no_leak_on_success_and_limit(self):
        self.make('nested/a')
        self.make('nested/b')
        before = len(os.listdir('/dev/fd'))
        for _ in range(20):
            r.large_file_summary(self.work)
            r.large_file_summary(self.work, maximum_entries=1)
        self.assertEqual(len(os.listdir('/dev/fd')), before)

    def test_guard_preserves_primary_budget_error_on_diagnostic_error(self):
        runner = b.Runner.__new__(b.Runner)
        runner.work = self.work
        runner.flutter = self.root
        runner.flutter_start = 0
        runner.cancelled = False
        with patch.object(b, 'size', side_effect=[r.LIMIT+1, 0, 0, 0, 0]), \
             patch.object(b, 'large_file_summary', side_effect=PermissionError(13, CANARY)):
            with self.assertRaisesRegex(v.GateError, '^workspace_budget$'):
                runner.guard()
        self.assertEqual(runner.resource_snapshot['total_logical_bytes'], r.LIMIT+1)
        self.assertNotIn(CANARY, json.dumps(runner.resource_snapshot))

    def test_guard_only_collects_diagnostic_on_budget_failure(self):
        runner = b.Runner.__new__(b.Runner)
        runner.work = self.work
        runner.flutter = self.root
        runner.flutter_start = 0
        runner.cancelled = False
        with patch.object(b, 'size', return_value=0), \
             patch.object(r.shutil, 'disk_usage', return_value=Mock(free=r.MIN_FREE)), \
             patch.object(b, 'large_file_summary') as detail:
            runner.guard()
            detail.assert_not_called()

    def test_guard_receipt_includes_diagnostic_and_keeps_same_limit(self):
        runner = b.Runner.__new__(b.Runner)
        runner.work = self.work
        runner.flutter = self.root
        runner.flutter_start = 0
        runner.cancelled = False
        self.make(CANARY, 1024)
        with patch.object(b, 'size', side_effect=[r.LIMIT+1, 0, 0, 0, 0]):
            with self.assertRaisesRegex(v.GateError, '^workspace_budget$'):
                runner.guard()
        self.assertEqual(runner.resource_snapshot['limit_bytes'], 8589934592)
        self.assertEqual(runner.resource_snapshot['work_largest_files']['rows'][0]['logical_bytes'], 1024)
        self.assertNotIn(CANARY, json.dumps(runner.resource_snapshot))


if __name__ == '__main__':
    unittest.main()
