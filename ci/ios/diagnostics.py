"""Bounded, value-free diagnostics. Never serialize exception text, argv or logs."""
import errno
import hashlib
import math
from pathlib import Path
import re
from types import MappingProxyType
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


def read_regular_bytes(path, maximum):
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
    return bytes(data)


def read_diagnostic_json(path, maximum=1024 * 1024):
    data = read_regular_bytes(path, maximum)
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


# Public, fixed command identities; no arbitrary command path or arguments.
HOST_COMMANDS = {
    'age-cli-build': None,
    'archive-test-compile': 'archive', 'archive-tests': 'archive', 'archive-vet': 'archive',
    'fuzz-FuzzStrictHistoryJSON': 'archive', 'fuzz-FuzzArchiveOpen': 'archive',
    'archivebridge-test-compile': 'archivebridge', 'archivebridge-tests': 'archivebridge',
    'archivebridge-vet': 'archivebridge',
}
FAILURE_KINDS = frozenset({'NONE', 'NONZERO_EXIT', 'TIMEOUT', 'CANCELLED', 'OUTPUT_BOUND',
                          'RESOURCE_GUARD', 'SPAWN_OR_IO', 'CLEANUP', 'OTHER'})
FAILURE_CATEGORIES = frozenset({'MALFORMED_TEST_JSON', 'INCOMPLETE_TEST_JSON', 'TEST_FAILURE',
                               'NO_TEST_FAILURE_EVENT', 'COMPILE_PHASE_FAILURE'})
TEST_SOURCES = {
    'archive': ('archive/archive_test.go', 'archive/interop_test.go'),
    'archivebridge': ('archivebridge/bridge_test.go',),
}


def snapshot_test_names(root, source_hashes):
    """Capture immutable public source names BEFORE the native child can run.

    Exact tracked-byte checks bind this diagnostic allowlist to the source inventory.
    Only top-level declarations are admitted; runtime subtest strings are never trusted.
    """
    result = {}
    for package, names in TEST_SOURCES.items():
        allowed = set()
        for name in names:
            data = read_regular_bytes(Path(root) / name, 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != source_hashes.get(name):
                raise ValueError('test_source_inventory_mismatch')
            text = data.decode('utf-8')
            allowed.update(re.findall(r'^func ((?:Test|Fuzz)[A-Za-z0-9_]{1,120})\(', text, re.M))
        if not allowed or len(allowed) > 128:
            raise ValueError('test_name_inventory_bound')
        result[package] = frozenset(allowed)
    return MappingProxyType(result)


def command_summary(data, trusted_tests):
    """Reject malformed fields and copy only the fixed, bounded diagnostic schema."""
    if type(data) is not dict:
        raise ValueError('command_summary_type')
    name, outcome, kind = data.get('name'), data.get('outcome'), data.get('failure_kind')
    if type(name) is not str or name not in HOST_COMMANDS:
        raise ValueError('command_summary_name')
    if type(outcome) is not str or outcome not in {'PASS', 'FAILED'}:
        raise ValueError('command_summary_outcome')
    if type(kind) is not str or kind not in FAILURE_KINDS:
        raise ValueError('command_summary_kind')
    code, elapsed = data.get('exit_code'), data.get('elapsed_seconds')
    if code is not None and (type(code) is not int or not -255 <= code <= 255):
        raise ValueError('command_summary_code')
    if type(elapsed) not in {int, float} or not math.isfinite(elapsed) or not 0 <= elapsed <= 3600:
        raise ValueError('command_summary_elapsed')
    tests, categories = data.get('failed_tests'), data.get('failure_categories')
    if type(tests) is not list or len(tests) > 32 or type(categories) is not list or len(categories) > 5:
        raise ValueError('command_summary_lists')
    allowed = trusted_tests.get(HOST_COMMANDS[name], frozenset())
    if any(type(x) is not str or x not in allowed or '/' in x for x in tests):
        raise ValueError('command_summary_test_name')
    if any(type(x) is not str or x not in FAILURE_CATEGORIES for x in categories):
        raise ValueError('command_summary_category')
    if len(set(tests)) != len(tests) or len(set(categories)) != len(categories):
        raise ValueError('command_summary_duplicates')
    if outcome == 'PASS' and (code != 0 or kind != 'NONE' or tests or categories):
        raise ValueError('command_summary_false_pass')
    if outcome == 'FAILED' and kind == 'NONE':
        raise ValueError('command_summary_missing_failure')
    return {'name': name, 'exit_code': code, 'elapsed_seconds': elapsed, 'outcome': outcome,
            'failure_kind': kind, 'failed_tests': list(tests), 'failure_categories': list(categories)}


def native_summary(path, reader=None, trusted_tests=None):
    """Project fixed status/stage and a bounded source-bound last host-command receipt."""
    try:
        data = (reader or read_diagnostic_json)(path, maximum=1024 * 1024)
        if type(data) is not dict or data.get('native_runtime_test') is not False:
            return {'availability': 'invalid'}
        status = data.get('status')
        if type(status) is not str or status not in {'FAILED', 'PASS_UNSIGNED_NATIVE_BUILD_ONLY'}:
            return {'availability': 'invalid'}
        row = {'availability': 'present', 'status': status}
        if status == 'FAILED':
            stage = data.get('failed_stage')
            if type(stage) is not str or stage not in NATIVE_STAGES:
                return {'availability': 'invalid'}
            row['failed_stage'] = stage
        if 'last_command' in data:
            try:
                row['last_command'] = command_summary(data['last_command'], trusted_tests or {})
            except Exception:
                # Invalid optional detail must not erase the already validated failure stage.
                row['last_command'] = {'availability': 'invalid'}
        return row
    except Exception:
        # Malformed/deep JSON and reader errors must never replace the primary failure.
        return {'availability': 'unavailable'}
