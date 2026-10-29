"""Synthetic-only tests. Never read Apple keys or invoke security/altool."""
import base64
import copy
import datetime
import hashlib
import io
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

from ci.github import internal_policy as q, internal_testflight as s, mac_unsigned as g
from ci.testflight import policy as p

CERT=b'synthetic-public-certificate-not-a-key'
PROFILE_BYTES=b'synthetic-provisioning-envelope'
PINS={'enabled':True,'certificate_sha256':hashlib.sha256(CERT).hexdigest(),
      'certificate_sha1':hashlib.sha1(CERT).hexdigest().upper(),
      'profile_sha256':hashlib.sha256(PROFILE_BYTES).hexdigest(),
      'profile_uuid':'12345678-1234-1234-1234-123456789ABC',
      'asc_key_id':'ABCDEF1234','asc_issuer_id':'12345678-1234-1234-1234-123456789abc'}
ENT={'application-identifier':p.TEAM+'.'+p.BUNDLE,'com.apple.developer.team-identifier':p.TEAM,
     'get-task-allow':False,'beta-reports-active':True}
PROFILE={'UUID':PINS['profile_uuid'],'Name':p.PROFILE,'TeamIdentifier':[p.TEAM],
         'ExpirationDate':datetime.datetime(2099,1,1),'Entitlements':ENT,'DeveloperCertificates':[CERT]}
INFO={'CFBundleIdentifier':p.BUNDLE,'CFBundleVersion':'17','DTPlatformName':'iphoneos','CFBundleExecutable':'Runner'}


def settings():
    return [{'target':'Runner','buildSettings':{'PRODUCT_BUNDLE_IDENTIFIER':p.BUNDLE,'DEVELOPMENT_TEAM':p.TEAM,
        'CONFIGURATION':'Release','PLATFORM_NAME':'iphoneos','CODE_SIGNING_ALLOWED':'YES','CODE_SIGNING_REQUIRED':'YES',
        'CODE_SIGN_STYLE':'Manual','CODE_SIGN_IDENTITY':'Apple Distribution','PROVISIONING_PROFILE_SPECIFIER':PINS['profile_uuid'],
        'DART_DEFINES':','.join(base64.b64encode(x.encode()).decode() for x in ['WAINEK_DEV_MODE=true','WAINEK_REPOSITORY=fake'])}}]


class Policy(unittest.TestCase):
    def test_disabled_before_credential_reads(self):
        pins=json.loads(q.PIN_FILE.read_text())
        self.assertFalse(pins['enabled'])
        class Unreadable(dict):
            def get(self,*args):raise AssertionError('environment read before activation')
            def __getitem__(self,key):raise AssertionError('credential read')
        with self.assertRaisesRegex(p.PolicyError,'signed_disabled'):s.preflight(Unreadable(),pins)
        for mode in ('--build','--upload'):
            with mock.patch.object(s,'compile_internal') as build,mock.patch.object(s,'upload') as upload,mock.patch('builtins.print') as out:
                self.assertEqual(s.main([mode]),1)
                self.assertEqual(json.loads(out.call_args.args[0])['safe_reason'],'signed_disabled')
                build.assert_not_called();upload.assert_not_called()

    def test_pin_schema_mutations(self):
        q.validate_pins(PINS,active=True)
        for key in q.PIN_FIELDS:
            with self.subTest(key=key):
                altered=copy.deepcopy(PINS);altered[key]='CANARY/$()\n'
                with self.assertRaises(p.PolicyError):q.validate_pins(altered,active=True)
        for altered in ({**PINS,'extra':True},{**PINS,'enabled':1}):
            with self.assertRaises(p.PolicyError):q.validate_pins(altered)

    def test_context_mutations(self):
        valid={'WAINEK_SIGNED_TARGET':'mac-internal','WAINEK_SIGNED_ENVIRONMENT':q.ENVIRONMENT,
               'GITHUB_RUN_ATTEMPT':'1','WAINEK_EXPECTED_SHA':'a'*40,'WAINEK_BUILD_NUMBER':'17'}
        self.assertEqual(q.context(valid),'17')
        for key in valid:
            with self.subTest(key=key),self.assertRaises(p.PolicyError):q.context({**valid,key:'CANARY'})
        for key,value in [('RUNNER_DEBUG','1'),('ACTIONS_STEP_DEBUG','true'),('ACTIONS_RUNNER_DEBUG','TRUE')]:
            with self.assertRaisesRegex(p.PolicyError,'signed_debug_logging'):q.context({**valid,key:value})

    def test_environment_protections(self):
        env={'name':q.ENVIRONMENT,'can_admins_bypass':False,
             'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True},
             'protection_rules':[{'type':'required_reviewers','prevent_self_review':True,
                                 'reviewers':[{'type':'User','reviewer':{'id':123}}]}]}
        branches=[{'name':q.BRANCH,'type':'branch'}];q.validate_environment(env,branches)
        for key,value in [('can_admins_bypass',True),('protection_rules',[]),('deployment_branch_policy',None),('name','other')]:
            with self.assertRaises(p.PolicyError):q.validate_environment({**env,key:value},branches)
        for rules in ([],[{'name':'*','type':'branch'}],[{'name':q.BRANCH,'type':'tag'}],branches*2):
            with self.assertRaises(p.PolicyError):q.validate_environment(env,rules)
        for field,value in [('prevent_self_review',False),('reviewers',[])]:
            changed=copy.deepcopy(env);changed['protection_rules'][0][field]=value
            with self.assertRaises(p.PolicyError):q.validate_environment(changed,branches)

    def test_dormant_workflow_exact_and_mutations(self):
        job=json.loads((q.ROOT/'ci/github/internal-testflight.job.json').read_text());q.validate_job(job)
        source=(q.ROOT/'.github/workflows/ci.yml').read_text()
        self.assertNotIn('mac-internal',source);self.assertNotIn('secrets.',source)
        candidate=(q.ROOT/'ci/github/internal-testflight.workflow.candidate').read_text()
        self.assertEqual(q.candidate_workflow(source),candidate)
        self.assertIn("inputs.target != 'mac-internal'",candidate)
        self.assertNotIn('pull_request_target',candidate)
        self.assertNotIn('upload-artifact',candidate)
        for key,value in [('runs-on','self-hosted'),('timeout-minutes',46),('permissions',{'contents':'write'}),
                          ('environment','unprotected'),('if','true'),('concurrency',{'cancel-in-progress':True})]:
            with self.subTest(key=key),self.assertRaises(p.PolicyError):q.validate_job({**job,key:value})
        for index,step in enumerate(job['steps']):
            changed=copy.deepcopy(job);changed['steps'][index]['run']='echo unsafe'
            with self.assertRaises(p.PolicyError):q.validate_job(changed)
        for step in job['steps']:
            if 'uses' in step:self.assertRegex(step['uses'],r'@[a-f0-9]{40}$')
            self.assertNotIn('${{',step.get('run',''))
        self.assertEqual(set(job['steps'][3]['env']),set(q.SIGNING_SECRETS))
        self.assertEqual(set(job['steps'][4]['env']),set(q.UPLOAD_SECRETS))

    def test_profile_negative_cases(self):
        s.profile_check(PROFILE,PINS,'17')
        cases={'Name':'wrong','UUID':'wrong','TeamIdentifier':['wrong'],'DeveloperCertificates':[b'other'],
               'ProvisionedDevices':[],'ExpirationDate':datetime.datetime(2000,1,1)}
        for key,value in cases.items():
            with self.subTest(key=key),self.assertRaises(p.PolicyError):s.profile_check({**PROFILE,key:value},PINS,'17')
        with self.assertRaises(p.PolicyError):s.profile_check(PROFILE,{**PINS,'certificate_sha1':'A'*40},'17')
        for key,value in [('get-task-allow',True),('beta-reports-active',False),('application-identifier','wrong')]:
            with self.assertRaises(p.PolicyError):s.profile_check({**PROFILE,'Entitlements':{**ENT,key:value}},PINS,'17')

    def test_decode_and_symlink_boundaries(self):
        self.assertEqual(s.decode(base64.b64encode(b'fixture').decode(),7),b'fixture')
        for value,limit in [('',10),('%%%%',10),('YWJj',2),('YWJj\n',10),('é',10)]:
            with self.assertRaises(p.PolicyError):s.decode(value,limit)
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(s,'WORK',Path(tmp)):
            root=Path(tmp);(root/'target').write_bytes(b'data');(root/'link').symlink_to(root/'target')
            with self.assertRaises(p.PolicyError):s.regular(root/'link')
            with self.assertRaises(p.PolicyError):s.new_file(root/'link',b'overwrite')
            self.assertEqual((root/'target').read_bytes(),b'data')
            (root/'directory').mkdir();(root/'directory/file').write_bytes(b'fixture')
            (root/'alias').symlink_to(root/'directory',target_is_directory=True)
            with self.assertRaises(p.PolicyError):s.regular(root/'alias/file')
            with self.assertRaises(p.PolicyError):s.new_file(root/'alias/new',b'fixture')

    def test_mac_archive_case_and_normalization_aliases(self):
        for first,second in [('Folder/a','folder/b'),('data','DATA'),('caf\u00e9/a','cafe\u0301/b')]:
            with self.subTest(first=first),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ipa=root/'test.ipa'
                with zipfile.ZipFile(ipa,'w') as archive:
                    archive.writestr('Payload/Runner.app/Info.plist',b'fixture')
                    archive.writestr('Payload/Runner.app/'+first,b'a')
                    archive.writestr('Payload/Runner.app/'+second,b'b')
                with self.assertRaisesRegex(p.PolicyError,'signed_path'):s.unpack_signed(ipa,root/'inspect')
                self.assertFalse((root/'inspect').exists())


class Lifecycle(unittest.TestCase):
    def exercise(self, failure=None, mutation=None, uploading=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();work=root/'.ci-github';work.mkdir();(work/'home').mkdir();(work/'tmp').mkdir()
            private=work/'signing';ipa=work/'verified/wainek-internal.ipa';receipt=ipa.parent/'result.json'
            mobile=root/'apps/mobile';mobile.mkdir(parents=True)
            overlay=mock.Mock();ctx={'env':{'PATH':'/safe/path','HOME':str(work/'home')},'deadline':9999999999,
                                    'overlay':overlay,'mobile':mobile}
            calls=[];failed=False
            commands=['profile_decode','keychain_list','keychain_create','keychain_unlock','keychain_import','keychain_access',
                'keychain_select','signing_identity','ios_config','build_settings','build_ipa','verify_signature','read_entitlements',
                'read_profile','extract_certificate','architecture','source_clean','keychain_restore','keychain_delete']
            outputs={'profile_decode':plistlib.dumps(PROFILE).decode(),'keychain_list':'"/original/login.keychain-db"\n',
                'signing_identity':f'  1) {PINS["certificate_sha1"]} "Apple Distribution: NEXTAURA LLC ({p.TEAM})"\n 1 valid identities found\n',
                'build_settings':json.dumps(settings()),'read_entitlements':plistlib.dumps(ENT).decode(),
                'read_profile':plistlib.dumps(PROFILE).decode(),'architecture':'arm64','source_commit':'a'*40,
                'xcode_version':'Xcode 26.4.1\nBuild version 17E202\n'}
            if mutation=='profile':outputs['profile_decode']=plistlib.dumps({**PROFILE,'Name':'wrong'}).decode()
            if mutation=='identity':outputs['signing_identity']='0 valid identities found'
            if mutation=='settings':outputs['build_settings']=json.dumps([{'target':'Runner','buildSettings':{}}])
            keychain=private/'distribution.keychain-db';app=work/'signed-inspect/Payload/Runner.app'
            expected_commands={
                'profile_decode':['/usr/bin/security','cms','-D','-i',private/'profile.mobileprovision'],
                'keychain_list':['/usr/bin/security','list-keychains','-d','user'],
                'keychain_create':['/usr/bin/security','create-keychain','-p','synthetic-password',keychain],
                'keychain_unlock':['/usr/bin/security','unlock-keychain','-p','synthetic-password',keychain],
                'keychain_import':['/usr/bin/security','import',private/'distribution.p12','-k',keychain,'-P','CANARY_PASSWORD','-T','/usr/bin/codesign','-T','/usr/bin/security'],
                'keychain_access':['/usr/bin/security','set-key-partition-list','-S','apple-tool:,apple:,codesign:','-s','-k','synthetic-password',keychain],
                'keychain_select':['/usr/bin/security','list-keychains','-d','user','-s',keychain,'/original/login.keychain-db'],
                'keychain_restore':['/usr/bin/security','list-keychains','-d','user','-s','/original/login.keychain-db'],
                'keychain_delete':['/usr/bin/security','delete-keychain',keychain],
                'signing_identity':['/usr/bin/security','find-identity','-v','-p','codesigning',keychain],
                'ios_config':['flutter','build','ios','--config-only','--release','--no-pub','--no-codesign','--build-number','17',*p.DEFINES],
                'build_settings':['/usr/bin/xcodebuild','-project',mobile/'ios/Runner.xcodeproj','-scheme','Runner','-configuration','Release','-sdk','iphoneos','-showBuildSettings','-json'],
                'build_ipa':['flutter','build','ipa','--release','--no-pub','--build-number','17','--export-options-plist',private/'export.plist',*p.DEFINES],
                'verify_signature':['/usr/bin/codesign','--verify','--deep','--strict',app],
                'read_entitlements':['/usr/bin/codesign','-d','--entitlements',':-',app],
                'read_profile':['/usr/bin/security','cms','-D','-i',app/'embedded.mobileprovision'],
                'extract_certificate':['/usr/bin/codesign','-d','--extract-certificates',private/'leaf',app],
                'architecture':['/usr/bin/lipo','-archs',app/'Runner'],
                'source_clean':['git','status','--porcelain'],
                'source_commit':['git','rev-parse','HEAD'],
                'xcode_version':['/usr/bin/xcodebuild','-version'],
                'upload_ipa':['/usr/bin/xcrun','altool','--upload-app','--type','ios','--file',ipa,'--apiKey',PINS['asc_key_id'],'--apiIssuer',PINS['asc_issuer_id']],
            }
            self.assertEqual(set(expected_commands),s.LABELS)
            def run(label,argv,**kwargs):
                nonlocal failed
                self.assertIn(label,s.LABELS,'unexpected command')
                self.assertEqual(argv,expected_commands[label],'unexpected argv')
                if label not in {'keychain_restore','keychain_delete'}:
                    self.assertFalse(failed,'continued after failure')
                    if not uploading:self.assertEqual(label,commands[len([x for x in calls if x not in {'keychain_restore','keychain_delete'}])])
                calls.append(label)
                if failure==label:failed=True;raise RuntimeError('CANARY_SECRET_OUTPUT')
                if label=='keychain_create':(private/'distribution.keychain-db').write_bytes(b'synthetic-keychain')
                if label=='keychain_delete':(private/'distribution.keychain-db').unlink()
                if label=='keychain_import':
                    self.assertNotIn('-A',argv);self.assertIn('/usr/bin/codesign',argv)
                if label=='keychain_restore':self.assertEqual(argv,['/usr/bin/security','list-keychains','-d','user','-s','/original/login.keychain-db'])
                if label=='build_ipa':
                    self.assertIn('--no-pub',argv);self.assertTrue(all(x in argv for x in p.DEFINES))
                    options=plistlib.loads((private/'export.plist').read_bytes());p.validate_export(options)
                    dest=mobile/'build/ios/ipa';dest.mkdir(parents=True)
                    with zipfile.ZipFile(dest/'test.ipa','w') as z:
                        z.writestr('Payload/Runner.app/Info.plist',plistlib.dumps(INFO))
                        z.writestr('Payload/Runner.app/embedded.mobileprovision',PROFILE_BYTES)
                        z.writestr('Payload/Runner.app/Runner',b'fake executable')
                    if mutation=='export':(private/'export.plist').write_bytes(b'changed')
                if label=='extract_certificate':(private/'leaf0').write_bytes(b'other' if mutation=='certificate' else CERT)
                if label=='upload_ipa':
                    self.assertEqual(argv,['/usr/bin/xcrun','altool','--upload-app','--type','ios','--file',ipa,
                        '--apiKey',PINS['asc_key_id'],'--apiIssuer',PINS['asc_issuer_id']])
                    self.assertNotIn('CANARY',str(argv));self.assertEqual(kwargs['cwd'],private)
                    self.assertTrue((private/'private_keys'/('AuthKey_'+PINS['asc_key_id']+'.p8')).is_file())
                return outputs.get(label,'')
            fake_secrets={q.SIGNING_SECRETS[0]:base64.b64encode(b'synthetic-p12').decode(),
                          q.SIGNING_SECRETS[1]:'CANARY_PASSWORD',q.SIGNING_SECRETS[2]:base64.b64encode(PROFILE_BYTES).decode()}
            with mock.patch.multiple(s,ROOT=root,WORK=work,PRIVATE=private,IPA=ipa,RECEIPT=receipt), \
                 mock.patch.object(s,'runner',return_value=run),mock.patch.object(s,'cleanup_runner',return_value=run), \
                 mock.patch.object(s.secrets,'token_hex',return_value='synthetic-password'), \
                 mock.patch.dict(s.os.environ,{'GITHUB_SHA':'a'*40},clear=True),mock.patch('builtins.print') as printed:
                if not uploading:
                    if failure or mutation:
                        with self.assertRaises((RuntimeError,p.PolicyError)):s.compile_internal(PINS,'17',ctx,fake_secrets)
                        self.assertFalse(receipt.exists())
                    else:
                        s.compile_internal(PINS,'17',ctx,fake_secrets)
                        self.assertEqual(calls,commands);self.assertTrue(ipa.exists())
                        result=json.loads(receipt.read_text());s.validate_receipt(result,PINS,'17','a'*40)
                        for key in result:
                            altered=copy.deepcopy(result);altered[key]='CANARY'
                            with self.subTest(receipt_key=key),self.assertRaises(p.PolicyError):s.validate_receipt(altered,PINS,'17','a'*40)
                else:
                    private.mkdir();ipa.parent.mkdir();ipa.write_bytes(b'fake ipa')
                    result={'status':'VERIFIED_INTERNAL_IPA','source_commit':'a'*40,'build_number':'17','bundle_identifier':p.BUNDLE,
                        'team':p.TEAM,'asc_app_id':p.ASC_APP_ID,'sha256':s.sha(ipa.read_bytes()),'export_options_sha256':'b'*64,
                        'pins_sha256':s.sha(json.dumps(PINS,sort_keys=True).encode()),'internal_only_export':True,
                        'mode':'fake','cleanup_verified':True,'runtime_voiceover':'NOT_RUN','apple_upload':False}
                    receipt.write_text(json.dumps(result))
                    fake_key=b'-----BEGIN '+b'PRIVATE KEY-----\nCANARY\n-----END '+b'PRIVATE KEY-----'
                    if mutation=='ipa':ipa.write_bytes(b'tampered')
                    if mutation=='receipt':receipt.write_text(json.dumps({**result,'internal_only_export':False}))
                    if failure or mutation:
                        with self.assertRaises((RuntimeError,p.PolicyError)):s.upload(PINS,'17',{q.UPLOAD_SECRETS[0]:base64.b64encode(fake_key).decode()})
                    else:
                        s.upload(PINS,'17',{q.UPLOAD_SECRETS[0]:base64.b64encode(fake_key).decode()})
                        self.assertEqual(calls,['source_commit','source_clean','xcode_version','upload_ipa'])
                        with self.assertRaisesRegex(p.PolicyError,'signed_upload_ambiguous'):
                            s.upload(PINS,'17',{})
                    self.assertFalse(list((private/'private_keys').glob('*.p8')))
                self.assertNotIn('CANARY',str(printed.call_args_list))
                self.assertFalse((private/'distribution.p12').exists())
                self.assertFalse((private/'profile.mobileprovision').exists())
                if failure not in {'keychain_restore','keychain_delete'}:
                    self.assertFalse((private/'search-list.json').exists())
                    self.assertFalse((private/'distribution.keychain-db').exists())

    def test_success_and_each_build_command_failure(self):
        stages=['profile_decode','keychain_list','keychain_create','keychain_unlock','keychain_import','keychain_access',
            'keychain_select','signing_identity','ios_config','build_settings','build_ipa','verify_signature','read_entitlements',
            'read_profile','extract_certificate','architecture','source_clean','keychain_restore','keychain_delete']
        for stage in [None,*stages]:
            with self.subTest(stage=stage):self.exercise(failure=stage)

    def test_signed_payload_mutations(self):
        for mutation in ('profile','identity','settings','export','certificate'):
            with self.subTest(mutation=mutation):self.exercise(mutation=mutation)

    def test_upload_lifecycle_and_negatives(self):
        for stage in [None,'source_commit','source_clean','xcode_version','upload_ipa']:
            with self.subTest(stage=stage):self.exercise(failure=stage,uploading=True)
        for mutation in ('ipa','receipt'):
            with self.subTest(mutation=mutation):self.exercise(mutation=mutation,uploading=True)

    def test_bounded_diagnostics_canary_and_environment(self):
        env={'PATH':'/usr/bin','HOME':'/tmp/fixture'}
        for phase in ('command','post_verification'):
            overlay=mock.Mock()
            if phase=='post_verification':overlay.verify.side_effect=[None,p.PolicyError('sdk_base_changed')]
            with mock.patch.object(g,'resource_guard'),mock.patch.object(g,'run_bounded') as bounded,mock.patch('builtins.print') as printed:
                if phase=='command':bounded.side_effect=RuntimeError('CANARY_PRIVATE_OUTPUT')
                else:bounded.return_value=subprocess.CompletedProcess([],0,'CANARY_STDOUT','CANARY_STDERR')
                with self.assertRaises((RuntimeError,p.PolicyError)):
                    s.runner(env,g.time.monotonic()+60,overlay)('keychain_import',['/usr/bin/security','synthetic','CANARY_ARGUMENT'])
                row=json.loads(printed.call_args.args[0]);self.assertNotIn('CANARY',str(printed.call_args_list))
                self.assertEqual(row['verification_phase'],phase)
                self.assertEqual(row['command_outcome'],'PASS' if phase=='post_verification' else 'FAILED')
                self.assertEqual(bounded.call_args.kwargs['env'],env)
                self.assertIs(bounded.call_args.kwargs['group_observer'],g.groups.capture)
                self.assertTrue(bounded.call_args.kwargs['check'])

    def test_cleanup_not_blocked_by_sdk_disk_or_original_deadline(self):
        with mock.patch.object(g,'resource_guard',side_effect=AssertionError('must not use build resource guard')), \
             mock.patch.object(g,'run_bounded',return_value=subprocess.CompletedProcess([],0,'','')) as bounded, \
             mock.patch('builtins.print'):
            run=s.cleanup_runner();run('keychain_delete',['/usr/bin/security','delete-keychain','/synthetic'])
            self.assertLessEqual(bounded.call_args.kwargs['seconds'],25)
            with self.assertRaises(p.PolicyError):run('upload_ipa',['/usr/bin/xcrun','altool'])


if __name__=='__main__':unittest.main()
