#!/usr/bin/env python3
"""Run explicit host Flutter gates; machine output must prove execution, not a skip."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import tempfile
from ci_process import run_bounded
from backend.integration.flutter_driver_diagnostics import project as project_driver

ROOT = Path(__file__).resolve().parents[1]
MOBILE = ROOT / 'apps/mobile'
DEFAULT_SKIPS = Counter({name: 1 for name in (
    'native_backend_integration_test.dart', 'identity_live_widget_test.dart',
    'identity_matching_live_widget_test.dart', 'local_cards_entrypoint_test.dart',
    'native_archive_platform_test.dart',
)})


def validate_matching_probe(output, returncode):
    lines = output.splitlines()
    summaries = [line for line in lines if line.startswith('QA_MATCHING_RACES ')]
    match = re.fullmatch(r'QA_MATCHING_RACES passed=([0-9]{1,3}) failed=0', summaries[0]) if len(summaries) == 1 else None
    if (returncode or match is None or not lines or lines[-1] != summaries[0]
            or int(match[1]) < 4
            or sum(line.startswith('PASS ') for line in lines) != int(match[1])
            or any(line.startswith('FAIL ') for line in lines)):
        raise RuntimeError('Independent matching race probe did not pass all required cases')
    return {'passed': int(match[1]), 'failed': 0}


def validate_events(output, returncode, allowed_skips=None):
    suites, tests, outcomes = {}, {}, {}
    completed = False
    completion_count = 0
    errors = False
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue  # Flutter may prepend non-JSON tool status; never emit it.
        if (isinstance(event, list) and len(event) == 1 and isinstance(event[0], dict)
                and set(event[0]) == {'event', 'params'}
                and event[0]['event'] == 'test.startedProcess'
                and isinstance(event[0]['params'], dict)
                and set(event[0]['params']) == {'vmServiceUri'}
                and (event[0]['params']['vmServiceUri'] is None
                     or isinstance(event[0]['params']['vmServiceUri'], str))):
            continue  # Flutter's daemon envelope is metadata, never a test outcome.
        if not isinstance(event, dict):
            raise RuntimeError('Malformed Flutter event')
        kind = event.get('type')
        if kind == 'suite':
            if event['suite']['id'] in suites:
                raise RuntimeError('Duplicate Flutter suite')
            suites[event['suite']['id']] = Path(event['suite']['path']).name
        elif kind == 'testStart':
            if event['test']['id'] in tests:
                raise RuntimeError('Duplicate Flutter test execution')
            tests[event['test']['id']] = event['test']
        elif kind == 'testDone':
            if event['testID'] in outcomes:
                raise RuntimeError('Duplicate Flutter test outcome')
            outcomes[event['testID']] = event
        elif kind == 'error':
            errors = True
        elif kind == 'done':
            completion_count += 1
            if completion_count != 1:
                raise RuntimeError('Duplicate Flutter completion event')
            completed = event.get('success') is True
    passed = 0
    skipped = Counter()
    for identity, outcome in outcomes.items():
        test = tests.get(identity)
        if test is None:
            raise RuntimeError('Flutter outcome has no matching test start')
        if outcome.get('result') != 'success':
            errors = True
        if outcome.get('hidden'):
            continue
        if outcome.get('skipped'):
            skipped[suites.get(test['suiteID'], 'unknown')] += 1
        elif outcome.get('result') == 'success':
            passed += 1
        else:
            errors = True
    if set(tests) != set(outcomes):
        errors = True
    if returncode or errors or not completed or not passed or skipped != (allowed_skips or Counter()):
        raise RuntimeError('Flutter execution failed, incomplete, or contains unexpected skipped tests')
    return {'passed': passed, 'skipped_by_file': dict(skipped)}


def run_gate(flutter, label, args, env, skips=None):
    result = run_bounded([flutter, 'test', '--no-pub', '--concurrency=1', '--machine', *args],
                         cwd=MOBILE, env=env, seconds=600,
                         cleanup_grace=120 if any(env.get(flag) == '1' for flag in
                            ('WAINEK_RUN_IDENTITY_WIDGET', 'WAINEK_RUN_MATCHING_WIDGET')) else 0)
    try:
        summary = validate_events(result.stdout, result.returncode, skips)
    except Exception:
        print(json.dumps({'gate': label, 'status': 'FAILED', 'returncode': result.returncode,
                          'raw_output': 'withheld; reproduce the named test locally'}), flush=True)
        raise
    print(json.dumps({'gate': label, 'status': 'PASS', **summary}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools-root', required=True, type=Path)
    parser.add_argument('--identity-python', required=True, type=Path)
    args = parser.parse_args()
    tools = args.tools_root.resolve(strict=True)
    flutter = tools / 'flutter/bin/flutter'
    python = args.identity_python.absolute()
    if not flutter.is_file() or not python.is_file():
        raise SystemExit('Explicit Flutter and identity Python are required')
    with tempfile.TemporaryDirectory(prefix='wainek-identity-home-', dir=tools) as fixture_home:
        run_checks(tools, flutter, python, Path(fixture_home).resolve(strict=True))


def run_checks(tools, flutter, python, fixture_home):
    env = dict(os.environ, PUB_CACHE=str(tools / 'pub-cache'), CI='true', FLUTTER_SUPPRESS_ANALYTICS='true',
               WAINEK_IDENTITY_FIXTURE_PYTHON=str(python), WAINEK_IDENTITY_FIXTURE_HOME=str(fixture_home),
               WAINEK_IDENTITY_FIXTURE_SCRIPT=str(ROOT / 'backend/integration/serve_identity_fixture.py'))
    for key in ('WAINEK_RUN_IDENTITY_WIDGET', 'WAINEK_RUN_MATCHING_WIDGET', 'WAINEK_BACKEND_ROOT',
                'WAINEK_TEST_BASE_URL', 'WAINEK_TEST_CONTROL_DIR'):
        env.pop(key, None)
    run_bounded([flutter, 'pub', 'get', '--enforce-lockfile'], cwd=MOBILE, env=env, check=True)
    run_bounded([flutter, 'analyze', '--no-pub'], cwd=MOBILE, env=env, check=True, seconds=180)
    run_gate(flutter, 'default host suite', [], env, DEFAULT_SKIPS)
    probe = run_bounded([tools / 'flutter/bin/dart', ROOT / 'qa/phase3_matching/matching_race_probe.dart'],
                        cwd=ROOT, env=env, seconds=90)
    print(json.dumps({'gate': 'independent matching race probe', 'status': 'PASS',
                      **validate_matching_probe(probe.stdout, probe.returncode)}), flush=True)
    run_gate(flutter, 'internal TestFlight fake entrypoint', ['--dart-define=WAINEK_DEV_MODE=true',
        '--dart-define=WAINEK_REPOSITORY=fake', 'test/testflight_entrypoint_test.dart'], env)
    run_gate(flutter, 'local cards entrypoint', ['--dart-define=WAINEK_DEV_MODE=true',
        '--dart-define=WAINEK_REPOSITORY=local_cards', 'test/local_cards_entrypoint_test.dart'], env)
    run_gate(flutter, 'native archive entrypoint', ['--dart-define=WAINEK_DEV_MODE=true',
        '--dart-define=WAINEK_REPOSITORY=native_archive', 'test/native_archive_entry_test.dart'], env)
    run_gate(flutter, 'iOS platform host fixture', ['--dart-define=WAINEK_DEV_MODE=true',
        '--dart-define=WAINEK_REPOSITORY=native_archive', '--dart-define=WAINEK_IOS_ARCHIVE_PREVIEW=true',
        'test/native_archive_platform_test.dart'], env)
    for label, test, flag in (
        ('identity HTTP PostgreSQL widgets', 'identity_live_widget_test.dart', 'WAINEK_RUN_IDENTITY_WIDGET'),
        ('matching HTTP PostgreSQL widgets', 'identity_matching_live_widget_test.dart', 'WAINEK_RUN_MATCHING_WIDGET'),
    ):
        run_gate(flutter, label, ['test/' + test], dict(env, **{flag: '1'}))
    result = run_bounded([python, 'backend/integration/run_flutter_postgres.py', '--run-flutter-postgres',
                          '--mobile-root', MOBILE, '--tools-root', tools], cwd=ROOT, env=env,
                         seconds=600, cleanup_grace=120)
    summary = project_driver(result.stdout, result.returncode)
    print(json.dumps({'gate': 'native HTTP PostgreSQL driver', **summary}), flush=True)
    if summary['status'] != 'PASS':
        raise RuntimeError('Native HTTP PostgreSQL driver failed; see fixed-schema diagnostic above')
    print('PASS: native HTTP PostgreSQL driver completed its required marker protocol.', flush=True)
    run_bounded(['git', 'diff', '--exit-code', '--', 'apps/mobile/pubspec.lock'], cwd=ROOT, check=True)
    print('PASS: Flutter host, explicit preview, authenticated HTTP and durable PostgreSQL gates. No device runtime claim.')


if __name__ == '__main__':
    main()
