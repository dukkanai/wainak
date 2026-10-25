"""Bounded, value-free diagnostics. Never serialize exception text, argv or logs."""
import errno
import json
import os
import signal
import stat
import subprocess
import time

ERROR_TYPES = {'PermissionError', 'ProcessLookupError', 'FileNotFoundError', 'TimeoutExpired',
               'TimeoutError', 'BrokenPipeError', 'OSError', 'ValueError', 'GateError',
               'KeyboardInterrupt', 'SystemExit'}
GATE_CODES = {'command_timeout_or_cancel', 'command_output_bound', 'source_changed_before_command',
              'source_changed_by_command', 'flutter_source_drift', 'owned_process_group_survived',
              'workspace_budget', 'disk_headroom', 'cancelled', 'command_cleanup_failed'}
LABELS = {'xcode-selection', 'xcode-version', 'flutter-head', 'flutter-source-clean',
          'flutter-version', 'native', 'pub-locked', 'native-dart-tests', 'ios-optin-dart-tests',
          'ios-config', 'settings-iphoneos', 'settings-iphonesimulator', 'compile-iphoneos',
          'compile-iphonesimulator', 'unsigned-iphoneos', 'unsigned-iphonesimulator'}
NATIVE_STAGES = {'preflight', 'authenticated-go-bootstrap', 'authenticated-public-module-acquisition',
                 'pinned-upstream-tool-build', 'new-policy-host-tests', 'unmodified-upstream-apple-bind',
                 'artifact-inspection'}


def safe_error(error):
    kind = type(error).__name__
    row = {'type': kind if kind in ERROR_TYPES else 'Exception'}
    number = getattr(error, 'errno', None)
    if type(number) is int and number in errno.errorcode:
        row['errno'] = number
    # GateError is authored locally, but still require an explicit value allowlist.
    if kind == 'GateError':
        value = str(error)
        if value in GATE_CODES or value in {'command_failed_' + name for name in LABELS}:
            row['gate'] = value
    return row


def emit(event, **fields):
    # Call sites supply only fixed labels and safe_error projections, never arbitrary exceptions.
    print('WAINAK_CI_DIAGNOSTIC ' + json.dumps({'event': event, **fields}, sort_keys=True), flush=True)


def cleanup_process(process, selector):
    """Best-effort owned-group cleanup; uncertainty is returned as failure, never waived.

    Exceptions are collected independently so a denied signal cannot suppress reaping,
    FD closing or the original command exception. No privilege escalation or new target.
    """
    failures = []
    group_gone = process is None

    def record(operation, error):
        failures.append({'operation': operation, **safe_error(error)})

    def probe(operation):
        nonlocal group_gone
        try:
            os.killpg(process.pid, 0)
            return True
        except ProcessLookupError:
            group_gone = True
            return False
        except BaseException as error:
            record(operation, error)
            return None

    if process is not None:
        for sig, delay, label in ((signal.SIGTERM, 15, 'term'), (signal.SIGKILL, 2, 'kill')):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                group_gone = True
                break
            except BaseException as error:
                record('signal_' + label, error)
            end = time.monotonic() + delay
            while time.monotonic() < end:
                if probe('probe_after_' + label) is not True:
                    break
                time.sleep(.05)
            if group_gone:
                break
        try:
            process.wait(timeout=5)
        except BaseException as error:
            record('reap_direct_child', error)
        end = time.monotonic() + 5
        while not group_gone and time.monotonic() < end:
            if probe('verify_group_gone') is not True:
                break
            time.sleep(.05)
        if not group_gone:
            failures.append({'operation': 'verify_group_gone', 'type': 'UnverifiedProcessGroup'})
    if selector is not None:
        try:
            selector.close()
        except BaseException as error:
            record('close_selector', error)
    if process is not None and process.stdout is not None:
        try:
            process.stdout.close()
        except BaseException as error:
            record('close_stdout', error)
    return failures


def read_diagnostic_json(path, maximum=1024 * 1024):
    # Bound the opened descriptor, not a racy path stat followed by unbounded read_text.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError('diagnostic_file_type_or_size')
        data = bytearray()
        while True:
            block = os.read(fd, min(65536, maximum + 1 - len(data)))
            if not block:
                break
            data.extend(block)
            if len(data) > maximum:
                raise ValueError('diagnostic_read_bound')
    finally:
        os.close(fd)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_diagnostic_key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('nonfinite_diagnostic_json')
    # Native JSON is UTF-8. Do not let json.loads(bytes) auto-detect another encoding
    # whose structural characters disagree with the byte depth scanner.
    text = data.decode('utf-8')
    # Do not depend on the Python version's recursion threshold for hostile JSON.
    depth = 0
    quoted = escaped = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 64:
                raise ValueError('diagnostic_json_depth')
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                raise ValueError('diagnostic_json_structure')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def native_summary(path, reader=None):
    """Project only fixed status/stage from a bounded regular JSON result, not its other fields."""
    try:
        data = (reader or read_diagnostic_json)(path, maximum=1024 * 1024)
        if type(data) is not dict or data.get('native_runtime_test') is not False:
            return {'availability': 'invalid'}
        status = data.get('status')
        if status not in {'FAILED', 'PASS_UNSIGNED_NATIVE_BUILD_ONLY'}:
            return {'availability': 'invalid'}
        row = {'availability': 'present', 'status': status}
        if status == 'FAILED':
            stage = data.get('failed_stage')
            if stage not in NATIVE_STAGES:
                return {'availability': 'invalid'}
            row['failed_stage'] = stage
        return row
    except Exception:
        # Malformed/deep JSON and reader errors must never replace the primary failure.
        return {'availability': 'unavailable'}
