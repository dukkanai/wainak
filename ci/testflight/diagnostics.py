"""Public, finite TestFlight diagnostics. No child output or environment values."""
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

from ci.testflight import policy as p
from ci.ios.diagnostics import project_cleanup_errors

COMMAND_STAGES = {
    'source_preparation': 'preflight',
    'source_commit': 'preflight',
    'source_clean': 'preflight',
    'flutter_version': 'preflight',
    'xcode_version': 'preflight',
    'pub_get': 'flutter_host_checks',
    'analyze': 'flutter_host_checks',
    'entry_test': 'flutter_host_checks',
    'lock_diff': 'flutter_host_checks',
    'use_profiles': 'profiles_and_export_policy',
    'ios_config': 'profiles_and_export_policy',
    'build_settings': 'profiles_and_export_policy',
    'build_ipa': 'signed_internal_export',
    'verify_signature': 'verify_signed_payload',
    'read_entitlements': 'verify_signed_payload',
    'read_profile': 'verify_signed_payload',
    'architecture': 'verify_signed_payload',
}
FAILURE_KINDS = frozenset({'NONE', 'NONZERO_EXIT', 'TIMEOUT', 'CANCELLED',
                         'OUTPUT_BOUND', 'RESOURCE_GUARD', 'SPAWN_OR_IO', 'CLEANUP', 'OTHER'})
ERROR_TYPES = frozenset({'RuntimeError', 'TimeoutError', 'TimeoutExpired', 'InterruptedError',
                        'KeyboardInterrupt', 'SystemExit', 'OSError', 'FileNotFoundError',
                        'PermissionError', 'ValueError', 'TypeError', 'PolicyError',
                        'CalledProcessError'})


def error_type(error):
    name = type(error).__name__
    return name if name in ERROR_TYPES else 'Exception'


def failure_kind(error):
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        return 'TIMEOUT'
    if isinstance(error, (InterruptedError, KeyboardInterrupt, SystemExit)):
        return 'CANCELLED'
    if isinstance(error, OSError):
        return 'SPAWN_OR_IO'
    if isinstance(error, subprocess.CalledProcessError):
        return 'NONZERO_EXIT'
    return 'OTHER'


def integer(value, minimum, maximum):
    return value if type(value) is int and minimum <= value <= maximum else None


def emit_command(label, outcome, started, detail):
    # Only fixed identities and bounded primitives cross the log boundary.
    if label not in COMMAND_STAGES or outcome not in {'START', 'PASS', 'FAILED'}:
        raise ValueError('Unknown diagnostic identity')
    elapsed = time.monotonic() - started
    if not math.isfinite(elapsed) or not 0 <= elapsed <= 86400:
        elapsed = 86400.0
    kind = detail.get('failure_kind')
    if type(kind) is not str or kind not in FAILURE_KINDS:
        kind = 'OTHER'
    print(json.dumps({
        'event': 'TESTFLIGHT_COMMAND', 'command': label,
        'stage': COMMAND_STAGES[label], 'outcome': outcome,
        'elapsed_seconds': round(elapsed, 3),
        'exit_code': integer(detail.get('exit_code'), -255, 255),
        'failure_kind': kind,
        'output_bytes': integer(detail.get('output_bytes'), 0, 16 * 1024 * 1024),
        'cleanup_failed': detail.get('cleanup_failed') is True,
        **project_cleanup_errors(detail.get('cleanup_errors', [])),
        'cleanup_errors_truncated': detail.get('cleanup_errors_truncated') is True or
            (type(detail.get('cleanup_errors')) is list and len(detail['cleanup_errors']) > 16),
    }), flush=True)


def run_command(label, command, *, cwd, env, root, deadline, runner, seconds=300):
    started = time.monotonic()
    detail = {'failure_kind': 'NONE'}
    emit_command(label, 'START', started, detail)
    try:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0 or shutil.disk_usage(root).free < 4*1024**3:
            detail['failure_kind'] = 'RESOURCE_GUARD'
            p.require(False, 'time_or_disk_limit')
        result = runner(command, cwd=cwd, env=env, seconds=min(seconds, remaining),
                        check=True, diagnostic=detail)
    except BaseException as error:
        if detail.get('failure_kind') in (None, 'NONE'):
            detail['failure_kind'] = failure_kind(error)
        emit_command(label, 'FAILED', started, detail)
        raise
    emit_command(label, 'PASS', started, detail)
    return result.stdout


def numeric_version(value):
    return value if type(value) is str and re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}', value) else 'UNKNOWN'


def emit_host(root, work, flutter_version, dart_version):
    # Probe an owned disposable directory after source checks. No paths, host
    # names, environment contents, provisioning data or tool output are logged.
    case_sensitive = None
    try:
        with tempfile.TemporaryDirectory(prefix='host-probe-', dir=work) as directory:
            probe = Path(directory)/'CaseProbe'
            probe.write_bytes(b'')
            case_sensitive = not (Path(directory)/'caseprobe').exists()
    except OSError:
        pass
    try:
        macos = numeric_version(platform.mac_ver()[0]) if sys.platform == 'darwin' else 'NOT_MACOS'
    except Exception:
        macos = 'UNKNOWN'
    print(json.dumps({
        'event': 'TESTFLIGHT_HOST',
        'os': sys.platform if sys.platform in {'darwin', 'linux'} else 'OTHER',
        'architecture': platform.machine() if platform.machine() in {'arm64', 'aarch64', 'x86_64'} else 'OTHER',
        'python': '.'.join(str(n) for n in sys.version_info[:3]),
        'macos': macos,
        'case_sensitive_volume': case_sensitive,
        'checkout_resolves_to_root': Path(os.environ.get('CM_BUILD_DIR', '/nonexistent')).resolve() == root,
        'pub_cache_explicit': 'PUB_CACHE' in os.environ,
        # These versions are emitted only after the driver's exact pin checks.
        'flutter': numeric_version(flutter_version),
        'dart': numeric_version(dart_version),
        'xcode': '26.4.1', 'xcode_build': '17E202',
        'flutter_pin_verified': True, 'xcode_pin_verified': True,
    }), flush=True)
