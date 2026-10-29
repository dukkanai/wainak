#!/usr/bin/env python3
"""Explicit Codemagic-only internal UI export. No Apple API or key creation."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import shutil
import stat
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from ci.testflight import policy as p
from scripts.ci_process import run_bounded


def preflight(env, host, machine, root):
    p.require(host == 'darwin' and machine == 'arm64', 'codemagic_macos_required')
    p.require(env.get('CM_PROJECT_ID') == '6add6ea46576d8df9a1d3f59', 'wrong_codemagic_project')
    p.require(env.get('CM_WORKFLOW_NAME') in {'ios-testflight', p.workflow()['name']}, 'wrong_workflow')
    p.require(env.get('CM_TRIGGER_SOURCE') == 'api' and env.get('CM_PULL_REQUEST') == 'false', 'manual_non_pr_required')
    p.require(Path(env.get('CM_BUILD_DIR', '/nonexistent')).resolve() == root, 'wrong_checkout')
    p.require(re.fullmatch(r'[a-f0-9]{40}', env.get('CM_COMMIT', '')) is not None, 'missing_source_commit')
    p.require(re.fullmatch(r'[0-9]{1,8}', env.get('PROJECT_BUILD_NUMBER', '')) is not None, 'project_build_number')
    return p.build_number(str(int(env['PROJECT_BUILD_NUMBER']) + 1))


def safe_unpack(ipa, destination):
    p.require(ipa.is_file() and not ipa.is_symlink() and ipa.stat().st_size <= 1024**3, 'ipa_file')
    with zipfile.ZipFile(ipa) as archive:
        entries = archive.infolist()
        p.require(0 < len(entries) <= 20000 and sum(x.file_size for x in entries) <= 2*1024**3, 'ipa_size')
        seen = set()
        for entry in entries:
            name = entry.filename.rstrip('/')
            path = PurePosixPath(name)
            mode = entry.external_attr >> 16
            p.require(name and not path.is_absolute() and '..' not in path.parts and str(path) == name
                      and '\\' not in name and name not in seen, 'ipa_path')
            p.require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'ipa_special_file')
            seen.add(name)
        p.require('Payload/Runner.app/Info.plist' in seen, 'missing_runner')
        p.require(not any(n.startswith('Payload/') and len(PurePosixPath(n).parts) >= 2
                          and PurePosixPath(n).parts[1] != 'Runner.app' for n in seen), 'extra_application')
        p.require(not any(n.endswith(('.appex', '.xcframework')) or 'Archivebridge.framework' in n for n in seen), 'unexpected_extension_or_archive')
        destination.mkdir(mode=0o700)
        # All names/types/sizes checked before the first write; no ZIP symlinks.
        archive.extractall(destination)
        for entry in entries:
            file = destination / entry.filename
            if file.is_file() and (entry.external_attr >> 16) & 0o111:
                file.chmod(0o700)
    return destination / 'Payload/Runner.app'


def xml_plist(text):
    start = text.find('<?xml')
    end = text.find('</plist>', start)
    p.require(start >= 0 and end >= start, 'missing_plist_output')
    return plistlib.loads(text[start:end+8].encode())


def child_environment(source):
    # App Store Connect/private-key variables stay with Codemagic's publisher.
    allowed = {'HOME', 'PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'DEVELOPER_DIR',
               'FLUTTER_ROOT', 'PUB_CACHE', 'SDKROOT', 'SSH_AUTH_SOCK'}
    env = {k: v for k, v in source.items() if k in allowed}
    env.update(CI='true', FLUTTER_SUPPRESS_ANALYTICS='true', DART_SUPPRESS_ANALYTICS='true')
    return env


def execute():
    number = preflight(os.environ, sys.platform, platform.machine(), ROOT)
    os.umask(0o077)
    mobile = ROOT / 'apps/mobile'
    work = ROOT / '.ci-work/testflight'
    output = ROOT / p.ARTIFACT
    p.require(not work.exists() and not work.is_symlink(), 'existing_work_directory')
    p.require(not (mobile / 'build').exists() and not (mobile / 'build').is_symlink(), 'stale_build_directory')
    p.require(not (ROOT / '.ci-work').is_symlink(), 'work_parent_symlink')
    env = child_environment(os.environ)
    deadline = time.monotonic() + 35*60
    stage = 'preflight'

    def run(command, cwd=ROOT, seconds=300):
        remaining = int(deadline - time.monotonic())
        p.require(remaining > 0 and shutil.disk_usage(ROOT).free >= 4*1024**3, 'time_or_disk_limit')
        result = run_bounded(command, cwd=cwd, env=env, seconds=min(seconds, remaining), check=True)
        return result.stdout

    # Recheck before use-profiles modifies the disposable cloud project.
    run([sys.executable, ROOT / 'ci/check_preparation.py'])
    commit = run(['git', 'rev-parse', 'HEAD']).strip()
    p.require(commit == os.environ['CM_COMMIT'] and not run(['git', 'status', '--porcelain']).strip(), 'dirty_or_wrong_source')
    pins = json.loads((ROOT / 'ci/ios-host-pins.json').read_text())
    version = json.loads(run(['flutter', '--version', '--machine']))
    for field, expected in [('frameworkVersion', 'version'), ('frameworkRevision', 'framework_revision'),
                            ('engineRevision', 'engine_revision'), ('dartSdkVersion', 'dart_version')]:
        p.require(version.get(field) == pins['flutter'][expected], 'flutter_pin')
    p.require(run(['xcodebuild', '-version']).splitlines() == ['Xcode 26.4.1', 'Build version 17E202'], 'xcode_pin')
    work.mkdir(mode=0o700, parents=True)
    try:
        stage = 'flutter_host_checks'
        run(['flutter', 'pub', 'get', '--enforce-lockfile'], mobile)
        run(['flutter', 'analyze', '--no-pub'], mobile)
        run(['flutter', 'test', '--no-pub', '--concurrency=1', *p.DEFINES,
             'test/testflight_entrypoint_test.dart'], mobile)
        p.require(not run(['git', 'diff', '--exit-code', '--', 'apps/mobile/pubspec.lock']).strip(), 'dependency_drift')
        stage = 'profiles_and_export_policy'
        export = work / 'export.plist'
        # ios_signing imports owner-uploaded identities on the disposable host.
        # No fetch-signing-files --create, certificate creation or keychain reset.
        run(['xcode-project', 'use-profiles', '--project', mobile / 'ios/Runner.xcodeproj',
             '--archive-method', 'app-store', '--export-options-plist', export,
             '--custom-export-options', json.dumps(p.CUSTOM_EXPORT)])
        p.validate_export(plistlib.loads(export.read_bytes()))
        export_hash = hashlib.sha256(export.read_bytes()).hexdigest()
        env['XCODE_XCCONFIG_FILE'] = str(ROOT / 'ci/testflight/Signing.xcconfig')
        run(['flutter', 'build', 'ios', '--config-only', '--release', '--no-pub', '--no-codesign',
             '--build-number', number, *p.DEFINES], mobile)
        settings = json.loads(run(['xcodebuild', '-project', mobile / 'ios/Runner.xcodeproj',
                                   '-scheme', 'Runner', '-configuration', 'Release', '-sdk', 'iphoneos',
                                   '-showBuildSettings', '-json']))
        p.validate_settings(settings)
        stage = 'signed_internal_export'
        run(['flutter', 'build', 'ipa', '--release', '--no-pub', '--build-number', number,
             '--export-options-plist', export, *p.DEFINES], mobile, seconds=1200)
        p.require(hashlib.sha256(export.read_bytes()).hexdigest() == export_hash, 'export_policy_changed')
        p.validate_export(plistlib.loads(export.read_bytes()))
        candidates = list((mobile / 'build/ios/ipa').glob('*.ipa'))
        p.require(len(candidates) == 1, 'ipa_count')
        stage = 'verify_signed_payload'
        ipa = candidates[0]
        app = safe_unpack(ipa, work / 'inspect')
        run(['codesign', '--verify', '--deep', '--strict', app])
        entitlements = xml_plist(run(['codesign', '-d', '--entitlements', ':-', app]))
        profile = xml_plist(run(['security', 'cms', '-D', '-i', app / 'embedded.mobileprovision']))
        info = plistlib.loads((app / 'Info.plist').read_bytes())
        p.validate_profile(profile, entitlements, info, number)
        p.require(info.get('CFBundleExecutable') == 'Runner', 'executable_name')
        p.require(run(['lipo', '-archs', app / 'Runner']).strip() == 'arm64', 'device_architecture')
        report = {'status': 'VERIFIED_INTERNAL_IPA', 'source_commit': commit, 'build_number': number,
                  'bundle_identifier': p.BUNDLE, 'team': p.TEAM, 'mode': 'fake',
                  'internal_only_export': True, 'sha256': hashlib.sha256(ipa.read_bytes()).hexdigest(),
                  'export_options_sha256': export_hash, 'runtime_voiceover': 'NOT_RUN',
                  'app_store_connect_processing': 'NOT_RUN_BY_DRIVER'}
        (work / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
        output.parent.mkdir(mode=0o700)
        # This is the only path eligible for Codemagic publishing. Created last.
        ipa.rename(output)
        print(json.dumps(report))
    except BaseException:
        if output.is_file() and not output.is_symlink():
            output.unlink()
        print(json.dumps({'status': 'FAILED_CLOSED', 'stage': stage, 'artifact_eligible': False}))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-internal', action='store_true', required=True)
    parser.parse_args()
    try:
        execute()
    except Exception as error:
        # Never emit provider credentials, decoded provisioning bytes or raw logs.
        print(json.dumps({'status': 'FAILED', 'error_type': type(error).__name__, 'raw_output': 'withheld'}))
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
