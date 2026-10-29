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
    print('WAINEK_CI_DIAGNOSTIC ' + json.dumps({'event': event, **fields}, sort_keys=True), flush=True)


CLEANUP_OPERATIONS = frozenset({'poll_direct_child', 'signal_term', 'signal_kill',
    'probe_after_term', 'probe_after_kill', 'reap_direct_child', 'verify_group_gone',
    'close_selector', 'close_stdout', 'close_stderr', 'cleanup_process', 'grace_cleanup', 'observer_cleanup'})
CLEANUP_TYPES = frozenset(ERROR_TYPES) | {'UnverifiedProcessGroup', 'Exception', 'RuntimeError'}


def project_cleanup_errors(errors):
    """Bounded public projection, including hostile or malformed caller data."""
    if type(errors) is not list:
        errors = [{'operation': 'cleanup_process', 'type': 'Exception'}]
    rows = []
    for error in errors[:16]:
        error = error if type(error) is dict else {}
        operation, kind = error.get('operation'), error.get('type')
        row = {'operation': operation if type(operation) is str and operation in CLEANUP_OPERATIONS else 'other',
               'type': kind if type(kind) is str and kind in CLEANUP_TYPES else 'Exception'}
        number = error.get('errno')
        if type(number) is int and number in errno.errorcode:
            row['errno'] = number
        rows.append(row)
    return {'cleanup_errors': rows, 'cleanup_errors_truncated': len(errors) > 16}


def cleanup_process(process, selector):
    """Best-effort owned-group cleanup; uncertainty is returned as failure, never waived.

    Exceptions are collected independently so a denied signal cannot suppress reaping,
    FD closing or the original command exception. No privilege escalation or new target.
    """
    failures = []
    group_gone = process is None

    def record(operation, error):
        failures.append({'operation': operation, **safe_error(error)})

    def reap_ready_child():
        # Reap a terminated direct child without waiting. On Darwin, a group
        # containing only unreaped zombies can report EPERM; on Linux it can
        # remain discoverable indefinitely until waitpid/poll collects it.
        # Reaping the leader is never evidence that its descendants are gone.
        try:
            process.poll()
        except BaseException as error:
            record('poll_direct_child', error)

    def probe(operation):
        nonlocal group_gone
        reap_ready_child()
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
            reap_ready_child()
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
    if process is not None and getattr(process,'stderr',None) is not None:
        try:
            process.stderr.close()
        except BaseException as error:
            record('close_stderr', error)
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
# Finite identities emitted by the reviewed native recipe; never argv or paths.
NATIVE_COMMANDS = frozenset(['apple-bind', 'binding-input-controls', 'binding-input-modules', 'go-version', 'gobind-build', 'gobind-buildinfo', 'gomobile-build', 'gomobile-buildinfo', 'iphoneos-clang', 'iphoneos-sdk', 'iphoneos-sysroot', 'iphonesimulator-clang', 'iphonesimulator-sdk', 'iphonesimulator-sysroot', 'module-acquisition', 'module-verify', 'module-verify-after', 'slice-architecture', 'slice-load-commands', 'slice-symbols', 'target-0-controls', 'target-0-modules', 'target-1-controls', 'target-1-modules', 'target-device-packages', 'target-simulator-packages', 'tool-input-controls', 'tool-input-modules', 'xcode-version'])
GRAPH_REASONS = frozenset(['TARGET_MAIN', 'CONTROLS', 'DUPLICATE_REPLACEMENT', 'INPUT_SELECTION', 'LOCAL_REPLACEMENT', 'MODULE_UNRESOLVED', 'OWNED_MAIN_CONTEXT', 'OWNED_MAIN_PATH', 'OWNED_MAIN_SELECTED', 'PACKAGES_EMPTY', 'PACKAGES_UNRESOLVED', 'PACKAGE_LOCAL', 'PACKAGE_MODULE', 'PUBLIC_MODULE', 'REPLACEMENT', 'REPLACEMENT_VERSION', 'TARGET_EVIDENCE'])

TOOL_CATEGORIES = frozenset(['COMPILER', 'GOMOBILE_BIND', 'GO_MODULE_OFFLINE', 'GO_MODULE_SUM', 'GO_MODULE_UPDATE', 'GO_VERSION', 'GRAPH_MISMATCH', 'SDK_TOOL', 'UNKNOWN_TOOL_FAILURE'])

FAILURE_KINDS = frozenset({'NONE', 'NONZERO_EXIT', 'TIMEOUT', 'CANCELLED', 'OUTPUT_BOUND',
                          'RESOURCE_GUARD', 'SPAWN_OR_IO', 'CLEANUP', 'OTHER'})
FAILURE_CATEGORIES = frozenset({'MALFORMED_TEST_JSON', 'INCOMPLETE_TEST_JSON', 'TEST_FAILURE',
                               'NO_TEST_FAILURE_EVENT', 'COMPILE_PHASE_FAILURE', 'MISSING_TEST_EXECUTION', 'SKIPPED_TEST'})
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
    if type(name) is not str or name not in (HOST_COMMANDS.keys() | NATIVE_COMMANDS):
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
    if type(tests) is not list or len(tests) > 32 or type(categories) is not list or len(categories) > len(FAILURE_CATEGORIES):
        raise ValueError('command_summary_lists')
    allowed = trusted_tests.get(HOST_COMMANDS.get(name), frozenset())
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
    tool = data.get('tool_categories', [])
    if type(tool) is not list or len(tool) > len(TOOL_CATEGORIES) or any(type(x) is not str or x not in TOOL_CATEGORIES for x in tool) or len(set(tool)) != len(tool):
        raise ValueError('command_summary_tool_categories')
    if tool and (outcome != 'FAILED' or name in HOST_COMMANDS):
        raise ValueError('command_summary_tool_scope')
    if name in NATIVE_COMMANDS and (tests or categories):
        raise ValueError('command_summary_nonhost_tests')
    row = {'name': name, 'exit_code': code, 'elapsed_seconds': elapsed, 'outcome': outcome,
            'failure_kind': kind, 'failed_tests': list(tests), 'failure_categories': list(categories)}
    if 'test_counts' in data:
        counts=data['test_counts']
        if type(counts) is not dict or set(counts)!={'expected','run','passed','skipped'} or any(type(x) is not int or not 0<=x<=128 for x in counts.values()):
            raise ValueError('command_summary_test_counts')
        if name not in HOST_COMMANDS or counts['expected']==0 or counts['run']>counts['expected'] or counts['passed']>counts['run']:
            raise ValueError('command_summary_test_counts_scope')
        if outcome=='PASS' and (counts['run']!=counts['expected'] or counts['passed']!=counts['expected'] or counts['skipped']):
            raise ValueError('command_summary_test_counts_false_pass')
        row['test_counts']=dict(counts)
    if 'primary' in data:
        primary=data['primary']
        operations={'preflight','resource_guard','spawn','register_output','collect_output','wait_child','post_guard'}
        kinds=ERROR_TYPES|{'BuildFailure','InvalidRecipe','Exception'}
        if type(primary) is not dict or set(primary)-{'operation','type','errno'} or primary.get('operation') not in operations or primary.get('type') not in kinds:
            raise ValueError('command_summary_primary')
        if 'errno' in primary and (type(primary['errno']) is not int or primary['errno'] not in errno.errorcode):
            raise ValueError('command_summary_primary_errno')
        if outcome!='FAILED':raise ValueError('command_summary_primary_scope')
        row['primary']=dict(primary)
    if 'tool_categories' in data: row['tool_categories'] = list(tool)
    return row


ARTIFACT_ABI_NAMES = frozenset(['Cancel', 'Close', 'Epoch', 'ExportHistory', 'HistorySnapshot', 'ImportHistory', 'NewSyntheticSession'])
ARTIFACT_CHECKS = frozenset(['architecture', 'binary_hash', 'container', 'framework_plist', 'header', 'load_commands', 'metadata', 'modulemap', 'path', 'slice_metadata', 'symbols', 'variants'])
ARTIFACT_REASONS = frozenset(['ARCHITECTURE', 'CONTAINER', 'DECODE', 'DUPLICATE_VARIANT', 'FRAMEWORK_PLIST', 'HEADER', 'IO', 'LOAD_MINIMUM', 'LOAD_PLATFORM', 'LOAD_RECORD', 'METADATA', 'MODULEMAP', 'NONE', 'PATH', 'PLATFORM_ABI', 'SHAPE', 'SYMBOLS', 'UNKNOWN', 'VARIANT', 'VARIANTS'])

def artifact_summary(data):
    """Copy only fixed bounded values; raw paths, symbol text and tool output ignored."""
    if type(data) is not dict:raise ValueError('artifact_type')
    checks,symbols,loads=data.get('checks'),data.get('symbols'),data.get('loads')
    if type(checks) is not list or len(checks)>24 or type(symbols) is not list or len(symbols)>2 or type(loads) is not list or len(loads)>2:
        raise ValueError('artifact_bounds')
    result={'checks':[],'symbols':[],'loads':[]}
    for row in checks:
        if type(row) is not dict:raise ValueError('artifact_check_type')
        label,variant,outcome,reason=(row.get(k) for k in ('check','variant','outcome','reason'))
        if type(label) is not str or label not in ARTIFACT_CHECKS or type(variant) is not str or variant not in {'device','simulator','unknown'} or type(outcome) is not str or outcome not in {'PASS','FAILED'} or type(reason) is not str or reason not in ARTIFACT_REASONS:
            raise ValueError('artifact_check_fields')
        if (outcome=='PASS')!=(reason=='NONE'):raise ValueError('artifact_false_pass')
        result['checks'].append({'check':label,'variant':variant,'outcome':outcome,'reason':reason})
    def bounded_counts(value,keys):
        if type(value) is not dict or set(value)!=set(keys) or any(type(x) is not int or not 0<=x<=100000 for x in value.values()):raise ValueError('artifact_counts')
        return {key:value[key] for key in keys}
    for group,rows in (('symbols',symbols),('loads',loads)):
        seen=set()
        for row in rows:
            if type(row) is not dict:raise ValueError('artifact_detail_type')
            variant,complete=row.get('variant'),row.get('complete')
            if type(variant) is not str or variant not in {'device','simulator'} or variant in seen or type(complete) is not bool:raise ValueError('artifact_detail_fields')
            seen.add(variant);clean={'variant':variant,'complete':complete}
            if group=='symbols':
                keys=('defined','undefined','nontext','missing','hex_text','addressless_text','unrecognized')
                if not complete and not any(key in row for key in keys):result[group].append(clean);continue
                for key in keys:
                    value=row.get(key)
                    if type(value) is not list or len(value)>7 or any(type(x) is not str or x not in ARTIFACT_ABI_NAMES for x in value) or len(set(value))!=len(value):raise ValueError('artifact_symbol_names')
                    clean[key]=list(value)
                if not set(clean['hex_text']+clean['addressless_text'])<=set(clean['defined']):raise ValueError('artifact_symbol_sets')
                if set(clean['missing']) & set(clean['defined']+clean['undefined']+clean['nontext']+clean['unrecognized']):raise ValueError('artifact_symbol_missing')
                clean['format_counts']=bounded_counts(row.get('format_counts'),('bsd','posix','darwin','other'))
            else:
                if not complete and 'counts' not in row:result[group].append(clean);continue
                clean['counts']=bounded_counts(row.get('counts'),('build_records','legacy_records','platform_device','platform_simulator','platform_other','minimum_match','minimum_other'))
            result[group].append(clean)
    return result


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
            category = data.get('gate_category')
            if category is not None:
                row['gate_category'] = category if type(category) is str and category in TOOL_CATEGORIES else 'UNKNOWN_TOOL_FAILURE'
            reason = data.get('graph_reason')
            if row.get('gate_category') == 'GRAPH_MISMATCH' and type(reason) is str and reason in GRAPH_REASONS:
                row['graph_reason'] = reason
        if 'artifact_inspection' in data:
            try:row['artifact_inspection']=artifact_summary(data['artifact_inspection'])
            except Exception:row['artifact_inspection']={'availability':'invalid'}
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
