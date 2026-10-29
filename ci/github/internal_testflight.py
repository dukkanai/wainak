#!/usr/bin/env python3
"""Protected manual GitHub internal UI path. --check needs no Apple credentials."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import secrets
import shlex
import sys
import time
import unicodedata
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ci.github import internal_policy as q, mac_unsigned as g
from ci.testflight import policy as p, diagnostics as d
from ci.testflight.build import safe_unpack, xml_plist, child_environment
from scripts import security_diagnostics as security

LABELS=frozenset({'keychain_list','keychain_create','keychain_unlock','keychain_import','keychain_access',
    'keychain_select','keychain_restore','keychain_delete','signing_identity','profile_decode','ios_config',
    'build_settings','build_ipa','verify_signature','read_entitlements','read_profile','extract_certificate',
    'architecture','source_commit','source_clean','upload_ipa','xcode_version'})
WORK=ROOT/'.ci-github'
PRIVATE=WORK/'signing'
IPA=WORK/'verified/wainek-internal.ipa'
RECEIPT=WORK/'verified/result.json'


def sha(data):return hashlib.sha256(data).hexdigest()


def regular(path, limit=1024*1024):
    p.require(not WORK.is_symlink() and path.resolve().is_relative_to(WORK.resolve()) and
              not any(x.is_symlink() for x in (path,*path.parents) if x.is_relative_to(WORK)) and
              path.is_file() and path.stat().st_size<=limit,'signed_path')
    return path.read_bytes()


def new_file(path, data):
    p.require(not WORK.is_symlink() and not path.exists() and not path.is_symlink() and path.parent.is_dir() and
              path.parent.resolve().is_relative_to(WORK.resolve()) and
              not any(x.is_symlink() for x in path.parents if x.is_relative_to(WORK)),'signed_existing_path')
    with path.open('xb') as file:file.write(data)
    path.chmod(0o600)


def decode(value, limit):
    p.require(type(value) is str and 0<len(value)<=4*((limit+2)//3),'signed_secret_bound')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,UnicodeError):raise p.PolicyError('signed_secret_encoding') from None
    p.require(0<len(raw)<=limit,'signed_secret_bound')
    return raw


def preflight(env, pins):
    q.validate_reviewed_pins(pins)  # Before reading any credential value.
    number=q.context(env)
    g.preflight(env,sys.platform,platform.machine(),g.shutil.disk_usage(ROOT).free)
    return number


def runner(env, deadline, overlay=None):
    def run(label, command, cwd=ROOT, seconds=300):
        return g.run_checked(label,command,cwd=cwd,env=env,deadline=deadline,
            guard=lambda:g.resource_guard(WORK,ROOT/'apps/mobile',deadline),overlay=overlay,seconds=seconds,
            allowed_labels=LABELS,safe_reasons=g.SAFE_POLICY_REASONS|q.REASONS,
            **({'output_profile':security.PROFILE} if label=='keychain_import' and
               list(command[:2])==['/usr/bin/security','import'] else {}))
    return run


def cleanup_runner():
    # Cleanup must remain possible after disk/deadline/SDK verification failure.
    # It still requires bounded processes and verified group cleanup.
    env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(WORK/'home')}
    deadline=time.monotonic()+60
    def run(label, command):
        return g.run_checked(label,command,cwd=ROOT,env=env,deadline=deadline,
            guard=lambda:None,overlay=None,seconds=25,
            allowed_labels=frozenset({'keychain_restore','keychain_delete'}),safe_reasons=q.REASONS)
    return run


def profile_check(profile, pins, number):
    # Preserve the signed profile's actual UUID spelling; never normalize bytes
    # or reuse Codemagic's independent historical profile reference.
    p.require(profile.get('UUID')==pins['profile_uuid'] and profile.get('Name')==pins['profile_name'],'signed_profile_identity')
    p.validate_profile(profile,profile.get('Entitlements',{}),
        {'CFBundleIdentifier':p.BUNDLE,'CFBundleVersion':number,'DTPlatformName':'iphoneos'},number)
    certs=profile.get('DeveloperCertificates',[])
    p.require(type(certs) is list and len(certs)==1 and type(certs[0]) is bytes and
        sha(certs[0])==pins['certificate_sha256'] and
        hashlib.sha1(certs[0]).hexdigest().upper()==pins['certificate_sha1'],'signed_certificate')


def decode_profile(run, label, path, keychain, pins):
    p.require(label in {'profile_decode','read_profile'} and path.is_absolute(),'signed_cms_input')
    data=regular(path,36*1024)
    p.require(sha(data)==pins['profile_sha256'],'signed_profile_hash')
    p.require(data.startswith(b'\x30'),'signed_cms_input')  # Pinned DER CMS, not PEM/base64 text.
    p.require(keychain.is_absolute() and keychain==PRIVATE/'distribution.keychain-db' and
              keychain.is_file() and not keychain.is_symlink() and not PRIVATE.is_symlink() and
              keychain.parent.resolve()==PRIVATE.resolve(),'signed_cms_keychain')
    print(json.dumps({'event':'GITHUB_CMS_INPUT','role':label,'absolute_path':True,
        'regular_profile':True,'profile_bytes':len(data),'pinned_hash_match':True,
        'format':'PINNED_DER','explicit_owned_keychain':True,'cwd':'CHECKOUT_ROOT'}),flush=True)
    try:
        # cms imports its embedded certificates. Supply the already unlocked
        # owned keychain; do not depend on a default keychain in isolated HOME.
        output=run(label,['/usr/bin/security','cms','-D','-k',keychain,'-i',path],cwd=ROOT)
    except RuntimeError:
        # Process exit/timeout/cleanup details remain in the bounded command event.
        raise p.PolicyError('signed_cms_command_failed') from None
    p.require(sha(regular(path,36*1024))==pins['profile_sha256'],'signed_profile_hash')
    return xml_plist(output)


def unpack_signed(ipa, destination):
    # A Mac volume can merge names that Linux treats as different. Reject even
    # implicit parent aliases before the existing bounded ZIP extractor writes.
    seen={}
    p.require(ipa.is_file() and not ipa.is_symlink() and ipa.stat().st_size<=1024**3,'signed_path')
    with zipfile.ZipFile(ipa) as archive:
        p.require(len(archive.infolist())<=20000,'signed_path')
        for entry in archive.infolist():
            parts=entry.filename.rstrip('/').split('/')
            for count in range(1,len(parts)+1):
                name='/'.join(parts[:count]);folded=unicodedata.normalize('NFD',name).casefold()
                p.require(folded not in seen or seen[folded]==name,'signed_path')
                seen[folded]=name
    return safe_unpack(ipa,destination)


def cleanup(run):
    # Own isolated HOME only. Never delete an owner's login keychain/profile.
    p.require(not WORK.is_symlink() and not PRIVATE.is_symlink(),'signed_path')
    if not PRIVATE.exists():return
    errors=0
    journal=PRIVATE/'search-list.json'
    if journal.exists():
        try:
            paths=json.loads(regular(journal))
            p.require(type(paths) is list and len(paths)<=32 and all(type(x) is str and x.startswith('/') and
                '\n' not in x and '\0' not in x for x in paths),'signed_path')
            run('keychain_restore',['/usr/bin/security','list-keychains','-d','user','-s',*paths])
            journal.unlink()
        except BaseException:errors+=1
    keychain=PRIVATE/'distribution.keychain-db'
    if keychain.exists() or keychain.is_symlink():
        try:
            p.require(not keychain.is_symlink(),'signed_path')
            run('keychain_delete',['/usr/bin/security','delete-keychain',keychain])
            p.require(not keychain.exists(),'signed_cleanup')
        except BaseException:errors+=1
    # Explicit owned files only, no broad recursive deletion.
    for name in ('distribution.p12','profile.mobileprovision','upload.p8'):
        path=PRIVATE/name
        try:
            if path.is_symlink():raise p.PolicyError('signed_path')
            if path.exists():path.unlink()
        except BaseException:errors+=1
    for directory in (WORK/'home/Library/MobileDevice/Provisioning Profiles',
                      WORK/'home/Library/Developer/Xcode/UserData/Provisioning Profiles', PRIVATE/'private_keys'):
        try:
            if directory.exists():
                p.require(directory.resolve().is_relative_to(WORK.resolve()) and not directory.is_symlink(),'signed_path')
                for path in directory.iterdir():
                    p.require(path.is_file() and not path.is_symlink(),'signed_path')
                    path.unlink()
        except BaseException:errors+=1
    if errors:raise p.PolicyError('signed_cleanup')


def compile_internal(pins, number, ctx, secret_source):
    env=dict(ctx['env']);env.pop('XCODE_XCCONFIG_FILE',None)
    run=runner(env,ctx['deadline'],ctx['overlay'])
    p.require(not PRIVATE.exists() and not PRIVATE.is_symlink(),'signed_existing_path')
    PRIVATE.mkdir(mode=0o700)
    keychain=PRIVATE/'distribution.keychain-db'
    export=PRIVATE/'export.plist'
    key_password=secrets.token_hex(32)  # Ephemeral keychain password, NOT an Apple key.
    candidate=None
    try:
        raw=decode(secret_source[q.SIGNING_SECRETS[2]],36*1024)
        p.require(sha(raw)==pins['profile_sha256'],'signed_profile_hash')
        profile_path=PRIVATE/'profile.mobileprovision';new_file(profile_path,raw)
        prior=shlex.split(run('keychain_list',['/usr/bin/security','list-keychains','-d','user']))
        p.require(len(prior)<=32 and all(x.startswith('/') and '\n' not in x and '\0' not in x for x in prior),'signed_path')
        new_file(PRIVATE/'search-list.json',json.dumps(prior).encode())
        run('keychain_create',['/usr/bin/security','create-keychain','-p',key_password,keychain])
        run('keychain_unlock',['/usr/bin/security','unlock-keychain','-p',key_password,keychain])
        profile=decode_profile(run,'profile_decode',profile_path,keychain,pins)
        profile_check(profile,pins,number)
        # P12 is not read/imported until the profile has passed validation.
        p12=PRIVATE/'distribution.p12';new_file(p12,decode(secret_source[q.SIGNING_SECRETS[0]],36*1024))
        password=secret_source[q.SIGNING_SECRETS[1]]
        p.require(type(password) is str and len(password)<=1024 and '\0' not in password,'signed_secret_bound')
        run('keychain_import',['/usr/bin/security','import',p12,'-k',keychain,'-P',password,'-T','/usr/bin/codesign','-T','/usr/bin/security'])
        run('keychain_access',['/usr/bin/security','set-key-partition-list','-S','apple-tool:,apple:,codesign:','-s','-k',key_password,keychain])
        run('keychain_select',['/usr/bin/security','list-keychains','-d','user','-s',keychain,*prior])
        identities=run('signing_identity',['/usr/bin/security','find-identity','-v','-p','codesigning',keychain])
        found=re.findall(r'\) ([A-F0-9]{40}) "(Apple Distribution: [^"\n]+)"',identities)
        p.require(len(found)==1 and found[0][0]==pins['certificate_sha1'] and
                  found[0][1].endswith('('+p.TEAM+')') and '1 valid identities found' in identities,'signed_identity_count')
        # Both conventional and Xcode 16+ locations, inside this job's isolated HOME.
        for relative in ('Library/MobileDevice/Provisioning Profiles','Library/Developer/Xcode/UserData/Provisioning Profiles'):
            directory=WORK/'home'/relative;directory.mkdir(mode=0o700,parents=True,exist_ok=False)
            new_file(directory/(pins['profile_uuid']+'.mobileprovision'),raw)
        options={**p.CUSTOM_EXPORT,'provisioningProfiles':{p.BUNDLE:pins['profile_uuid']},
                 'signingCertificate':pins['certificate_sha1']}
        p.validate_export(options);new_file(export,plistlib.dumps(options));export_hash=sha(export.read_bytes())
        config=PRIVATE/'Signing.xcconfig'
        new_file(config,(p.SIGNING_CONFIG+'PROVISIONING_PROFILE_SPECIFIER = '+pins['profile_uuid']+'\n').encode())
        env['XCODE_XCCONFIG_FILE']=str(config)
        mobile=ctx['mobile']
        run('ios_config',['flutter','build','ios','--config-only','--release','--no-pub','--no-codesign',
            '--build-number',number,*p.DEFINES],cwd=mobile)
        settings=json.loads(run('build_settings',['/usr/bin/xcodebuild','-project',mobile/'ios/Runner.xcodeproj',
            '-scheme','Runner','-configuration','Release','-sdk','iphoneos','-showBuildSettings','-json']))
        p.validate_settings(settings)
        actual=next(x['buildSettings'] for x in settings if x.get('target')=='Runner')
        p.require(actual.get('PROVISIONING_PROFILE_SPECIFIER')==pins['profile_uuid'],'signed_settings')
        run('build_ipa',['flutter','build','ipa','--release','--no-pub','--build-number',number,
            '--export-options-plist',export,*p.DEFINES],cwd=mobile,seconds=1200)
        p.require(sha(regular(export))==export_hash and plistlib.loads(export.read_bytes())==options,'signed_export')
        candidates=list((mobile/'build/ios/ipa').glob('*.ipa'))
        p.require(len(candidates)==1,'signed_no_ipa');candidate=candidates[0]
        app=unpack_signed(candidate,WORK/'signed-inspect')
        run('verify_signature',['/usr/bin/codesign','--verify','--deep','--strict',app])
        entitlements=xml_plist(run('read_entitlements',['/usr/bin/codesign','-d','--entitlements',':-',app]))
        embedded=regular(app/'embedded.mobileprovision',256*1024)
        p.require(sha(embedded)==pins['profile_sha256'],'signed_profile_hash')
        embedded_profile=decode_profile(run,'read_profile',app/'embedded.mobileprovision',keychain,pins)
        profile_check(embedded_profile,pins,number)
        info=plistlib.loads(regular(app/'Info.plist'))
        p.validate_profile(embedded_profile,entitlements,info,number)
        p.require(info.get('CFBundleExecutable')=='Runner','signed_settings')
        prefix=PRIVATE/'leaf'
        run('extract_certificate',['/usr/bin/codesign','-d','--extract-certificates',prefix,app])
        p.require(sha(regular(PRIVATE/'leaf0'))==pins['certificate_sha256'],'signed_certificate')
        p.require(run('architecture',['/usr/bin/lipo','-archs',app/'Runner']).strip()=='arm64','signed_settings')
        p.require(not run('source_clean',['git','status','--porcelain']).strip(),'signed_source_drift')
        ctx['overlay'].verify()
    finally:
        # Failure here prevents the receipt/upload even after a successful build.
        cleanup(cleanup_runner())
    IPA.parent.mkdir(mode=0o700)
    candidate.rename(IPA)
    result={'status':'VERIFIED_INTERNAL_IPA','source_commit':os.environ['GITHUB_SHA'],
        'build_number':number,'bundle_identifier':p.BUNDLE,'team':p.TEAM,'asc_app_id':p.ASC_APP_ID,
        'sha256':sha(regular(IPA,1024**3)),'export_options_sha256':export_hash,
        'pins_sha256':sha(json.dumps(pins,sort_keys=True).encode()),'internal_only_export':True,
        'mode':'fake','cleanup_verified':True,'runtime_voiceover':'NOT_RUN','apple_upload':False}
    new_file(RECEIPT,(json.dumps(result,sort_keys=True)+'\n').encode())
    print(json.dumps(result),flush=True)


def validate_receipt(value, pins, number, commit):
    expected={'status':'VERIFIED_INTERNAL_IPA','source_commit':commit,'build_number':number,
        'bundle_identifier':p.BUNDLE,'team':p.TEAM,'asc_app_id':p.ASC_APP_ID,
        'pins_sha256':sha(json.dumps(pins,sort_keys=True).encode()),'internal_only_export':True,
        'mode':'fake','cleanup_verified':True,'runtime_voiceover':'NOT_RUN','apple_upload':False}
    p.require(type(value) is dict and set(value)==set(expected)|{'sha256','export_options_sha256'},'signed_receipt')
    for key, actual in expected.items():
        p.require(type(value[key]) is type(actual) and value[key]==actual,'signed_receipt')
    for key in ('sha256','export_options_sha256'):
        p.require(type(value[key]) is str and re.fullmatch('[a-f0-9]{64}',value[key]),'signed_receipt')


def upload(pins, number, secret_source):
    env=child_environment(os.environ);env.pop('SSH_AUTH_SOCK',None)
    env['PATH']='/usr/bin:/bin:/usr/sbin:/sbin'
    env.update(HOME=str(WORK/'home'),TMPDIR=str(WORK/'tmp'),DEVELOPER_DIR='/Applications/Xcode_26.4.1.app/Contents/Developer')
    run=runner(env,time.monotonic()+15*60)
    value=json.loads(regular(RECEIPT))
    validate_receipt(value,pins,number,os.environ['GITHUB_SHA'])
    p.require(sha(regular(IPA,1024**3))==value['sha256'],'signed_ipa_hash')
    p.require(run('source_commit',['git','rev-parse','HEAD']).strip()==os.environ['GITHUB_SHA'] and
              not run('source_clean',['git','status','--porcelain']).strip(),'signed_source_drift')
    p.require(run('xcode_version',['/usr/bin/xcodebuild','-version']).splitlines()==['Xcode 26.4.1','Build version 17E202'],'signed_settings')
    p.require(not (PRIVATE/'search-list.json').exists() and not (PRIVATE/'distribution.keychain-db').exists(),'signed_cleanup')
    marker=WORK/'upload-attempt.json'
    p.require(not marker.exists() and not marker.is_symlink(),'signed_upload_ambiguous')
    new_file(marker,b'{"state":"attempt_started_no_automatic_retry"}\n')
    keys=PRIVATE/'private_keys';keys.mkdir(mode=0o700)
    try:
        raw=decode(secret_source[q.UPLOAD_SECRETS[0]],16*1024)
        # Shape only; Apple validates the actual private key. Never log any bytes.
        start=b'-----BEGIN '+b'PRIVATE KEY-----';end=b'-----END '+b'PRIVATE KEY-----'
        p.require(raw.strip().startswith(start) and raw.strip().endswith(end),'signed_p8_shape')
        new_file(keys/('AuthKey_'+pins['asc_key_id']+'.p8'),raw)
        # altool discovers ./private_keys in this owned cwd. No Apple secrets in argv.
        run('upload_ipa',['/usr/bin/xcrun','altool','--upload-app','--type','ios','--file',IPA,
            '--apiKey',pins['asc_key_id'],'--apiIssuer',pins['asc_issuer_id']],cwd=PRIVATE,seconds=900)
    finally:cleanup(cleanup_runner())
    print(json.dumps({'status':'APPLE_UPLOAD_COMMAND_SUCCEEDED','source_commit':os.environ['GITHUB_SHA'],
        'sha256':value['sha256'],'app_store_connect_processing':'NOT_VERIFIED','internal_testflight_availability':'NOT_VERIFIED',
        'runtime_voiceover':'NOT_RUN','external_distribution':False}),flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    for option in ('check','build','upload','cleanup'):mode.add_argument('--'+option,action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.cleanup:
            # Do not strand owned signing files after a pin/workflow check fails.
            # Cleanup uses no secret values and retains host/path/process guards.
            p.require(sys.platform=='darwin' and os.environ.get('GITHUB_REPOSITORY')=='dukkanai/wainak' and
                Path(os.environ.get('GITHUB_WORKSPACE','/nonexistent')).resolve()==ROOT,'signed_context')
            cleanup(cleanup_runner());return 0
        pins=json.loads(q.PIN_FILE.read_text());q.validate_reviewed_pins(pins)
        q.validate_job(json.loads((ROOT/'ci/github/internal-testflight.job.json').read_text()))
        q.validate_active_workflow((ROOT/'.github/workflows/ci.yml').read_text())
        if args.check:
            print(json.dumps({'status':'SIGNED_PREPARATION_CONTRACT_PASS','enabled':pins['enabled'],
                'credentials_read':False,'runtime_signing':'NOT_RUN','apple_upload':False}));return 0
        number=preflight(os.environ,pins)
        if args.build:
            # All subprocesses receive the existing allowlisted child environment;
            # signing values are first read after the complete unsigned gates.
            ctx=g.execute()
            compile_internal(pins,number,ctx,os.environ)
        else:upload(pins,number,os.environ)
        return 0
    except BaseException as error:
        reason=error.args[0] if isinstance(error,p.PolicyError) and error.args else None
        safe=q.REASONS|g.SAFE_POLICY_REASONS|g.sdk.SAFE_POLICY_REASONS
        print(json.dumps({'status':'FAILED_CLOSED','artifact_eligible':False,'raw_output':'withheld',
            'safe_reason':reason if type(reason) is str and reason in safe else 'OTHER','error_type':d.error_type(error)}),flush=True)
        return 1


if __name__=='__main__':raise SystemExit(main())
