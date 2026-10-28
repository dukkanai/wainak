"""Pure mocked lifecycle/error tests. No process, signal, compiler or network execution."""
import contextlib
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

IOS = Path(__file__).resolve().parents[1] / 'ios'
sys.path.insert(0, str(IOS))
try:
    import diagnostics as d
    import build as b
finally:
    sys.path.pop(0)

CANARY = 'PRIVATE_FIXTURE_DO_NOT_PRINT'

class DiagnosticsTests(unittest.TestCase):
    def process(self):
        p = Mock(); p.pid = 45678; p.returncode = 0
        p.wait.return_value = 0
        return p

    def cleanup(self, p=None, selector=None, killer=None):
        p = p or self.process(); selector = selector or Mock()
        clock = iter(range(1000))
        with patch.object(d.os, 'killpg', side_effect=killer or ProcessLookupError()), \
             patch.object(d.time, 'monotonic', side_effect=lambda: next(clock)), \
             patch.object(d.time, 'sleep'):
            return d.cleanup_process(p, selector)

    def test_normal_reaps_and_closes(self):
        p = self.process(); selector = Mock()
        self.assertEqual(self.cleanup(p, selector), [])
        p.wait.assert_called_once_with(timeout=5)
        p.stdout.close.assert_called_once(); selector.close.assert_called_once()

    def test_term_permission_still_attempts_kill_reap_and_close(self):
        p = self.process(); calls = []
        def kill(pid, sig):
            calls.append(sig)
            if sig == d.signal.SIGTERM: raise PermissionError(errno.EPERM, CANARY)
            if sig == d.signal.SIGKILL: raise ProcessLookupError()
        errors = self.cleanup(p, killer=kill)
        self.assertIn(d.signal.SIGKILL, calls)
        self.assertEqual(errors[0]['operation'], 'signal_term')
        p.wait.assert_called_once(); p.stdout.close.assert_called_once()
        self.assertNotIn(CANARY, json.dumps(errors))

    def test_kill_permission_fails_closed(self):
        def kill(pid, sig):
            if sig == d.signal.SIGKILL: raise PermissionError(errno.EPERM, CANARY)
        errors = self.cleanup(killer=kill)
        self.assertIn('signal_kill', [e['operation'] for e in errors])
        self.assertIn('UnverifiedProcessGroup', [e['type'] for e in errors])

    def test_probe_permission_does_not_mean_group_gone(self):
        def kill(pid, sig):
            if sig == 0: raise PermissionError(errno.EPERM, CANARY)
        errors = self.cleanup(killer=kill)
        self.assertIn('probe_after_term', [e['operation'] for e in errors])
        self.assertIn('probe_after_kill', [e['operation'] for e in errors])
        self.assertIn('verify_group_gone', [e['operation'] for e in errors])

    def test_wait_permission_does_not_suppress_fd_close(self):
        p = self.process(); p.wait.side_effect = PermissionError(errno.EPERM, CANARY)
        errors = self.cleanup(p)
        self.assertEqual(errors[0]['operation'], 'reap_direct_child')
        p.stdout.close.assert_called_once()

    def test_wait_timeout_is_reported(self):
        p = self.process(); p.wait.side_effect = d.subprocess.TimeoutExpired(CANARY, 5)
        errors = self.cleanup(p)
        self.assertEqual(errors[0]['type'], 'TimeoutExpired')
        self.assertNotIn(CANARY, json.dumps(errors))

    def test_selector_permission_does_not_suppress_stdout_close(self):
        p = self.process(); sel = Mock(); sel.close.side_effect = PermissionError(errno.EACCES, CANARY)
        errors = self.cleanup(p, sel)
        self.assertEqual(errors[0]['operation'], 'close_selector')
        p.stdout.close.assert_called_once()

    def test_stdout_permission_is_reported(self):
        p = self.process(); p.stdout.close.side_effect = PermissionError(errno.EACCES, CANARY)
        self.assertEqual(self.cleanup(p)[0]['operation'], 'close_stdout')

    def test_absent_child_never_signals(self):
        with patch.object(d.os, 'killpg') as kill:
            self.assertEqual(d.cleanup_process(None, None), [])
            kill.assert_not_called()

    def test_error_projection_never_includes_filename_or_message(self):
        error = PermissionError(errno.EACCES, CANARY, '/private/' + CANARY)
        self.assertEqual(d.safe_error(error), {'type': 'PermissionError', 'errno': errno.EACCES})
        self.assertEqual(d.safe_error(b.GateError(CANARY)), {'type': 'GateError'})
        self.assertEqual(d.safe_error(b.GateError('command_timeout_or_cancel'))['gate'], 'command_timeout_or_cancel')

    def test_native_projection_drops_all_unapproved_fields(self):
        reader = Mock(return_value={'status': 'FAILED', 'native_runtime_test': False,
                                    'failed_stage': 'new-policy-host-tests', 'secret': CANARY, 'commands': [CANARY]})
        value = d.native_summary(Path('/unused'), reader)
        self.assertEqual(value, {'availability': 'present', 'status': 'FAILED', 'failed_stage': 'new-policy-host-tests'})
        reader.assert_called_once_with(Path('/unused'), maximum=1024 * 1024)

    def test_native_unknown_stage_and_unreadable_fail_closed(self):
        for value in [[], {'status': 'FAILED', 'native_runtime_test': False, 'failed_stage': CANARY},
                      {'status': CANARY, 'native_runtime_test': False}]:
            self.assertEqual(d.native_summary(None, Mock(return_value=value))['availability'], 'invalid')
        self.assertEqual(d.native_summary(None, Mock(side_effect=PermissionError(errno.EACCES, CANARY))), {'availability': 'unavailable'})

class DiagnosticReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'result.json'

    def test_real_bounded_regular_projection(self):
        self.path.write_text(json.dumps({'status':'FAILED','native_runtime_test':False,'failed_stage':'preflight','secret':CANARY}))
        value = d.native_summary(self.path)
        self.assertEqual(value['failed_stage'], 'preflight'); self.assertNotIn(CANARY, json.dumps(value))

    def test_symlink_directory_and_fifo_rejected_without_blocking(self):
        target = Path(self.tmp.name)/'target'; target.write_text('{}')
        self.path.symlink_to(target)
        self.assertEqual(d.native_summary(self.path)['availability'], 'unavailable')
        self.path.unlink(); self.path.mkdir()
        self.assertEqual(d.native_summary(self.path)['availability'], 'unavailable')
        self.path.rmdir(); os.mkfifo(self.path)
        self.assertEqual(d.native_summary(self.path)['availability'], 'unavailable')

    def test_opened_read_cap_even_when_stat_size_is_stale(self):
        self.path.write_bytes(b'x' * 65)
        real = os.fstat
        def stale(fd):
            original = real(fd)
            return type('Info', (), {'st_mode': original.st_mode, 'st_size': 0})()
        with patch.object(d.os, 'fstat', stale):
            with self.assertRaises(ValueError): d.read_diagnostic_json(self.path, maximum=64)

    def test_duplicate_and_nonfinite_rejected(self):
        for raw in ['{"status":"FAILED","status":"FAILED"}', '{"value":NaN}']:
            self.path.write_text(raw)
            self.assertEqual(d.native_summary(self.path)['availability'], 'unavailable')

    def test_deep_json_never_masks_original_error(self):
        self.path.write_text('['*10000 + '0' + ']'*10000)
        self.assertEqual(d.native_summary(self.path), {'availability':'unavailable'})

    def test_explicit_depth_bound_is_version_independent(self):
        self.path.write_text('['*65 + '0' + ']'*65)
        self.assertEqual(d.native_summary(self.path), {'availability':'unavailable'})
        self.path.write_text(json.dumps({'text': '[{'*100 + '\\"' + '}]'*100}))
        self.assertIn('text', d.read_diagnostic_json(self.path))

    def test_non_utf8_encodings_cannot_bypass_depth_scanner(self):
        nested = 0
        for _ in range(65): nested = [nested]
        text = json.dumps({'escaped': '\\"', 'nested': nested})
        for encoding in ('utf-16-le', 'utf-16-be', 'utf-32-le', 'utf-32-be'):
            self.path.write_bytes(text.encode(encoding))
            self.assertEqual(d.native_summary(self.path), {'availability':'unavailable'})
        self.path.write_text(json.dumps({'status':'FAILED','native_runtime_test':False,'failed_stage':'preflight','text':'نص اصطناعي'}, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(d.native_summary(self.path)['failed_stage'], 'preflight')

    def test_reader_permission_and_recursion_are_unavailable(self):
        for error in [PermissionError(errno.EACCES,CANARY), RecursionError(CANARY)]:
            self.assertEqual(d.native_summary(self.path, Mock(side_effect=error)), {'availability':'unavailable'})


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); (self.root/'logs').mkdir()
        self.runner = b.Runner.__new__(b.Runner)
        self.runner.work = self.root; self.runner.flutter = self.root/'flutter'
        self.runner.sources = self.runner.flutter_sources = {'source': 'hash'}
        self.runner.sequence = 0; self.runner.results = []; self.runner.cancelled = False; self.runner.env = {}
        self.runner.guard = Mock()
        self.p = Mock(); self.p.pid = 45678; self.p.returncode = 0; self.p.wait.return_value = 0
        self.selector = Mock(); self.selector.get_map.return_value = {}
        self.stdout = io.StringIO()
        patches = [patch.object(b, 'git_snapshot', return_value={'source': 'hash'}),
                   patch.object(b.subprocess, 'Popen', return_value=self.p),
                   patch.object(b.selectors, 'DefaultSelector', return_value=self.selector),
                   patch.object(b, 'cleanup_process', return_value=[])]
        self.mocks = [self.enterContext(p) for p in patches]
        self.enterContext(contextlib.redirect_stdout(self.stdout))

    def run_command(self):
        return self.runner.run('native', ['/never-executed', CANARY])

    def test_success_after_verified_cleanup(self):
        self.assertEqual(self.run_command(), b'')
        self.assertEqual(self.runner.results[-1]['status'], 'PASS')
        self.assertNotIn(CANARY, self.stdout.getvalue())

    def test_primary_permission_preserved_despite_cleanup_permission(self):
        primary = PermissionError(errno.EACCES, CANARY)
        self.runner.guard.side_effect = primary
        self.mocks[-1].return_value = [{'operation': 'close_stdout', 'type': 'PermissionError', 'errno': errno.EPERM}]
        with self.assertRaises(PermissionError) as caught: self.run_command()
        self.assertIs(caught.exception, primary)
        self.assertNotIn(CANARY, self.stdout.getvalue())
        self.assertEqual(self.runner.results[-1]['status'], 'FAILED')

    def test_timeout_preserved_despite_cleanup_permission(self):
        self.selector.get_map.return_value = {'pending': True}
        self.runner.cancelled = True
        self.mocks[-1].return_value = [{'operation': 'signal_term', 'type': 'PermissionError', 'errno': errno.EPERM}]
        with self.assertRaises(b.GateError) as caught: self.run_command()
        self.assertEqual(str(caught.exception), 'command_timeout_or_cancel')
        self.assertIn('command_timeout_or_cancel', self.stdout.getvalue())

    def test_cleanup_failure_after_success_is_failure(self):
        self.mocks[-1].return_value = [{'operation': 'verify_group_gone', 'type': 'UnverifiedProcessGroup'}]
        with self.assertRaises(b.GateError): self.run_command()
        self.assertEqual(self.runner.results[-1]['status'], 'FAILED')

    def test_private_log_permission_preserves_primary(self):
        primary = b.GateError('command_failed_native'); self.p.wait.side_effect = primary
        real = Path.write_bytes
        def write(path, data):
            if path.suffix == '.log': raise PermissionError(errno.EACCES, CANARY)
            return real(path, data)
        with patch.object(Path, 'write_bytes', write):
            with self.assertRaises(b.GateError) as caught: self.run_command()
        self.assertIs(caught.exception, primary)
        self.assertIn('write_private_log', self.stdout.getvalue()); self.assertNotIn(CANARY, self.stdout.getvalue())

    def test_commands_manifest_permission_after_success_fails(self):
        real = Path.write_text
        def write(path, *args, **kwargs):
            if path.name == 'commands.json': raise PermissionError(errno.EACCES, CANARY)
            return real(path, *args, **kwargs)
        with patch.object(Path, 'write_text', write):
            with self.assertRaises(b.GateError): self.run_command()
        self.assertIn('write_commands_manifest', self.stdout.getvalue())
        self.assertEqual(self.runner.results[-1]['status'], 'FAILED')

    def test_selector_registration_failure_still_runs_cleanup(self):
        primary = PermissionError(errno.EPERM, CANARY); self.selector.register.side_effect = primary
        with self.assertRaises(PermissionError) as caught: self.run_command()
        self.assertIs(caught.exception, primary); self.mocks[-1].assert_called_once_with(self.p, self.selector)

    def test_spawn_failure_does_not_signal_unknown_group(self):
        primary = PermissionError(errno.EACCES, CANARY); self.mocks[1].side_effect = primary
        with self.assertRaises(PermissionError) as caught: self.run_command()
        self.assertIs(caught.exception, primary); self.mocks[-1].assert_called_once_with(None, None)


    def test_actual_deadline_preserved_despite_cleanup_permission(self):
        self.selector.get_map.return_value = {'pending': True}
        self.mocks[-1].return_value = [{'operation': 'signal_term', 'type': 'PermissionError', 'errno': errno.EPERM}]
        with patch.object(b.time, 'monotonic', side_effect=[0, 0, 1201, 1202]):
            with self.assertRaises(b.GateError) as caught: self.run_command()
        self.assertEqual(str(caught.exception), 'command_timeout_or_cancel')
        self.assertIn('1202', self.stdout.getvalue())

    def test_diagnostic_write_permission_preserves_primary(self):
        primary = b.GateError('command_failed_native'); self.p.wait.side_effect = primary
        real = b.emit
        def emit(event, **data):
            if event == 'command_end': raise PermissionError(errno.EACCES, CANARY)
            return real(event, **data)
        with patch.object(b, 'emit', emit):
            with self.assertRaises(b.GateError) as caught: self.run_command()
        self.assertIs(caught.exception, primary)

    def test_diagnostic_write_permission_after_success_records_failure(self):
        real = b.emit
        def emit(event, **data):
            if event == 'command_end': raise PermissionError(errno.EACCES, CANARY)
            return real(event, **data)
        with patch.object(b, 'emit', emit):
            with self.assertRaises(b.GateError): self.run_command()
        saved = json.loads((self.root/'commands.json').read_text())
        self.assertEqual(saved[-1]['status'], 'FAILED')
        self.assertNotIn(CANARY, json.dumps(saved))

    def test_generated_file_unlink_permission_still_checks_source(self):
        cfg = self.root/'generated'; cfg.write_text('owned'); sources = {'source': 'hash'}
        with patch.object(Path, 'unlink', side_effect=PermissionError(errno.EACCES, CANARY)):
            errors = b.cleanup_owned_files(True, cfg, b.digest(cfg), sources)
        self.assertEqual(errors[0]['operation'], 'remove_owned_generated_config')
        self.assertEqual(len(errors), 1)
        self.assertTrue(cfg.exists())

    def test_generated_file_drift_never_unlinks(self):
        cfg = self.root/'generated'; cfg.write_text('owned')
        with patch.object(Path, 'unlink') as unlink:
            errors = b.cleanup_owned_files(True, cfg, 'wrong_hash', {'source': 'hash'})
            unlink.assert_not_called()
        self.assertEqual(errors[0]['operation'], 'remove_owned_generated_config')

    def test_final_source_permission_recorded_after_file_cleanup(self):
        cfg = self.root/'generated'; cfg.write_text('owned'); sha = b.digest(cfg)
        with patch.object(b, 'git_snapshot', side_effect=PermissionError(errno.EACCES, CANARY)):
            errors = b.cleanup_owned_files(True, cfg, sha, {'source': 'hash'})
        self.assertFalse(cfg.exists())
        self.assertEqual(errors[0]['operation'], 'final_source_guard')
        self.assertNotIn(CANARY, json.dumps(errors))

    def test_no_success_result_written_before_final_cleanup(self):
        source = (IOS/'build.py').read_text()
        self.assertLess(source.index("'final_source_guard'"), source.index("(work / 'result.json').write_text"))
        self.assertLess(source.index("'final_source_guard'"), source.index("print('PASS unsigned"))

if __name__ == '__main__': unittest.main()
