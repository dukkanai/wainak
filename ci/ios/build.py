#!/usr/bin/env python3
"""Manual unsigned iOS compile recipe. Writing this file does not run a build.

--check performs source checks only. --build-unsigned is for an explicitly
started, disposable Codemagic macOS job; no signing, device or simulator launch.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import selectors
import shutil
import signal
import subprocess
import sys
import time
from verify import GateError, require, read_json, digest, inventory, framework_slices, xcconfig, unsigned_settings, UNCACHED_SETTINGS, uncached_settings
from diagnostics import LABELS, cleanup_process, emit, native_summary, safe_error, snapshot_test_names
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_guards import tree_size, wait_until
from resources import budget_snapshot, identity, retire_native_tools, retirement_error, large_file_summary

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'apps/mobile'
PINS = ROOT / 'ci/ios-host-pins.json'
MAX_BYTES = 8 * 1024 ** 3
SIGNING = ['CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO', 'CODE_SIGN_IDENTITY=',
           'DEVELOPMENT_TEAM=', 'PROVISIONING_PROFILE=', 'PROVISIONING_PROFILE_SPECIFIER=',
           'CODE_SIGN_STYLE=Manual']
DEFINES = ['--dart-define=WAINAK_DEV_MODE=true', '--dart-define=WAINAK_REPOSITORY=native_archive',
           '--dart-define=WAINAK_IOS_ARCHIVE_PREVIEW=true']
TESTS = ['test/native_archive_test.dart', 'test/native_archive_widget_test.dart',
         'test/native_archive_entry_test.dart', 'test/native_archive_platform_test.dart',
         'test/native_archive_capacity_test.dart']


def size(root):
    return tree_size(root)


def git_snapshot(root=ROOT, paths=()):
    raw = subprocess.check_output(['git', 'ls-files', '-z', '--', *paths], cwd=root, timeout=15)
    result = {}
    for name in raw.decode('utf-8').split('\0'):
        if name:
            p = root / name
            require(p.is_file() and not p.is_symlink(), 'tracked_source_type')
            result[name] = digest(p)
    require(result, 'empty_source_inventory')
    return result



def xcode_commands(base, sdk):
    """Use one explicit cache policy for settings and the matching compile action."""
    require(sdk in ('iphoneos', 'iphonesimulator'), 'cache_policy_sdk')
    require(not any(str(arg).split('=', 1)[0] in UNCACHED_SETTINGS for arg in base),
            'cache_policy_duplicate_override')
    action = 'build' if sdk == 'iphoneos' else 'build-for-testing'
    shared = [*base, *(key + '=NO' for key in UNCACHED_SETTINGS)]
    return [*shared, action, '-showBuildSettings', '-json'], [*shared, action]


def cache_policy_receipt(settings, sdk):
    try:
        return uncached_settings(settings, sdk)
    except GateError as error:
        allowed = {'cache_policy_sdk', 'cache_policy_settings', 'compile_cache_enabled_or_unknown',
                   'cache_policy_targets', 'cache_policy_test_target_missing'}
        reason = str(error) if str(error) in allowed else 'invalid_settings'
        try:
            public_sdk = sdk if sdk in ('iphoneos', 'iphonesimulator') else 'unknown'
            emit('compile_cache_policy', sdk=public_sdk, status='FAILED', reason=reason)
        except BaseException:
            pass
        raise


class Runner:
    def __init__(self, work, flutter):
        self.work, self.flutter = work, flutter
        self.work_identity = identity(work.stat())
        self.resource_snapshot = None
        self.sources = git_snapshot()
        self.trusted_tests = snapshot_test_names(ROOT, self.sources)
        self.flutter_start = size(flutter)
        self.flutter_sources = git_snapshot(flutter, ('packages/flutter_tools', 'bin/internal', 'bin/flutter', 'bin/dart'))
        self.cancelled = False
        self.sequence = 0
        self.results = []
        self.env = {
            'PATH': f'{flutter}/bin:/usr/bin:/bin:/usr/sbin:/sbin',
            'HOME': str(work / 'home'), 'TMPDIR': str(work / 'tmp'),
            'PUB_CACHE': str(work / 'pub-cache'), 'CI': 'true',
            'FLUTTER_SUPPRESS_ANALYTICS': 'true', 'DART_SUPPRESS_ANALYTICS': 'true',
            'PUB_HOSTED_URL': 'https://pub.dev',
            'FLUTTER_STORAGE_BASE_URL': 'https://storage.googleapis.com',
            'GOTOOLCHAIN': 'local', 'GOTELEMETRY': 'off', 'GOENV': 'off',
            'LANG': 'en_US.UTF-8', 'LC_ALL': 'en_US.UTF-8',
        }
        # Selected Xcode only; do not inherit secrets/proxy/signing configuration.
        if os.environ.get('DEVELOPER_DIR'):
            self.env['DEVELOPER_DIR'] = os.environ['DEVELOPER_DIR']
        for name in ('home', 'tmp', 'pub-cache', 'logs'):
            (work / name).mkdir(mode=0o700)
        signal.signal(signal.SIGTERM, self.cancel)
        signal.signal(signal.SIGINT, self.cancel)

    def cancel(self, *_):
        self.cancelled = True

    def guard(self):
        require(not self.cancelled, 'cancelled')
        self.resource_snapshot = None  # Never mislabel an old sample after an I/O failure.
        self.resource_snapshot = budget_snapshot(self.work, APP, self.flutter, self.flutter_start, measure=size)
        if self.resource_snapshot['total_logical_bytes'] > MAX_BYTES:
            try:
                detail = large_file_summary(self.work)
            except BaseException as error:
                detail = {'availability': 'unavailable', 'complete': False, 'error': safe_error(error)}
            self.resource_snapshot['work_largest_files'] = detail
        require(self.resource_snapshot['total_logical_bytes'] <= MAX_BYTES, 'workspace_budget')
        require(self.resource_snapshot['free_disk_bytes'] >= 4 * 1024 ** 3, 'disk_headroom')

    def run(self, label, args, cwd=ROOT, timeout=1200, maximum=16 * 1024 * 1024):
        require(label in LABELS, 'unknown_command_label')
        self.sequence += 1
        output = bytearray()
        p = sel = primary = None
        operation = 'preflight'
        start = time.monotonic()
        path = self.work / 'logs' / f'{self.sequence:02d}-{label}'
        try:
            emit('command_start', stage=label, sequence=self.sequence)
            self.guard()
            require(git_snapshot() == self.sources, 'source_changed_before_command')
            require(git_snapshot(self.flutter, ('packages/flutter_tools', 'bin/internal', 'bin/flutter', 'bin/dart')) == self.flutter_sources, 'flutter_source_drift')
            operation = 'write_command_metadata'
            command = {'label': label, 'argv': [str(x) for x in args], 'cwd': str(cwd), 'timeout_seconds': timeout}
            path.with_suffix('.command.json').write_text(json.dumps(command, indent=2) + '\n')
            operation = 'spawn_command'
            p = subprocess.Popen(args, cwd=cwd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
            operation = 'register_output'
            sel = selectors.DefaultSelector()
            sel.register(p.stdout, selectors.EVENT_READ)
            last_guard = time.monotonic()
            operation = 'collect_output'
            while sel.get_map():
                require(time.monotonic() - start <= timeout and not self.cancelled, 'command_timeout_or_cancel')
                if time.monotonic() - last_guard > 2:
                    operation = 'resource_guard'
                    self.guard(); last_guard = time.monotonic()
                operation = 'collect_output'
                for key, _ in sel.select(.2):
                    block = os.read(key.fd, 65536)
                    if not block:
                        sel.unregister(key.fileobj)
                    else:
                        require(len(output) + len(block) <= maximum, 'command_output_bound')
                        output.extend(block)
            operation = 'wait_command'
            def waiting_guard():
                nonlocal last_guard
                require(not self.cancelled, 'command_timeout_or_cancel')
                if time.monotonic() - last_guard > 2:
                    self.guard(); last_guard = time.monotonic()
            require(wait_until(p, start + timeout, waiting_guard,
                               lambda: GateError('command_timeout_or_cancel')) == 0, 'command_failed_' + label)
            operation = 'post_command_guards'
            self.guard()
            require(git_snapshot() == self.sources, 'source_changed_by_command')
            require(git_snapshot(self.flutter, ('packages/flutter_tools', 'bin/internal', 'bin/flutter', 'bin/dart')) == self.flutter_sources, 'flutter_source_drift')
            return bytes(output)
        except BaseException as error:
            primary = error
            raise
        finally:
            # Cleanup errors must not replace a primary timeout/command/permission error.
            failures = cleanup_process(p, sel)
            log_hash = None
            try:
                path.with_suffix('.log').write_bytes(output)
                log_hash = digest(path.with_suffix('.log'))
            except BaseException as error:
                failures.append({'operation': 'write_private_log', **safe_error(error)})
            row = {'label': label, 'status': 'FAILED' if primary or failures else 'PASS',
                   'exit_code': None if p is None else p.returncode, 'log_sha256': log_hash,
                   'primary': None if primary is None else {'operation': operation, **safe_error(primary)},
                   'cleanup_errors': failures,
                   'resource_snapshot': getattr(self, 'resource_snapshot', None)}
            self.results.append(row)
            try:
                (self.work / 'commands.json').write_text(json.dumps(self.results, indent=2) + '\n')
            except BaseException as error:
                failures.append({'operation': 'write_commands_manifest', **safe_error(error)})
                row['status'] = 'FAILED'
            public = {'stage': label, 'sequence': self.sequence, 'status': row['status'],
                      'elapsed_seconds': round(time.monotonic() - start, 3),
                      'primary': row['primary'], 'cleanup_errors': failures,
                      'resource_snapshot': row['resource_snapshot']}
            if label == 'native':
                public['native_result'] = native_summary(self.work / 'native/result.json', trusted_tests=getattr(self, 'trusted_tests', {}))
            try:
                emit('command_end', **public)
            except BaseException as error:
                failures.append({'operation': 'emit_diagnostic', **safe_error(error)})
                row['status'] = 'FAILED'
                try:
                    (self.work / 'commands.json').write_text(json.dumps(self.results, indent=2) + '\n')
                except BaseException as manifest_error:
                    failures.append({'operation': 'write_failed_diagnostic_manifest', **safe_error(manifest_error)})
            if failures and primary is None:
                raise GateError('command_cleanup_failed')


def cleanup_owned_files(cfg_owned, cfg, cfg_hash, sources):
    failures = []
    if cfg_owned:
        try:
            require(cfg.is_file() and not cfg.is_symlink() and digest(cfg) == cfg_hash, 'generated_config_drift')
            cfg.unlink()
        except BaseException as error:
            failures.append({'operation': 'remove_owned_generated_config', **safe_error(error)})
    try:
        require(git_snapshot() == sources, 'source_drift_at_exit')
    except BaseException as error:
        failures.append({'operation': 'final_source_guard', **safe_error(error)})
    return failures


def static_check():
    pins = read_json(PINS)
    require(pins['host'] == 'darwin-arm64' and pins['ios_minimum'] == '15.0', 'host_pins')
    require(pins['xcode_version'] == '26.4.1' and pins['xcode_build'] == '17E202', 'xcode_pin')
    for name in TESTS:
        require((APP / name).is_file(), 'missing_targeted_test')
    pbx = (APP / 'ios/Runner.xcodeproj/project.pbxproj').read_text()
    require('ArchiveNativeBridge.m in Sources' in pbx and 'GoArchiveEngine.swift in Sources' in pbx, 'missing_native_sources')
    require('Archivebridge.xcframework in Embed' not in pbx, 'embedded_static_framework')
    require(not (APP / 'ios/Flutter/NativeArchive.generated.xcconfig').exists(), 'unverified_native_config')
    return pins


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--build-unsigned', action='store_true')
    args = parser.parse_args()
    pins = static_check()
    if args.check:
        print('PASS iOS recipe static checks; Mac/Xcode execution NOT RUN')
        return
    require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'requires_darwin_arm64')
    require(os.environ.get('CM_BUILD_DIR') and Path(os.environ['CM_BUILD_DIR']).resolve() == ROOT, 'requires_explicit_codemagic_checkout')
    flutter_exe = shutil.which('flutter')
    require(flutter_exe is not None, 'flutter_missing')
    flutter = Path(flutter_exe).resolve().parent.parent
    work = ROOT / '.ci-work'
    work.mkdir(mode=0o700)  # Never reuse a prior partial execution or accept injected artifacts.
    runner = Runner(work, flutter)
    cfg = APP / 'ios/Flutter/NativeArchive.generated.xcconfig'
    cfg_owned = False
    cfg_hash = None
    try:
        if 'DEVELOPER_DIR' not in runner.env:
            selected = runner.run('xcode-selection', ['/usr/bin/xcode-select', '-p'], timeout=30).decode().strip()
            require(selected.startswith('/Applications/') and Path(selected).is_dir(), 'full_xcode_selection')
            runner.env['DEVELOPER_DIR'] = str(Path(selected).resolve(strict=True))
        runner.env['DEVELOPER_DIR'] = str(Path(runner.env['DEVELOPER_DIR']).resolve(strict=True))
        require(runner.env['DEVELOPER_DIR'].startswith('/Applications/') and Path(runner.env['DEVELOPER_DIR']).is_dir(), 'xcode_environment')
        xcode = runner.run('xcode-version', ['/usr/bin/xcodebuild', '-version'], timeout=30).decode().strip()
        require(xcode == f"Xcode {pins['xcode_version']}\nBuild version {pins['xcode_build']}", 'xcode_mismatch')
        flutter_head = runner.run('flutter-head', ['/usr/bin/git', 'rev-parse', 'HEAD'], cwd=flutter, timeout=30).decode().strip()
        require(flutter_head == pins['flutter']['framework_revision'], 'flutter_source_revision')
        runner.run('flutter-source-clean', ['/usr/bin/git', 'diff', '--exit-code', flutter_head, '--', 'packages/flutter_tools', 'bin/internal', 'bin/flutter', 'bin/dart'], cwd=flutter, timeout=30)
        version = json.loads(runner.run('flutter-version', [flutter / 'bin/flutter', '--version', '--machine'], timeout=120))
        fp = pins['flutter']
        require(version.get('frameworkVersion') == fp['version'] and version.get('frameworkRevision') == fp['framework_revision'] and version.get('engineRevision') == fp['engine_revision'] and version.get('dartSdkVersion', '').split(' ')[0] == fp['dart_version'], 'flutter_mismatch')
        runner.run('native', [sys.executable, ROOT / 'ci/native/build.py', '--build-ios', '--parent-owned-group', '--work-dir', work / 'native', '--output', work / 'native/Archivebridge.xcframework'])
        framework = work / 'native/Archivebridge.xcframework'
        native = read_json(work / 'native/result.json')
        require(native.get('status') == 'PASS_UNSIGNED_NATIVE_BUILD_ONLY' and native.get('native_runtime_test') is False, 'native_result')
        native_inventory = inventory(framework)
        require(native.get('artifact_files') == native_inventory, 'native_artifact_hashes')
        slices = framework_slices(framework)
        # A successful native run is quiescent: run() has already verified whole-group
        # cleanup. Retire only the five builder-only entries, never failed attempts.
        runner.guard()
        before_retirement = runner.resource_snapshot
        try:
            retirement = retire_native_tools(work, runner.work_identity, runner.results[-1],
                                             check=lambda: require(not runner.cancelled, 'cancelled'))
            runner.guard()
            emit('native_retirement', status='PASS', retirement=retirement,
                 before=before_retirement, after=runner.resource_snapshot)
        except BaseException as error:
            try:
                emit('native_retirement_failed', error=retirement_error(error))
            except BaseException:
                pass  # Diagnostics must not replace the retirement failure.
            raise
        with cfg.open('x', encoding='utf-8') as f:
            cfg_owned = True
            f.write(xcconfig(slices))
        cfg_hash = digest(cfg)
        runner.run('pub-locked', [flutter / 'bin/flutter', 'pub', 'get', '--enforce-lockfile'], cwd=APP, timeout=300)
        runner.run('native-dart-tests', [flutter / 'bin/flutter', 'test', '--no-pub', '--concurrency=1', '--reporter=expanded', *TESTS], cwd=APP, timeout=600)
        runner.run('ios-optin-dart-tests', [flutter / 'bin/flutter', 'test', '--no-pub', '--concurrency=1', '--reporter=expanded', *DEFINES, 'test/native_archive_entry_test.dart', 'test/native_archive_platform_test.dart'], cwd=APP, timeout=300)
        # Flutter owns current-engine acquisition/configuration. No upgrade or
        # pod/repo update is requested; tracked source/lock drift is fatal.
        runner.run('ios-config', [flutter / 'bin/flutter', 'build', 'ios', '--debug', '--no-codesign', '--no-pub', '--config-only', *DEFINES], cwd=APP, timeout=600)
        artifact_rows = []
        for sdk, destination in [('iphoneos', 'generic/platform=iOS'), ('iphonesimulator', 'generic/platform=iOS Simulator')]:
            require(digest(cfg) == cfg_hash and inventory(framework) == native_inventory, 'native_input_drift')
            base = ['/usr/bin/xcodebuild', '-jobs', '1', '-workspace', 'Runner.xcworkspace', '-scheme', 'Runner', '-configuration', 'Debug',
                    '-sdk', sdk, '-destination', destination, '-derivedDataPath', str(work / ('derived-' + sdk)),
                    '-disableAutomaticPackageResolution', '-onlyUsePackageVersionsFromResolvedFile',
                    'ARCHS=arm64', 'ONLY_ACTIVE_ARCH=YES', 'IPHONEOS_DEPLOYMENT_TARGET=15.0',
                    'SWIFT_ACTIVE_COMPILATION_CONDITIONS=DEBUG WAINAK_ARCHIVE_BRIDGE',
                    'GCC_PREPROCESSOR_DEFINITIONS=$(inherited) WAINAK_ARCHIVE_BRIDGE=1',
                    'FRAMEWORK_SEARCH_PATHS=$(inherited) "' + str(slices['device' if sdk == 'iphoneos' else 'simulator']) + '"',
                    'OTHER_LDFLAGS=$(inherited) -framework Archivebridge -framework Foundation', *SIGNING]
            settings_command, compile_command = xcode_commands(base, sdk)
            settings = json.loads(runner.run('settings-' + sdk, settings_command, cwd=APP / 'ios', timeout=120))
            cache_receipt = cache_policy_receipt(settings, sdk)
            unsigned_settings(settings, sdk)
            emit('compile_cache_policy', sdk=sdk, status='PASS', **cache_receipt)
            runner.run('compile-' + sdk, compile_command, cwd=APP / 'ios')
            app = work / ('derived-' + sdk) / 'Build/Products' / ('Debug-' + sdk) / 'Runner.app'
            require(app.is_dir() and not app.is_symlink(), 'app_missing')
            require(not (app / '_CodeSignature').exists() and not (app / 'embedded.mobileprovision').exists(), 'signed_app')
            require(not (app / 'Frameworks/Archivebridge.framework').exists(), 'static_framework_embedded')
            # Independent signing-tool negative check. Its nonzero status is
            # expected, so execute only through this bounded, constant helper.
            verify = runner.run('unsigned-' + sdk, [sys.executable, ROOT / 'ci/ios/check_unsigned.py', app], timeout=30)
            require(verify.strip() == b'PASS_UNSIGNED_APP', 'unsigned_check')
            row = {'sdk': sdk, 'binary_sha256': digest(app / 'Runner'), 'runtime': 'NOT_RUN'}
            if sdk == 'iphonesimulator':
                product = work / ('derived-' + sdk) / 'Build/Products'
                test_bundles = list(product.rglob('RunnerTests.xctest'))
                test_runs = list(product.glob('*.xctestrun'))
                require(len(test_bundles) == 1 and len(test_runs) == 1, 'xctest_compile_evidence')
                require((test_bundles[0] / 'RunnerTests').is_file(), 'xctest_binary_missing')
                row.update(xctest='COMPILED_NOT_RUN', xctest_binary_sha256=digest(test_bundles[0] / 'RunnerTests'), xctestrun_sha256=digest(test_runs[0]))
            artifact_rows.append(row)
        require(inventory(framework) == native_inventory and digest(cfg) == cfg_hash, 'native_input_drift')
        final_result = {'status': 'PASS_UNSIGNED_IOS_COMPILE_ONLY', 'apps': artifact_rows,
            'native_artifact_files': native_inventory, 'native_transient_retirement': retirement,
            'source_files': runner.sources,
            'device_runtime': 'NOT_RUN', 'simulator_runtime': 'NOT_RUN', 'signing': False,
            'production_security_acceptance': False,
            'flutter_provenance': 'Codemagic-provisioned SDK; exact Git revision/source integrity and version checked, whole archive not independently rehashed',
            'flutter_tool_sources': runner.flutter_sources}
    finally:
        # Preserve an in-flight command error even if final config/source checks fail.
        primary = sys.exc_info()[1]
        failures = cleanup_owned_files(cfg_owned, cfg, cfg_hash, runner.sources)
        if failures:
            try:
                emit('final_cleanup_failed', primary=None if primary is None else safe_error(primary), cleanup_errors=failures)
            except BaseException:
                pass  # Never replace the existing error when diagnostics cannot be written.
            if primary is None:
                raise GateError('command_cleanup_failed')

    (work / 'result.json').write_text(json.dumps(final_result, indent=2) + '\n')
    print('PASS unsigned iOS compile only; runtime and production security NOT accepted')


if __name__ == '__main__':
    try:
        main()
    except (GateError, OSError, ValueError, subprocess.SubprocessError) as error:
        try:
            emit('build_failed', error=safe_error(error))
        except OSError:
            pass
        raise SystemExit(1)
