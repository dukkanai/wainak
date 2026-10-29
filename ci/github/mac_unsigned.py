#!/usr/bin/env python3
"""Manual standard GitHub Mac: analyzer regression and unsigned fake UI compile only."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ci.testflight import sdk_overlay as sdk, diagnostics as d, group_observation as groups, policy as p
from ci.testflight.build import child_environment
from ci.testflight.check_sdk_dispose import check as dispose_check
from scripts.ci_process import run_bounded

LABELS=frozenset({'source_commit','source_clean','publication','preparation','regressions','xcode_version',
    'extract_sdk','flutter_version','sdk_head','sdk_inventory','sdk_provider_dependencies','sdk_dependencies','pub_get','analyze','entry_test',
    'compile_unsigned','verify_unsigned','source_unchanged','architecture'})
GIB=1024**3
SAFE_POLICY_REASONS=frozenset({'github_standard_arm_mac','github_manual_public_standard_only',
    'github_exact_sha','github_initial_disk','github_checkout','github_time_disk','github_workspace_budget',
    'github_sdk_url','github_sdk_redirect','github_sdk_download_bound','github_sdk_archive_hash',
    'github_fresh_work','github_command_identity','github_source_sha','github_dirty_source',
    'github_xcode_pin','github_flutter_pin','github_unsigned_result','github_arm64_artifact','github_source_drift'})


def preflight(env, host, machine, free):
    p.require(host=='darwin' and machine=='arm64','github_standard_arm_mac')
    expected={'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'dukkanai/wainak',
        'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/dev/ios-testflight-internal-20261029',
        'RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'macOS','RUNNER_ARCH':'ARM64',
        'WAINEK_REPOSITORY_VISIBILITY':'public','WAINEK_RUNNER_LABEL':'macos-26'}
    p.require(all(env.get(k)==v for k,v in expected.items()),'github_manual_public_standard_only')
    p.require(re.fullmatch('[a-f0-9]{40}',env.get('GITHUB_SHA','')) is not None and
        env.get('WAINEK_EXPECTED_SHA')==env['GITHUB_SHA'],'github_exact_sha')
    p.require(free>=10*GIB,'github_initial_disk')
    p.require(Path(env.get('GITHUB_WORKSPACE','/nonexistent')).resolve()==ROOT,'github_checkout')


def resource_guard(work, mobile, deadline):
    p.require(time.monotonic()<deadline and shutil.disk_usage(ROOT).free>=4*GIB,'github_time_disk')
    total=0
    for root in (work,mobile/'build'):
        if not root.exists():continue
        for file in root.rglob('*'):
            if file.is_file() and not file.is_symlink():total+=file.stat().st_size
            p.require(total<=8*GIB,'github_workspace_budget')


def download(spec, target, guard):
    p.require(spec['archive_url']=='https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/flutter_macos_arm64_3.47.8-stable.zip', 'github_sdk_url')
    digest=hashlib.sha256();count=0
    with urllib.request.urlopen(spec['archive_url'],timeout=30) as response,target.open('xb') as output:
        p.require(response.geturl()==spec['archive_url'],'github_sdk_redirect')
        while block:=response.read(1024*1024):
            count+=len(block);p.require(count<=3*GIB,'github_sdk_download_bound');guard()
            digest.update(block);output.write(block)
    p.require(digest.hexdigest()==spec['archive_sha256'],'github_sdk_archive_hash')


def run_checked(label,command,*,cwd,env,deadline,guard,overlay,seconds=300,
                allowed_labels=LABELS,safe_reasons=SAFE_POLICY_REASONS):
    p.require(label in allowed_labels,'github_command_identity')
    detail={};started=time.monotonic();outcome='FAILED';phase='pre_verification';command_outcome='NOT_RUN';reason='NONE'
    print(json.dumps({'event':'GITHUB_MAC_COMMAND','command':label,'outcome':'START'}),flush=True)
    try:
        guard()
        if overlay:overlay.verify()
        phase='command';command_outcome='FAILED'
        result=run_bounded(command,cwd=cwd,env=env,seconds=min(seconds,max(.01,deadline-time.monotonic())),
            check=True,diagnostic=detail,group_observer=groups.capture)
        command_outcome='PASS';phase='post_verification'
        guard()
        if overlay:overlay.verify()
        outcome='PASS';phase='complete'
        return result.stdout
    except BaseException as error:
        value=error.args[0] if isinstance(error,p.PolicyError) and error.args else None
        reason=value if type(value) is str and value in safe_reasons | sdk.SAFE_POLICY_REASONS else 'OTHER'
        raise
    finally:
        process_kind=detail.get('failure_kind','NONE')
        if type(process_kind) is not str or process_kind not in d.FAILURE_KINDS:process_kind='OTHER'
        kind=({'pre_verification':'PRE_VERIFICATION','post_verification':'POST_VERIFICATION'}.get(phase,
            process_kind if process_kind!='NONE' else 'OTHER')) if outcome=='FAILED' else 'NONE'
        row={'event':'GITHUB_MAC_COMMAND','command':label,'outcome':outcome,'command_outcome':command_outcome,
             'verification_phase':phase,'safe_reason':reason,'elapsed_seconds':round(time.monotonic()-started,3),
             'failure_kind':kind,'process_failure_kind':process_kind,
             'exit_code':d.integer(detail.get('exit_code'),-255,255),
             'cleanup_failed':detail.get('cleanup_failed') is True,
             'output_bytes':d.integer(detail.get('output_bytes'),0,16*1024**2),
             'group_before_cleanup':groups.project(detail.get('group_before_cleanup')),
             'group_after_cleanup':groups.project(detail.get('group_after_cleanup')),
             **d.project_cleanup_errors(detail.get('cleanup_errors',[]))}
        print(json.dumps(row),flush=True)


def fresh_work(work, mobile):
    p.require(not work.exists() and not work.is_symlink() and
              not (mobile/'build').exists() and not (mobile/'build').is_symlink(), 'github_fresh_work')


def execute():
    free=shutil.disk_usage(ROOT).free
    print(json.dumps({'event':'GITHUB_MAC_PREFLIGHT',
        'host':sys.platform if sys.platform in {'linux','darwin'} else 'OTHER',
        'machine':platform.machine() if platform.machine() in {'arm64','x86_64'} else 'OTHER',
        'python':d.numeric_version(platform.python_version()),
        'free_bytes':d.integer(free,0,2**60)}),flush=True)
    preflight(os.environ,sys.platform,platform.machine(),free)
    os.umask(0o077)
    work=ROOT/'.ci-github';mobile=ROOT/'apps/mobile'
    fresh_work(work,mobile)
    env=child_environment(os.environ)
    env.pop('SSH_AUTH_SOCK',None);env.pop('SDKROOT',None);env.pop('FLUTTER_ROOT',None)
    env['DEVELOPER_DIR']='/Applications/Xcode_26.4.1.app/Contents/Developer'
    deadline=time.monotonic()+40*60
    overlay=None
    def guard():resource_guard(work,mobile,deadline)
    def run(label,command,cwd=ROOT,seconds=300):
        return run_checked(label,command,cwd=cwd,env=env,deadline=deadline,guard=guard,overlay=overlay,seconds=seconds)
    p.require(run('source_commit',['git','rev-parse','HEAD']).strip()==os.environ['GITHUB_SHA'],'github_source_sha')
    p.require(not run('source_clean',['git','status','--porcelain']).strip(),'github_dirty_source')
    run('publication',[sys.executable,'scripts/check_publication.py'])
    run('preparation',[sys.executable,'ci/check_preparation.py'])
    run('regressions',[sys.executable,'-m','unittest','discover','-s','ci/tests','-q'])
    p.require(run('xcode_version',['/usr/bin/xcodebuild','-version']).splitlines()==['Xcode 26.4.1','Build version 17E202'],'github_xcode_pin')
    work.mkdir(mode=0o700)
    for name in ('home','tmp','pub-cache'):(work/name).mkdir(mode=0o700)
    env.update(HOME=str(work/'home'),TMPDIR=str(work/'tmp'),PUB_CACHE=str(work/'pub-cache'))
    pins=json.loads((ROOT/'ci/ios-host-pins.json').read_text())['flutter']
    archive=work/'flutter.zip';download(pins,archive,guard)
    print(json.dumps({'event':'GITHUB_MAC_SDK_ARCHIVE','sha256':pins['archive_sha256'],'verified':True}),flush=True)
    run('extract_sdk',['/usr/bin/ditto','-x','-k',archive,work/'sdk'],seconds=300)
    archive.unlink()  # Only this driver's hash-verified downloaded archive.
    base=work/'sdk/flutter';env['PATH']=str(base/'bin')+':'+env['PATH']
    os.environ['PATH']=env['PATH']  # Discovery only; child environment remains allowlisted.
    version=json.loads(run('flutter_version',['flutter','--version','--machine']))
    for field,key in [('frameworkVersion','version'),('frameworkRevision','framework_revision'),
                      ('engineRevision','engine_revision'),('dartSdkVersion','dart_version')]:
        p.require(version.get(field)==pins[key],'github_flutter_pin')
    d.emit_host(ROOT,work,pins['version'],pins['dart_version'],checkout_variable='GITHUB_WORKSPACE',effective_env=env)
    overlay=sdk.prepare(work,run);print(json.dumps(overlay.report()),flush=True)
    print(json.dumps(dispose_check(overlay,work,env)),flush=True)
    run('pub_get',['flutter','pub','get','--enforce-lockfile'],cwd=mobile)
    env['FLUTTER_ROOT']=str(base)
    run('analyze',overlay.command(),cwd=mobile)
    run('entry_test',['flutter','test','--no-pub','--concurrency=1',*p.DEFINES,'test/testflight_entrypoint_test.dart'],cwd=mobile)
    config=work/'unsigned.xcconfig'
    config.write_text('CODE_SIGNING_ALLOWED = NO\nCODE_SIGNING_REQUIRED = NO\nCODE_SIGN_IDENTITY =\nDEVELOPMENT_TEAM =\nPROVISIONING_PROFILE_SPECIFIER =\nPROVISIONING_PROFILE =\n')
    env['XCODE_XCCONFIG_FILE']=str(config)
    run('compile_unsigned',['flutter','build','ios','--release','--no-pub','--no-codesign',*p.DEFINES],cwd=mobile,seconds=1200)
    app=mobile/'build/ios/iphoneos/Runner.app'
    p.require(run('verify_unsigned',[sys.executable,ROOT/'ci/ios/check_unsigned.py',app]).strip()=='PASS_UNSIGNED_APP','github_unsigned_result')
    p.require(run('architecture',['/usr/bin/lipo','-archs',app/'Runner']).strip()=='arm64','github_arm64_artifact')
    p.require(not run('source_unchanged',['git','diff','--exit-code','HEAD','--']).strip(),'github_source_drift')
    overlay.verify()
    print(json.dumps({'status':'PASS_UNSIGNED_FAKE_UI_COMPILE_ONLY','source_commit':os.environ['GITHUB_SHA'],
        'executable_sha256':hashlib.sha256((app/'Runner').read_bytes()).hexdigest(),
        'runtime_voiceover':'NOT_RUN','apple_upload':False,'artifact_publication':False}),flush=True)
    # In-process handoff only: retain the SAME frozen SDK baseline and deadline.
    # The standalone unsigned entry point does not invoke any signing code.
    return {'work':work,'mobile':mobile,'env':env,'deadline':deadline,'overlay':overlay,'guard':guard}


def main():
    try:execute()
    except BaseException as error:
        reason=error.args[0] if isinstance(error,p.PolicyError) and error.args else None
        print(json.dumps({'status':'FAILED_CLOSED','artifact_eligible':False,'raw_output':'withheld',
            'safe_reason':reason if type(reason) is str and reason in SAFE_POLICY_REASONS | sdk.SAFE_POLICY_REASONS else 'OTHER',
            'error_type':d.error_type(error)}),flush=True)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
