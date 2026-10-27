"""Reject false green test wrappers: missing execution, skips, failures and truncation."""
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
import unittest
from run_flutter_ci import validate_events
from run_go_checks import cache_inventory, validate_go_events


def stream(events):
    return '\n'.join(json.dumps(event) for event in events)


class ResultControls(unittest.TestCase):
    def flutter(self, *, skip=False, hidden=False):
        return [
            {'type': 'suite', 'suite': {'id': 0, 'path': '/owned/opt_in_test.dart'}},
            {'type': 'testStart', 'test': {'id': 1, 'suiteID': 0, 'name': 'synthetic'}},
            {'type': 'testDone', 'testID': 1, 'skipped': skip, 'hidden': hidden, 'result': 'success'},
            {'type': 'done', 'success': True},
        ]

    def go(self):
        return [{'Action': 'start', 'Package': 'fixture'},
                {'Action': 'run', 'Test': 'TestFixture'},
                {'Action': 'pass', 'Test': 'TestFixture'}, {'Action': 'pass', 'Package': 'fixture'}]

    def test_flutter_real_completion(self):
        self.assertEqual(validate_events(stream(self.flutter()), 0)['passed'], 1)

    def test_flutter_known_daemon_envelope_is_metadata_only(self):
        envelope = [{'event': 'test.startedProcess', 'params': {'vmServiceUri': 'http://127.0.0.1:12345/'}}]
        self.assertEqual(validate_events(stream([envelope, *self.flutter()]), 0)['passed'], 1)
        envelope[0]['params']['vmServiceUri'] = None
        self.assertEqual(validate_events(stream([envelope, *self.flutter()]), 0)['passed'], 1)
        with self.assertRaises(RuntimeError):
            validate_events(stream([envelope]), 0)
        for event in [[{'event': 'unknown', 'params': {}}], [], 0, True, ['done']]:
            with self.subTest(event=event), self.assertRaises(RuntimeError):
                validate_events(stream([event, *self.flutter()]), 0)

    def test_flutter_duplicate_start_or_suite_is_rejected(self):
        for index in [0, 1]:
            events = self.flutter()
            with self.assertRaises(RuntimeError):
                validate_events(stream([events[index], *events]), 0)

    def test_flutter_failed_incomplete_skipped_or_hidden_is_not_acceptance(self):
        bad = [self.flutter()[:-1], self.flutter(skip=True), self.flutter(hidden=True),
               [{'type': 'done', 'success': True}], self.flutter() + [{'type': 'done', 'success': True}],
               self.flutter()[:-2] + [{'type': 'done', 'success': True}]]
        for events in bad:
            with self.subTest(events=events), self.assertRaises(RuntimeError):
                validate_events(stream(events), 0)
        with self.assertRaises(RuntimeError):
            validate_events(stream(self.flutter()), 1)

    def test_flutter_explicit_skip_allowlist_still_requires_executed_test(self):
        events = self.flutter(skip=True)[:-1]
        events += [{'type': 'testStart', 'test': {'id': 2, 'suiteID': 0, 'name': 'executed'}},
                   {'type': 'testDone', 'testID': 2, 'skipped': False, 'hidden': False, 'result': 'success'},
                   {'type': 'done', 'success': True}]
        self.assertEqual(validate_events(stream(events), 0, Counter({'opt_in_test.dart': 1}))['passed'], 1)
        with self.assertRaises(RuntimeError):
            validate_events(stream(events), 0, Counter({'another_test.dart': 1}))

    def test_flutter_hidden_failure_is_failure(self):
        events = self.flutter(); events[2].update(hidden=True, result='error')
        with self.assertRaises(RuntimeError):
            validate_events(stream(events), 0)

    def test_go_requires_runtime_execution(self):
        self.assertEqual(validate_go_events(stream(self.go()), 0)['passed'], 1)
        with self.assertRaises(RuntimeError):
            validate_go_events(stream([{'Action': 'pass'}]), 0)

    def test_go_missing_start_or_terminal_or_duplicate_rejected(self):
        for events in [self.go()[2:], self.go()[:-1], self.go() + [self.go()[-1]], self.go()[:2] + [self.go()[-1]]]:
            with self.subTest(events=events), self.assertRaises(RuntimeError):
                validate_go_events(stream(events), 0)

    def test_go_fail_or_skip_or_nonzero_rejected(self):
        for action in ['skip', 'fail']:
            events = self.go(); events[2]['Action'] = action
            with self.assertRaises(RuntimeError):
                validate_go_events(stream(events), 0)
        with self.assertRaises(RuntimeError):
            validate_go_events(stream(self.go()), 1)

    def test_go_malformed_stream_rejected(self):
        with self.assertRaises(RuntimeError):
            validate_go_events(stream(self.go()) + '\nnot-json', 0)

    def test_go_cache_inventory_detects_runtime_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {}
            for name in ('GOCACHE', 'GOMODCACHE', 'GOTMPDIR'):
                root = Path(temporary) / name
                root.mkdir(mode=0o700)
                env[name] = str(root)
            path = Path(env['GOCACHE']) / 'fixture'
            path.write_bytes(b'before')
            before = cache_inventory(env)
            path.write_bytes(b'after!')
            self.assertNotEqual(before, cache_inventory(env))
            path.unlink()
            path.symlink_to('/dev/null')
            with self.assertRaises(RuntimeError):
                cache_inventory(env)
            path.unlink()
            os.mkfifo(path)
            with self.assertRaises(RuntimeError):
                cache_inventory(env)


if __name__ == '__main__':
    unittest.main()
