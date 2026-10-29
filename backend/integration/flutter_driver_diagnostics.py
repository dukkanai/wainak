"""Fixed-schema diagnostics for the synthetic Flutter/PostgreSQL host driver."""
import json
import re

PREFIX = 'WAINEK_FLUTTER_POSTGRES_DIAGNOSTIC '
STAGES = frozenset({'harness', 'preflight', 'control_setup', 'http_start', 'flutter_start',
                   'wait_active', 'restart_active', 'wait_blocked', 'restart_blocked',
                   'flutter_complete', 'cleanup_flutter', 'cleanup_output', 'cleanup_http', 'complete'})
ERROR_TYPES = frozenset({'RuntimeError', 'KeyboardInterrupt', 'TimeoutExpired', 'TimeoutError',
                        'PermissionError', 'FileNotFoundError', 'FileExistsError', 'ProcessLookupError',
                        'EOFError', 'ConnectionResetError', 'HTTPError', 'URLError', 'OperationalError',
                        'InterfaceError', 'AssertionError', 'OSError', 'ValueError'})
MESSAGES = {
    'Temporary Flutter process group did not stop': 'flutter_group_survived',
    'Temporary HTTP process did not stop': 'http_process_survived',
    'Unexpected test control marker content': 'marker_content_invalid',
    'Unexpected test control marker type, owner or size': 'marker_metadata_invalid',
    'Test control marker changed during validation': 'marker_changed',
    'Temporary HTTP server did not report readiness': 'http_readiness_timeout',
    'Unexpected temporary loopback port': 'http_port_invalid',
    'HTTP server is not the synthetic PostgreSQL adapter': 'http_health_invalid',
    "Restart changed the test client's loopback address": 'http_port_changed',
    'Flutter exited before the active persistence checkpoint': 'flutter_before_active',
    'Flutter exited before the blocked persistence checkpoint': 'flutter_before_blocked',
    'Flutter did not reach the active checkpoint in time': 'active_checkpoint_timeout',
    'Flutter did not reach the blocked checkpoint in time': 'blocked_checkpoint_timeout',
    'Flutter did not finish after the persistence checkpoints': 'flutter_completion_timeout',
    'Both real process/database restart checkpoints are required': 'checkpoints_incomplete',
    'Flutter test source changed during this run': 'test_source_changed',
}
CODES = frozenset(MESSAGES.values()) | {'ok', 'unexpected_error', 'cancelled', 'timeout',
                                     'flutter_exit_nonzero', 'postgres_checks_failed'}


def error_code(error):
    # Message values are compared, never copied into diagnostics.
    if isinstance(error, KeyboardInterrupt):
        return 'cancelled'
    if type(error).__name__ in {'TimeoutError', 'TimeoutExpired'}:
        return 'timeout'
    if type(error) is RuntimeError:
        message = str(error)
        if message in MESSAGES:
            return MESSAGES[message]
        if re.fullmatch(r'Flutter integration test failed with exit -?[0-9]{1,4}', message):
            return 'flutter_exit_nonzero'
    return 'unexpected_error'


def emit(stage, status, code='ok', error=None):
    kind = type(error).__name__ if error is not None else 'none'
    if kind not in ERROR_TYPES:
        kind = 'none' if error is None else 'Exception'
    row = {'schema': 1, 'stage': stage, 'status': status, 'code': code, 'error_type': kind}
    validate(row)
    print(PREFIX + json.dumps(row, sort_keys=True), flush=True)


def validate(row):
    if (not isinstance(row, dict)
            or set(row) != {'schema', 'stage', 'status', 'code', 'error_type'}
            or type(row['schema']) is not int or row['schema'] != 1
            or row['stage'] not in STAGES or row['status'] not in {'RUNNING', 'PASS', 'FAILED'}
            or row['code'] not in CODES or row['error_type'] not in ERROR_TYPES | {'none', 'Exception'}
            or (row['status'] != 'FAILED' and (row['code'] != 'ok' or row['error_type'] != 'none'))):
        raise RuntimeError('Invalid fixed Flutter driver diagnostic')


class Progress:
    def __init__(self):
        self.stage = 'preflight'
        self.failure_reported = False

    def step(self, stage):
        self.stage = stage
        emit(stage, 'RUNNING')

    def failure(self, error):
        self.failure_reported = True
        emit(self.stage, 'FAILED', error_code(error), error)

    def call(self, stage, function):
        self.step(stage)
        try:
            return function()
        except BaseException as error:
            self.failure(error)
            raise


def project(output, returncode):
    """Only return approved enums; raw logs, paths, exception text stay private."""
    events = []
    for line in output.splitlines():
        if not line.startswith(PREFIX):
            continue
        if len(line) > 1024 or len(events) >= 64:
            raise RuntimeError('Flutter driver diagnostic bound exceeded')
        try:
            row = json.loads(line[len(PREFIX):])
            validate(row)
        except (TypeError, ValueError, KeyError) as error:
            raise RuntimeError('Malformed Flutter driver diagnostic') from None
        events.append(row)
    failures = [row for row in events if row['status'] == 'FAILED']
    complete = [row for row in events if row['stage'] == 'complete' and row['status'] == 'PASS']
    terminal = [row for row in events if row['stage'] == 'harness' and row['status'] != 'RUNNING']
    passed = (returncode == 0 and not failures and len(complete) == 1 and len(terminal) == 1
              and terminal[0]['status'] == 'PASS' and events[-1] == terminal[0])
    return {'status': 'PASS' if passed else 'FAILED', 'returncode': returncode,
            'last_stage': events[-1]['stage'] if events else 'missing_diagnostic',
            'failures': failures, 'diagnostic_events': len(events)}
