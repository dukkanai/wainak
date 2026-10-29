"""Deterministic Linux/Darwin lifecycle models; never signal a real PID."""
import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import signal
import unittest
from unittest.mock import Mock, patch

from ci.ios import diagnostics as d

CANARY = 'SYNTHETIC_PRIVATE_CLEANUP_CANARY'


class GroupModel:
    def __init__(self, host, *, initial='live', race=None, descendant=None,
                 denied=False, poll_denied=False):
        self.host = host
        self.state = initial
        self.race = race
        self.descendant = descendant
        self.descendant_alive = descendant is not None
        self.denied = denied
        self.poll_denied = poll_denied
        self.pid = 45678
        self.returncode = None
        self.stdout = Mock()
        self.events = []
        self.clock = 0
        self.wait_calls = 0

    def monotonic(self):
        self.clock += .25
        return self.clock

    def sleep(self, duration):
        self.clock += duration

    def poll(self):
        self.events.append(('poll', self.state, self.descendant_alive))
        if self.poll_denied:
            raise PermissionError(errno.EACCES, CANARY)
        if self.state == 'zombie':
            self.state = 'reaped'
            self.returncode = 0
        return self.returncode

    def wait(self, timeout):
        assert timeout == 5
        self.wait_calls += 1
        self.events.append(('wait', self.state, self.descendant_alive))
        if self.state == 'live':
            raise d.subprocess.TimeoutExpired(CANARY, timeout)
        self.state = 'reaped'
        self.returncode = 0
        return 0

    def killpg(self, pid, sig):
        assert pid == self.pid
        op = {signal.SIGTERM: 'term', signal.SIGKILL: 'kill', 0: 'probe'}[sig]
        # Exit exactly after poll, before the system call observes the group.
        if self.race == op and self.state == 'live':
            self.state = 'zombie'
            self.race = None
        self.events.append((op, self.state, self.descendant_alive))
        if self.denied:
            raise PermissionError(errno.EPERM, CANARY)
        if self.state == 'reaped' and not self.descendant_alive:
            raise ProcessLookupError(errno.ESRCH, CANARY)
        if self.host == 'darwin' and self.state == 'zombie' and not self.descendant_alive:
            raise PermissionError(errno.EPERM, CANARY)
        if sig in (signal.SIGTERM, signal.SIGKILL):
            if self.state == 'live' and (sig == signal.SIGKILL or self.race not in {'probe', 'kill'}):
                self.state = 'zombie'
            if self.descendant_alive and (self.descendant == 'term' or
                    (self.descendant == 'kill' and sig == signal.SIGKILL)):
                self.descendant_alive = False


class CleanupLifecycle(unittest.TestCase):
    def run_model(self, host, **kwargs):
        group = GroupModel(host, **kwargs)
        selector = Mock()
        with patch.object(d.os, 'killpg', side_effect=group.killpg), \
             patch.object(d.time, 'monotonic', side_effect=group.monotonic), \
             patch.object(d.time, 'sleep', side_effect=group.sleep):
            errors = d.cleanup_process(group, selector)
        self.assertLess(len(group.events), 300)
        self.assertLess(group.clock, 27)
        self.assertEqual(group.wait_calls, 1)
        selector.close.assert_called_once()
        group.stdout.close.assert_called_once()
        self.assertNotIn(CANARY, json.dumps(errors))
        return group, errors

    def test_already_zombie_is_reaped_before_signalling_on_both_platforms(self):
        for host in ('linux', 'darwin'):
            with self.subTest(host=host):
                group, errors = self.run_model(host, initial='zombie')
                self.assertEqual(errors, [])
                self.assertEqual(group.events[:2], [('poll', 'zombie', False), ('term', 'reaped', False)])
                self.assertEqual(group.state, 'reaped')
                self.assertFalse(any(op == 'kill' for op, *_ in group.events))
                self.assertLess(group.clock, 2)

    def test_term_exit_is_collected_during_poll_without_waiting_entire_grace(self):
        for host in ('linux', 'darwin'):
            with self.subTest(host=host):
                group, errors = self.run_model(host)
                self.assertEqual(errors, [])
                self.assertIn(('poll', 'zombie', False), group.events)
                self.assertIn(('probe', 'reaped', False), group.events)
                self.assertFalse(any(op == 'kill' for op, *_ in group.events))
                self.assertLess(group.clock, 3)

    def test_exit_between_poll_and_signal_or_probe_keeps_darwin_eperm(self):
        for host in ('linux', 'darwin'):
            for race, operation in (('term', 'signal_term'), ('probe', 'probe_after_term'), ('kill', 'signal_kill')):
                with self.subTest(host=host, race=race):
                    group, errors = self.run_model(host, race=race)
                    self.assertEqual(group.state, 'reaped')
                    self.assertFalse(group.descendant_alive)
                    expected = [{'operation': operation, 'type': 'PermissionError', 'errno': errno.EPERM}]
                    self.assertEqual(errors, expected if host == 'darwin' else [])
                    # Later absence must not erase the preceding permission error.
                    self.assertTrue(any(state == 'reaped' and op in {'term', 'kill', 'probe'}
                                        for op, state, _ in group.events))

    def test_reaped_leader_never_proves_descendants_gone(self):
        for host in ('linux', 'darwin'):
            for behavior in ('term', 'kill', 'survives'):
                with self.subTest(host=host, descendant=behavior):
                    group, errors = self.run_model(host, initial='zombie', descendant=behavior)
                    self.assertEqual(group.state, 'reaped')
                    if behavior == 'survives':
                        self.assertTrue(group.descendant_alive)
                        self.assertEqual(errors, [{'operation': 'verify_group_gone', 'type': 'UnverifiedProcessGroup'}])
                    else:
                        self.assertFalse(group.descendant_alive)
                        self.assertEqual(errors, [])
                    if behavior in {'kill', 'survives'}:
                        self.assertIn(('kill', 'reaped', True), group.events)

    def test_persistent_permission_denial_never_means_absence(self):
        for host in ('linux', 'darwin'):
            with self.subTest(host=host):
                group, errors = self.run_model(host, initial='zombie', descendant='survives', denied=True)
                self.assertTrue(group.descendant_alive)
                self.assertEqual([e['operation'] for e in errors], [
                    'signal_term', 'probe_after_term', 'signal_kill', 'probe_after_kill',
                    'verify_group_gone', 'verify_group_gone'])
                self.assertTrue(all(e['errno'] == errno.EPERM for e in errors[:-1]))
                self.assertEqual(errors[-1]['type'], 'UnverifiedProcessGroup')

    def test_poll_permission_failure_does_not_suppress_wait_group_check_or_errors(self):
        for host in ('linux', 'darwin'):
            with self.subTest(host=host):
                group, errors = self.run_model(host, initial='zombie', poll_denied=True)
                self.assertEqual(group.state, 'reaped')
                self.assertTrue(any(e == {'operation': 'poll_direct_child', 'type': 'PermissionError',
                    'errno': errno.EACCES} for e in errors))
                self.assertTrue(any(op == 'probe' and state == 'reaped' for op, state, _ in group.events))


class RealOwnedDescendants(unittest.TestCase):
    def test_output_failure_reaps_direct_child_and_terminates_owned_descendant(self):
        from scripts.ci_process import run_bounded
        child_source = """import os,signal,sys,time
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
open(sys.argv[1], 'w').write(str(os.getpid()))
time.sleep(60)
"""
        parent_source = """import os,signal,subprocess,sys,time
from pathlib import Path
signal.signal(signal.SIGTERM, lambda *_: None)
open(sys.argv[1], 'w').write(str(os.getpid()))
child = subprocess.Popen([sys.executable, '-c', sys.argv[3], sys.argv[2]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    deadline = time.monotonic()+3
    while not Path(sys.argv[2]).exists() or not Path(sys.argv[2]).read_text().strip():
        if time.monotonic() > deadline: raise RuntimeError('fixture readiness timeout')
        time.sleep(.01)
    print('x'*8192, flush=True)
    child.wait(timeout=20)
finally:
    if child.poll() is None:
        child.kill()
        child.wait(timeout=3)
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent_file, child_file = root/'parent', root/'child'
            detail = {}
            with self.assertRaisesRegex(RuntimeError, 'output limit'):
                run_bounded([sys.executable, '-c', parent_source, parent_file, child_file, child_source],
                            cwd=root, seconds=5, maximum=128, check=True, diagnostic=detail)
            self.assertEqual(detail['failure_kind'], 'OUTPUT_BOUND')
            for file in (parent_file, child_file):
                pid = int(file.read_text())
                with self.assertRaises(ProcessLookupError):os.kill(pid, 0)
            with self.assertRaises(ProcessLookupError):os.killpg(int(parent_file.read_text()), 0)
            for error in detail['cleanup_errors']:
                self.assertIn(error['operation'], {'signal_term', 'signal_kill',
                    'probe_after_term', 'probe_after_kill', 'verify_group_gone'})
                self.assertEqual(error['type'], 'PermissionError')
                self.assertEqual(error['errno'], errno.EPERM)
            self.assertEqual(detail['cleanup_failed'], bool(detail['cleanup_errors']))


class CleanupProjection(unittest.TestCase):
    def test_allowlisted_fields_only_and_bounded_error_count(self):
        errors = [{'operation': 'signal_term', 'type': 'PermissionError', 'errno': errno.EPERM,
                   'message': CANARY, 'path': CANARY} for _ in range(40)]
        result = d.project_cleanup_errors(errors)
        self.assertEqual(result, {'cleanup_errors': [
            {'operation': 'signal_term', 'type': 'PermissionError', 'errno': errno.EPERM}]*16,
            'cleanup_errors_truncated': True})
        self.assertNotIn(CANARY, json.dumps(result))

    def test_malformed_and_hostile_values_never_reach_logs(self):
        for value in (CANARY, {CANARY: CANARY}, [CANARY], True, None):
            with self.subTest(value_type=type(value)):
                errors = [{'operation': value, 'type': value, 'errno': value, 'extra': CANARY}]
                self.assertEqual(d.project_cleanup_errors(errors), {
                    'cleanup_errors': [{'operation': 'other', 'type': 'Exception'}],
                    'cleanup_errors_truncated': False})
        self.assertNotIn(CANARY, json.dumps(d.project_cleanup_errors(CANARY)))


if __name__ == '__main__':unittest.main()
