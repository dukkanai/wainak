"""Real local process probes and hostile-data tests; no Apple or cloud calls."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import errno
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from ci.testflight import build as b
from ci.testflight import diagnostics as d
from scripts import ci_process as process

CANARY = 'SYNTHETIC_PRIVATE_DIAGNOSTIC_CANARY'


class SafeCommandDiagnostics(unittest.TestCase):
    def probe(self, case):
        output = io.StringIO()
        source = 'import os,sys; print(os.environ["HOME"]); print(sys.argv[1],file=sys.stderr)'
        if case == 'nonzero':
            source += '; sys.exit(7)'
        if case == 'flood':
            source = 'print("x" * 8192)'
        if case == 'timeout':
            source = 'import time; time.sleep(60)'
        real_cleanup = process.cleanup_process
        observed_errors = []

        def observed_cleanup(proc, selector):
            errors = real_cleanup(proc, selector)
            observed_errors.extend(errors)
            if proc is not None:
                # Independent terminal proof, not an OS-name expectation:
                # collect the child and prove the entire owned group is absent.
                self.assertIsNotNone(proc.returncode)
                with self.assertRaises(ProcessLookupError):os.killpg(proc.pid, 0)
            # An exit between poll and killpg may still yield EPERM. Retain it
            # and require the precise bounded error plus the terminal proof above.
            for error in errors:
                self.assertIn(error['operation'], {'signal_term', 'signal_kill',
                    'probe_after_term', 'probe_after_kill', 'verify_group_gone'})
                self.assertEqual(error['type'], 'PermissionError')
                self.assertEqual(error['errno'], errno.EPERM)
            return errors

        def uncertain_cleanup(*args):
            # Always perform the real cleanup first; simulate only the outcome.
            result = observed_cleanup(*args)
            if case in {'cleanup_raise', 'primary_cleanup_raise'}:
                raise RuntimeError(CANARY)
            if case in {'eperm_cleanup', 'primary_eperm_cleanup'}:
                return result + [{'operation': 'signal_kill', 'type': 'PermissionError',
                                  'errno': errno.EPERM, 'message': CANARY}]
            return result + [{'operation': CANARY, 'type': CANARY}]

        def runner(command, **kwargs):
            kwargs['seconds'] = .2 if case == 'timeout' else 5
            kwargs['maximum'] = 128 if case == 'flood' else 16*1024*1024
            return process.run_bounded(command, **kwargs)

        with tempfile.TemporaryDirectory(prefix='wainek-diagnostic-test-') as directory, ExitStack() as stack:
            root = Path(directory).resolve(strict=True)
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(output))
            stack.enter_context(mock.patch.object(d.shutil, 'disk_usage', return_value=mock.Mock(free=8*1024**3)))
            if case in {'cleanup', 'cleanup_raise', 'primary_and_cleanup', 'primary_cleanup_raise', 'eperm_cleanup', 'primary_eperm_cleanup'}:
                stack.enter_context(mock.patch.object(process, 'cleanup_process', side_effect=uncertain_cleanup))
            else:
                stack.enter_context(mock.patch.object(process, 'cleanup_process', side_effect=observed_cleanup))
            if case in {'primary_and_cleanup', 'primary_cleanup_raise', 'primary_eperm_cleanup'}:
                source += '; sys.exit(7)'
            if case == 'spawn':
                stack.enter_context(mock.patch.object(process.subprocess, 'Popen', side_effect=PermissionError(CANARY)))
            if case in {'cancel', 'other'}:
                error = InterruptedError(CANARY) if case == 'cancel' else RuntimeError(CANARY)
                stack.enter_context(mock.patch.object(process.selectors.DefaultSelector, 'select', side_effect=error))
            caught = None
            try:
                result = d.run_command('entry_test', [sys.executable, '-c', source, CANARY],
                    cwd=root, root=root, env=b.child_environment({'HOME': CANARY}),
                    deadline=time.monotonic()+10, runner=runner)
            except BaseException as error:
                caught = error
            if case == 'success':
                self.assertIsNone(caught)
                self.assertIn(CANARY, result)  # Captured internally, never logged.
            else:
                self.assertIsNotNone(caught)
        raw = output.getvalue()
        self.assertNotIn(CANARY, raw)
        self.assertNotIn(directory, raw)
        rows = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['outcome'], 'START')
        self.assertEqual(rows[1]['outcome'], 'PASS' if case == 'success' else 'FAILED')
        self.assertEqual(rows[1]['command'], 'entry_test')
        self.assertEqual(rows[1]['stage'], 'flutter_host_checks')
        self.assertGreaterEqual(rows[1]['elapsed_seconds'], 0)
        self.assertEqual(rows[0]['exit_code'], None)
        expected_errors = list(observed_errors)
        if case in {'cleanup', 'primary_and_cleanup'}:
            expected_errors.append({'operation': 'other', 'type': 'Exception'})
        elif case in {'eperm_cleanup', 'primary_eperm_cleanup'}:
            expected_errors.append({'operation': 'signal_kill', 'type': 'PermissionError', 'errno': errno.EPERM})
        elif case in {'cleanup_raise', 'primary_cleanup_raise'}:
            expected_errors.append({'operation': 'cleanup_process', 'type': 'Exception'})
        self.assertEqual(rows[1]['cleanup_errors'], expected_errors)
        self.assertFalse(rows[1]['cleanup_errors_truncated'])
        self.assertEqual(rows[1]['cleanup_failed'], bool(expected_errors))
        if case == 'primary_cleanup_raise':
            self.assertEqual(caught.args, ('Host CI command failed with exit code 7',))
        return rows[1], caught

    def test_real_process_failure_classes_and_canary_isolation(self):
        cases = {'success': ('NONE', 0), 'nonzero': ('NONZERO_EXIT', 7),
                 'flood': ('OUTPUT_BOUND', None), 'timeout': ('TIMEOUT', None),
                 'spawn': ('SPAWN_OR_IO', None), 'cancel': ('CANCELLED', None),
                 'other': ('OTHER', None), 'cleanup': ('CLEANUP', 0),
                 'cleanup_raise': ('CLEANUP', 0), 'primary_and_cleanup': ('NONZERO_EXIT', 7),
                 'primary_cleanup_raise': ('NONZERO_EXIT', 7),
                 'eperm_cleanup': ('CLEANUP', 0), 'primary_eperm_cleanup': ('NONZERO_EXIT', 7)}
        for case, (kind, code) in cases.items():
            with self.subTest(case=case):
                row, error = self.probe(case)
                self.assertEqual(row['failure_kind'], kind)
                self.assertEqual(row['exit_code'], code)
                if error is not None:
                    for attribute in ('stdout', 'stderr', 'output'):
                        self.assertFalse(hasattr(error, attribute))

    def test_grace_permission_error_is_retained_after_successful_fallback_cleanup(self):
        real_killpg = process.os.killpg
        attempts = []
        def first_term_denied(pgid, sig):
            self.assertNotEqual(pgid, os.getpgrp())
            attempts.append(sig)
            if len(attempts) == 1:
                raise PermissionError(errno.EPERM, CANARY)
            return real_killpg(pgid, sig)
        detail = {}
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(process.os, 'killpg', side_effect=first_term_denied), \
             redirect_stdout(io.StringIO()) as output, redirect_stderr(output):
            with self.assertRaises(TimeoutError):
                process.run_bounded([sys.executable, '-c', 'import time; time.sleep(60)'],
                    cwd=directory, seconds=.2, cleanup_grace=1, check=True, diagnostic=detail)
        self.assertEqual(detail['failure_kind'], 'TIMEOUT')
        self.assertTrue(detail['cleanup_failed'])
        self.assertIn({'operation': 'grace_cleanup', 'type': 'PermissionError', 'errno': errno.EPERM},
                      detail['cleanup_errors'])
        self.assertGreater(len(attempts), 1)
        self.assertNotIn(CANARY, json.dumps(detail)+output.getvalue())

    def test_emitted_cleanup_details_reproject_canaries_and_keep_truncation(self):
        errors = [{'operation': 'signal_term', 'type': 'PermissionError', 'errno': errno.EPERM,
                   'message': CANARY}]*40
        with redirect_stdout(io.StringIO()) as output:
            d.emit_command('entry_test', 'FAILED', time.monotonic(), {
                'failure_kind': 'CLEANUP', 'cleanup_failed': True, 'cleanup_errors': errors})
        row = json.loads(output.getvalue())
        self.assertTrue(row['cleanup_failed'])
        self.assertTrue(row['cleanup_errors_truncated'])
        self.assertEqual(row['cleanup_errors'], [
            {'operation': 'signal_term', 'type': 'PermissionError', 'errno': errno.EPERM}]*16)
        self.assertNotIn(CANARY, output.getvalue())

    def test_disk_and_global_deadline_stop_before_spawn_for_every_command(self):
        for label in d.COMMAND_STAGES:
            for guard in ('disk', 'deadline'):
                with self.subTest(command=label, guard=guard), redirect_stdout(io.StringIO()) as output, \
                     mock.patch.object(d.shutil, 'disk_usage', return_value=mock.Mock(
                         free=0 if guard == 'disk' else 8*1024**3)):
                    runner = mock.Mock()
                    with self.assertRaisesRegex(b.p.PolicyError, '^time_or_disk_limit$'):
                        d.run_command(label, [CANARY], cwd=b.ROOT, env={'HOME': CANARY}, root=b.ROOT,
                            deadline=time.monotonic()+(-1 if guard == 'deadline' else 10), runner=runner)
                    runner.assert_not_called()
                    rows = [json.loads(line) for line in output.getvalue().splitlines()]
                    self.assertEqual([row['outcome'] for row in rows], ['START', 'FAILED'])
                    self.assertEqual(rows[-1]['failure_kind'], 'RESOURCE_GUARD')
                    self.assertEqual(rows[-1]['stage'], d.COMMAND_STAGES[label])
                    self.assertIsNone(rows[-1]['exit_code'])
                    self.assertNotIn(CANARY, output.getvalue())

    def test_global_budget_caps_timeout_without_changing_environment_or_command(self):
        def runner(command, **kwargs):
            self.assertEqual(command, ['public-fixture'])
            self.assertEqual(kwargs['seconds'], 19)
            self.assertEqual(kwargs['env'], {'HOME': CANARY})
            self.assertTrue(kwargs['check'])
            kwargs['diagnostic'].update(failure_kind='NONE', exit_code=0)
            return subprocess.CompletedProcess(command, 0, '', '')
        with mock.patch.object(d.time, 'monotonic', return_value=100), \
             mock.patch.object(d.shutil, 'disk_usage', return_value=mock.Mock(free=4*1024**3)), \
             redirect_stdout(io.StringIO()):
            d.run_command('build_ipa', ['public-fixture'], cwd=b.ROOT, env={'HOME': CANARY},
                          root=b.ROOT, deadline=119, runner=runner, seconds=1200)

    def test_untrusted_metadata_never_becomes_log_text(self):
        for value in (CANARY, [CANARY], {CANARY: CANARY}, True, float('nan')):
            detail = dict.fromkeys(('failure_kind', 'exit_code', 'output_bytes', 'cleanup_failed'), value)
            detail[CANARY] = CANARY
            with redirect_stdout(io.StringIO()) as output:
                d.emit_command('pub_get', 'FAILED', time.monotonic(), detail)
            row = json.loads(output.getvalue())
            self.assertEqual(row['failure_kind'], 'OTHER')
            self.assertIsNone(row['exit_code'])
            self.assertIsNone(row['output_bytes'])
            self.assertNotIn(CANARY, output.getvalue())

    def test_unknown_command_is_rejected_before_execution_and_logging(self):
        runner = mock.Mock()
        with redirect_stdout(io.StringIO()) as output, self.assertRaisesRegex(ValueError, '^Unknown diagnostic identity$'):
            d.run_command(CANARY, [CANARY], cwd=b.ROOT, env={}, root=b.ROOT,
                          deadline=time.monotonic()+10, runner=runner)
        runner.assert_not_called()
        self.assertEqual(output.getvalue(), '')

    def test_outer_error_hides_message_dynamic_type_output_and_environment(self):
        custom_error = type(CANARY, (Exception,), {})
        errors = [RuntimeError(CANARY), custom_error(CANARY), KeyboardInterrupt(CANARY), SystemExit(CANARY),
                  subprocess.CalledProcessError(7, [CANARY], output=CANARY, stderr=CANARY)]
        for error in errors:
            with self.subTest(kind=type(error)), mock.patch.object(b, 'execute', side_effect=error), \
                 mock.patch.object(sys, 'argv', ['build.py', '--build-internal']), \
                 mock.patch.dict(b.os.environ, {'CM_API_TOKEN': CANARY}), \
                 redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(b.main(), 1)
                self.assertNotIn(CANARY, output.getvalue()+stderr.getvalue())
                self.assertEqual(json.loads(output.getvalue()), {
                    'status': 'FAILED', 'raw_output': 'withheld', 'error_type': d.error_type(error)})


class SafeHostDiagnostics(unittest.TestCase):
    def test_real_filesystem_and_alias_probe_prints_no_paths_or_environment_values(self):
        with tempfile.TemporaryDirectory(prefix='wainek-host-test-') as directory:
            root = Path(directory).resolve(strict=True)
            alias = root/CANARY
            alias.symlink_to(root, target_is_directory=True)
            work = root/'work'
            work.mkdir()
            with mock.patch.dict(d.os.environ, {'CM_BUILD_DIR': str(alias), 'PUB_CACHE': CANARY, 'HOME': CANARY}), \
                 redirect_stdout(io.StringIO()) as output:
                d.emit_host(root, work, '3.47.8', '3.13.7')
            self.assertNotIn(CANARY, output.getvalue())
            self.assertNotIn(directory, output.getvalue())
            row = json.loads(output.getvalue())
            self.assertTrue(row['checkout_resolves_to_root'])
            self.assertTrue(row['pub_cache_explicit'])
            self.assertIs(type(row['case_sensitive_volume']), bool)
            probe = root/'IndependentCase'
            probe.touch()
            self.assertEqual(row['case_sensitive_volume'], not (root/'independentcase').exists())
            self.assertEqual(list(work.iterdir()), [])
            self.assertEqual(row['flutter'], '3.47.8')
            self.assertEqual(row['python'], '.'.join(str(n) for n in sys.version_info[:3]))

    def test_host_untrusted_version_architecture_and_probe_failure_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(d.sys, 'platform', 'darwin'), \
             mock.patch.object(d.platform, 'machine', return_value=CANARY), \
             mock.patch.object(d.platform, 'mac_ver', return_value=(CANARY, (), '')), \
             mock.patch.object(d.tempfile, 'TemporaryDirectory', side_effect=PermissionError(CANARY)), \
             mock.patch.dict(d.os.environ, {'CM_BUILD_DIR': CANARY}), \
             redirect_stdout(io.StringIO()) as output:
            d.emit_host(Path(directory), Path(directory), CANARY, CANARY)
        row = json.loads(output.getvalue())
        self.assertNotIn(CANARY, output.getvalue())
        self.assertEqual(row['macos'], 'UNKNOWN')
        self.assertEqual(row['architecture'], 'OTHER')
        self.assertEqual(row['flutter'], 'UNKNOWN')
        self.assertEqual(row['dart'], 'UNKNOWN')
        self.assertIsNone(row['case_sensitive_volume'])
        self.assertFalse(row['checkout_resolves_to_root'])


if __name__ == '__main__':
    unittest.main()
