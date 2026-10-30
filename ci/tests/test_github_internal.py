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
PROFILE_BYTES=b'\x30synthetic-provisioning-envelope'
PINS={'enabled':True,'certificate_sha256':hashlib.sha256(CERT).hexdigest(),
      'certificate_sha1':hashlib.sha1(CERT).hexdigest().upper(),
      'profile_sha256':hashlib.sha256(PROFILE_BYTES).hexdigest(),
      'profile_uuid':'12345678-1234-1234-1234-123456789abc','profile_name':q.PROFILE_NAME,
      'asc_key_id':'ABCDEF1234','asc_issuer_id':'12345678-1234-1234-1234-123456789abc'}
ENT={'application-identifier':p.TEAM+'.'+p.BUNDLE,'com.apple.developer.team-identifier':p.TEAM,
     'get-task-allow':False,'beta-reports-active':True}
PROFILE={'UUID':PINS['profile_uuid'],'Name':PINS['profile_name'],'TeamIdentifier':[p.TEAM],
         'ExpirationDate':datetime.datetime(2099,1,1),'Entitlements':ENT,'DeveloperCertificates':[CERT]}
INFO={'CFBundleIdentifier':p.BUNDLE,'CFBundleVersion':'17','DTPlatformName':'iphoneos','CFBundleExecutable':'Runner'}


def settings():
    return [{'target':'Runner','buildSettings':{'PRODUCT_BUNDLE_IDENTIFIER':p.BUNDLE,'DEVELOPMENT_TEAM':p.TEAM,
        'CONFIGURATION':'Release','PLATFORM_NAME':'iphoneos','CODE_SIGNING_ALLOWED':'YES','CODE_SIGNING_REQUIRED':'YES',
        'CODE_SIGN_STYLE':'Manual','CODE_SIGN_IDENTITY':'Apple Distribution','PROVISIONING_PROFILE_SPECIFIER':PINS['profile_uuid'],
        'DART_DEFINES':','.join(base64.b64encode(x.encode()).decode() for x in ['WAINEK_DEV_MODE=true','WAINEK_REPOSITORY=fake'])}}]


class Policy(unittest.TestCase):
    def test_disabled_before_credential_reads(self):
        pins={key:None for key in q.PIN_FIELDS};pins['enabled']=False
        class Unreadable(dict):
            def get(self,*args):raise AssertionError('environment read before activation')
            def __getitem__(self,key):raise AssertionError('credential read')
        with self.assertRaisesRegex(p.PolicyError,'signed_disabled'):s.preflight(Unreadable(),pins)
        for mode in ('--build','--upload'):
            with mock.patch.object(q,'PIN_FILE',mock.Mock(read_text=lambda:json.dumps(pins))), \
                 mock.patch.object(s,'compile_internal') as build,mock.patch.object(s,'upload') as upload,mock.patch('builtins.print') as out:
                self.assertEqual(s.main([mode]),1)
                self.assertEqual(json.loads(out.call_args.args[0])['safe_reason'],'signed_disabled')
                build.assert_not_called();upload.assert_not_called()

    def test_exact_public_pins_and_valid_format_substitution_rejected(self):
        expected={
            'enabled':True,
            'certificate_sha256':'82fcf7f974315bf4d5822233174dcb1ac925f9508ddf167de5070ba4f208e4d8',
            'certificate_sha1':'625B08B199BA85687150068537A43771638134CC',
            'profile_sha256':'75c4dc0f6141a0bf2083bf9ae382874fcaa67f131072ee14b924e0857bdb5c5b',
            'profile_uuid':'32354322-1461-4d95-90a6-9b62285e3a1a',
            'profile_name':'wainek_github_app_store_20261029',
            'asc_key_id':'9X6UGZYBYR','asc_issuer_id':'54a3742f-c62d-468e-a2ae-70e0d8aff797',
        }
        value=json.loads(q.PIN_FILE.read_text());self.assertEqual(value,expected)
        q.validate_reviewed_pins(value)
        for key in ('certificate_sha256','certificate_sha1','profile_sha256','profile_uuid','asc_key_id','asc_issuer_id'):
            replacement=('1' if value[key][0]!='1' else '2')+value[key][1:]
            changed={**value,key:replacement};q.validate_pins(changed,active=True)
            with self.subTest(key=key),self.assertRaisesRegex(p.PolicyError,'signed_pin_mismatch'):
                q.validate_reviewed_pins(changed)
        with self.assertRaises(p.PolicyError):q.validate_reviewed_pins({**value,'profile_uuid':value['profile_uuid'].upper()})
        self.assertEqual(p.PROFILE,'wainek_app_store')
        self.assertEqual(p.CERTIFICATE,'nextaura_apple_distribution')

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

    def test_signed_preflight_rejects_wrong_trigger_source_and_host_without_secrets(self):
        class Guarded(dict):
            def __getitem__(self,key):
                if key in (*q.SIGNING_SECRETS,*q.UPLOAD_SECRETS):raise AssertionError('secret read')
                return super().__getitem__(key)
        env=Guarded({'WAINEK_SIGNED_TARGET':'mac-internal','WAINEK_SIGNED_ENVIRONMENT':q.ENVIRONMENT,
            'GITHUB_RUN_ATTEMPT':'1','WAINEK_EXPECTED_SHA':'a'*40,'WAINEK_BUILD_NUMBER':'17',
            'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'dukkanai/wainak','GITHUB_EVENT_NAME':'workflow_dispatch',
            'GITHUB_REF':'refs/heads/'+q.BRANCH,'GITHUB_SHA':'a'*40,'GITHUB_WORKSPACE':str(s.ROOT),
            'RUNNER_ENVIRONMENT':'github-hosted','RUNNER_OS':'macOS','RUNNER_ARCH':'ARM64',
            'WAINEK_REPOSITORY_VISIBILITY':'public','WAINEK_RUNNER_LABEL':'macos-26'})
        with mock.patch.object(s.sys,'platform','darwin'),mock.patch.object(s.platform,'machine',return_value='arm64'), \
             mock.patch.object(g.shutil,'disk_usage',return_value=mock.Mock(free=12*g.GIB)):
            self.assertEqual(s.preflight(env,q.REVIEWED_PINS),'17')
            for key,value in [('GITHUB_REPOSITORY','fork/wainak'),('GITHUB_EVENT_NAME','pull_request'),
                              ('GITHUB_EVENT_NAME','pull_request_target'),('GITHUB_EVENT_NAME','push'),
                              ('GITHUB_REF','refs/heads/main'),('GITHUB_RUN_ATTEMPT','2'),
                              ('WAINEK_EXPECTED_SHA','b'*40),('WAINEK_BUILD_NUMBER','17; CANARY'),
                              ('WAINEK_REPOSITORY_VISIBILITY','private'),('WAINEK_RUNNER_LABEL','macos-26-large')]:
                with self.subTest(key=key,value=value),self.assertRaises(p.PolicyError):
                    s.preflight(Guarded({**env,key:value}),q.REVIEWED_PINS)
        with mock.patch.object(s.sys,'platform','linux'),mock.patch.object(g.shutil,'disk_usage',return_value=mock.Mock(free=12*g.GIB)):
            with self.assertRaisesRegex(p.PolicyError,'github_standard_arm_mac'):s.preflight(env,q.REVIEWED_PINS)

    def test_active_entrypoint_routes_only_after_contract_checks(self):
        for mode in ('--check','--build','--upload'):
            with self.subTest(mode=mode),mock.patch.object(s,'preflight',return_value='17'), \
                 mock.patch.object(g,'execute',return_value={'fixture':'context'}) as unsigned, \
                 mock.patch.object(s,'compile_internal') as compile_,mock.patch.object(s,'upload') as upload, \
                 mock.patch('builtins.print') as printed:
                self.assertEqual(s.main([mode]),0)
                self.assertEqual(unsigned.call_count,int(mode=='--build'))
                self.assertEqual(compile_.call_count,int(mode=='--build'))
                self.assertEqual(upload.call_count,int(mode=='--upload'))
                self.assertNotIn('CANARY',str(printed.call_args_list))
        for error in ('signed_pin_mismatch','signed_active_workflow'):
            target='validate_reviewed_pins' if error=='signed_pin_mismatch' else 'validate_active_workflow'
            with mock.patch.object(q,target,side_effect=p.PolicyError(error)), \
                 mock.patch.object(g,'execute') as unsigned,mock.patch.object(s,'upload') as upload, \
                 mock.patch('builtins.print') as printed:
                self.assertEqual(s.main(['--build']),1);self.assertEqual(s.main(['--upload']),1)
                unsigned.assert_not_called();upload.assert_not_called()
                self.assertEqual(json.loads(printed.call_args.args[0])['safe_reason'],error)

    def test_cleanup_entrypoint_survives_invalid_pins_with_host_guard_intact(self):
        with mock.patch.object(q,'PIN_FILE',mock.Mock(read_text=mock.Mock(side_effect=AssertionError('pins must not block cleanup')))), \
             mock.patch.object(s.sys,'platform','darwin'), \
             mock.patch.dict(s.os.environ,{'GITHUB_REPOSITORY':'dukkanai/wainak','GITHUB_WORKSPACE':str(s.ROOT)},clear=True), \
             mock.patch.object(s,'cleanup') as cleanup,mock.patch.object(s,'cleanup_runner'),mock.patch('builtins.print'):
            self.assertEqual(s.main(['--cleanup']),0);cleanup.assert_called_once()
            cleanup.reset_mock()
            with mock.patch.object(s.sys,'platform','linux'):
                self.assertEqual(s.main(['--cleanup']),1);cleanup.assert_not_called()
            with mock.patch.object(s,'cleanup',side_effect=p.PolicyError('signed_cleanup')):
                self.assertEqual(s.main(['--cleanup']),1)

    def test_environment_protections(self):
        env={'name':q.ENVIRONMENT,'can_admins_bypass':False,
             'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True},
             'protection_rules':[{'type':'required_reviewers','prevent_self_review':False,
                                 'reviewers':[{'type':'User','reviewer':{'id':q.OWNER_ID,'login':q.OWNER_LOGIN}}]}]}
        branches=[{'name':q.BRANCH,'type':'branch'}];q.validate_environment(env,branches)
        for key,value in [('can_admins_bypass',True),('protection_rules',[]),('deployment_branch_policy',None),('name','other')]:
            with self.assertRaises(p.PolicyError):q.validate_environment({**env,key:value},branches)
        for rules in ([],[{'name':'*','type':'branch'}],[{'name':q.BRANCH,'type':'tag'}],branches*2):
            with self.assertRaises(p.PolicyError):q.validate_environment(env,rules)
        for field,value in [('prevent_self_review',True),('prevent_self_review',0),('reviewers',[])]:
            changed=copy.deepcopy(env);changed['protection_rules'][0][field]=value
            with self.assertRaises(p.PolicyError):q.validate_environment(changed,branches)
        for reviewer in [
            {'type':'Team','reviewer':{'id':q.OWNER_ID,'login':q.OWNER_LOGIN}},
            {'type':'User','reviewer':{'id':123,'login':q.OWNER_LOGIN}},
            {'type':'User','reviewer':{'id':q.OWNER_ID,'login':'other'}},
        ]:
            changed=copy.deepcopy(env);changed['protection_rules'][0]['reviewers']=[reviewer]
            with self.assertRaises(p.PolicyError):q.validate_environment(changed,branches)
        changed=copy.deepcopy(env);changed['protection_rules'][0]['reviewers']*=2
        with self.assertRaises(p.PolicyError):q.validate_environment(changed,branches)

    def test_active_workflow_exact_and_mutations(self):
        job=json.loads((q.ROOT/'ci/github/internal-testflight.job.json').read_text());q.validate_job(job)
        source=(q.ROOT/'.github/workflows/ci.yml').read_text()
        candidate=(q.ROOT/'ci/github/internal-testflight.workflow.candidate').read_text()
        self.assertEqual(source,candidate);q.validate_active_workflow(source)
        self.assertIn('options: [ci, mac-unsigned, mac-internal]',source)
        self.assertEqual(source.count("if: ${{ inputs.target != 'mac-unsigned' && inputs.target != 'mac-internal' }}"),9)
        self.assertIn("cancel-in-progress: ${{ inputs.target != 'mac-internal' }}",source)
        for changed in (source.replace('branches: [main]','branches: [main, dev]'),
                        source.replace('  pull_request:', '  pull_request_target:'),
                        source.replace('contents: read','contents: write'),
                        source.replace('options: [ci, mac-unsigned, mac-internal]','options: [mac-internal]'),
                        source.replace("inputs.target != 'mac-internal'",'true'),
                        source.replace('wainek-internal-testflight','other-environment')):
            with self.assertRaisesRegex(p.PolicyError,'signed_active_workflow'):q.validate_active_workflow(changed)
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
        cases={'Name':p.PROFILE,'UUID':PINS['profile_uuid'].upper(),'TeamIdentifier':['wrong'],'DeveloperCertificates':[b'other'],
               'ProvisionedDevices':[],'ExpirationDate':datetime.datetime(2000,1,1)}
        for key,value in cases.items():
            with self.subTest(key=key),self.assertRaises(p.PolicyError):s.profile_check({**PROFILE,key:value},PINS,'17')
        with self.assertRaises(p.PolicyError):s.profile_check(PROFILE,{**PINS,'certificate_sha1':'A'*40},'17')
        for certificates in ([CERT,CERT],[CERT,b'other'],[]):
            with self.assertRaisesRegex(p.PolicyError,'signed_certificate'):
                s.profile_check({**PROFILE,'DeveloperCertificates':certificates},PINS,'17')
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


class CMSInput(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='cms paths with spaces ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.work=self.root/'.ci-github'
        self.private=self.work/'signing';self.private.mkdir(parents=True)
        patch=mock.patch.multiple(s,ROOT=self.root,WORK=self.work,PRIVATE=self.private)
        patch.start();self.addCleanup(patch.stop)
        self.path=self.private/'profile.mobileprovision';self.path.write_bytes(PROFILE_BYTES)
        self.keychain=self.private/'distribution.keychain-db';self.keychain.write_bytes(b'synthetic-keychain')
        self.run=mock.Mock(return_value=plistlib.dumps(PROFILE).decode())

    def decode(self,**overrides):
        return s.decode_profile(self.run,overrides.get('label','profile_decode'),
            overrides.get('path',self.path),overrides.get('keychain',self.keychain),overrides.get('pins',PINS))

    def test_absolute_paths_spaces_explicit_keychain_and_cwd(self):
        # No real security process: argv is checked exactly, with no shell or
        # option that disables CMS signature/trust processing.
        with mock.patch('builtins.print') as printed:
            for label in ('profile_decode','read_profile'):
                self.assertEqual(self.decode(label=label),PROFILE)
                self.run.assert_called_with(label,['/usr/bin/security','cms','-D','-k',self.keychain,'-i',self.path],cwd=self.root)
                row=json.loads(printed.call_args.args[0])
                self.assertEqual(row,{'event':'GITHUB_CMS_INPUT','role':label,'absolute_path':True,
                    'regular_profile':True,'profile_bytes':len(PROFILE_BYTES),'pinned_hash_match':True,
                    'format':'PINNED_DER','explicit_owned_keychain':True,'cwd':'CHECKOUT_ROOT'})
            self.assertNotIn(str(self.root),str(printed.call_args_list))

    def test_relative_outside_directory_and_symlink_profiles_rejected_before_command(self):
        outside=self.root/'outside';outside.write_bytes(PROFILE_BYTES)
        link=self.private/'link';link.symlink_to(self.path)
        parent=self.work/'alias';parent.symlink_to(self.private,target_is_directory=True)
        for path,reason in [(Path('profile.mobileprovision'),'signed_cms_input'),
                            (outside,'signed_path'),(self.private,'signed_path'),
                            (link,'signed_path'),(parent/self.path.name,'signed_path')]:
            with self.subTest(path=path.name),self.assertRaisesRegex(p.PolicyError,reason):self.decode(path=path)
        self.run.assert_not_called()

    def test_keychain_missing_wrong_location_directory_or_symlink_rejected(self):
        other=self.private/'other.keychain-db';other.write_bytes(b'synthetic')
        for keychain in (Path(self.keychain.name),other,self.private):
            with self.subTest(path=keychain.name),self.assertRaisesRegex(p.PolicyError,'signed_cms_keychain'):
                self.decode(keychain=keychain)
        self.keychain.unlink()
        with self.assertRaisesRegex(p.PolicyError,'signed_cms_keychain'):self.decode()
        self.keychain.symlink_to(other)
        with self.assertRaisesRegex(p.PolicyError,'signed_cms_keychain'):self.decode()
        self.run.assert_not_called()

    def test_input_hash_and_format_rejected_before_command(self):
        self.path.write_bytes(b'changed')
        with self.assertRaisesRegex(p.PolicyError,'signed_profile_hash'):self.decode()
        # Even a pinned text envelope is not accepted as the reviewed DER input.
        with self.assertRaisesRegex(p.PolicyError,'signed_cms_input'):
            self.decode(pins={**PINS,'profile_sha256':s.sha(b'changed')})
        with self.assertRaisesRegex(p.PolicyError,'signed_cms_input'):self.decode(label='unexpected')
        self.run.assert_not_called()

    def test_post_command_hash_drift_and_symlink_rejected(self):
        for mutation in ('bytes','symlink'):
            with self.subTest(mutation=mutation),mock.patch('builtins.print'):
                def mutate(*args,**kwargs):
                    if mutation=='bytes':self.path.write_bytes(b'changed')
                    else:
                        other=self.private/'replacement';other.write_bytes(PROFILE_BYTES)
                        self.path.unlink();self.path.symlink_to(other)
                    return plistlib.dumps(PROFILE).decode()
                self.run.side_effect=mutate
                with self.assertRaisesRegex(p.PolicyError,'signed_profile_hash' if mutation=='bytes' else 'signed_path'):
                    self.decode()
                self.path.unlink();self.path.write_bytes(PROFILE_BYTES)

    def test_failed_cms_has_safe_reason_no_fallback_and_no_output_leak(self):
        for error in (RuntimeError('CANARY_CMS_TRUST_FAILURE'),RuntimeError('CANARY_TIMEOUT_OR_CLEANUP')):
            self.run.reset_mock();self.run.side_effect=error
            with mock.patch('builtins.print') as printed,self.assertRaisesRegex(p.PolicyError,'^signed_cms_command_failed$') as caught:
                self.decode()
            self.assertEqual(self.run.call_count,1)
            self.assertNotIn('CANARY',str(printed.call_args_list)+str(caught.exception))
            self.assertIn(str(caught.exception),q.REASONS)
        self.run.side_effect=p.PolicyError('sdk_base_changed')
        with mock.patch('builtins.print'),self.assertRaisesRegex(p.PolicyError,'sdk_base_changed'):self.decode()

    def test_successful_exit_without_plist_still_rejected(self):
        self.run.return_value='CANARY_INVALID_OUTPUT'
        with mock.patch('builtins.print') as printed,self.assertRaisesRegex(p.PolicyError,'missing_plist_output'):
            self.decode()
        self.assertNotIn('CANARY',str(printed.call_args_list))


class Lifecycle(unittest.TestCase):
    def exercise(self, failure=None, mutation=None, uploading=False,native_cleanup_failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();work=root/'.ci-github';work.mkdir(mode=0o700);(work/'home').mkdir(mode=0o700);(work/'tmp').mkdir(mode=0o700)
            private=work/'signing';ipa=work/'verified/wainek-internal.ipa';receipt=ipa.parent/'result.json'
            native_home=root/'native-home';native_home.mkdir(mode=0o700)
            mobile=root/'apps/mobile';mobile.mkdir(parents=True)
            overlay=mock.Mock();ctx={'env':{'PATH':'/safe/path','HOME':str(work/'home')},'deadline':9999999999,
                                    'overlay':overlay,'mobile':mobile}
            calls=[];failed=False;unlocked=False
            commands=['keychain_list','keychain_create','keychain_unlock','profile_decode','keychain_import','keychain_access',
                'keychain_select',*s.keychain_diagnostics.COMMANDS,'signing_identity','ios_config','build_settings','workspace_settings','signing_discovery',
                *s.keychain_diagnostics.COMMANDS,'build_ipa','verify_signature','read_entitlements',
                'read_profile','extract_certificate','architecture','source_clean','keychain_restore_readback','keychain_restore','keychain_restore_readback','keychain_delete']
            outputs={'profile_decode':plistlib.dumps(PROFILE).decode(),'keychain_list':'"/original/login.keychain-db"\n',
                'signing_identity':f'  1) {PINS["certificate_sha1"]} "Apple Distribution: NEXTAURA LLC ({p.TEAM})"\n 1 valid identities found\n',
                'build_settings':json.dumps(settings()),'workspace_settings':json.dumps(settings()),'read_entitlements':plistlib.dumps(ENT).decode(),
                'signing_discovery':json.dumps(s.signing_discovery.project(None)),
                'read_profile':plistlib.dumps(PROFILE).decode(),'architecture':'arm64','source_commit':'a'*40,
                'xcode_version':'Xcode 26.4.1\nBuild version 17E202\n'}
            if mutation=='profile':outputs['profile_decode']=plistlib.dumps({**PROFILE,'Name':'wrong'}).decode()
            if mutation=='identity':outputs['signing_identity']='0 valid identities found'
            if mutation=='settings':outputs['build_settings']=json.dumps([{'target':'Runner','buildSettings':{}}])
            if mutation=='settings_json':outputs['build_settings']='CANARY\n'+outputs['build_settings']
            if mutation=='settings_type':outputs['build_settings']='[null]'
            if mutation=='settings_defines_type':
                value=settings();value[0]['buildSettings']['DART_DEFINES']=[];outputs['build_settings']=json.dumps(value)
            keychain=private/'distribution.keychain-db';app=work/'signed-inspect/Payload/Runner.app'
            for label in s.keychain_diagnostics.COMMANDS:
                outputs[label]=(f'"{keychain}"\n"/original/login.keychain-db"\n' if label.startswith('keychain_search') else outputs['signing_identity'])
            expected_commands={
                **{label:list(command) for label,command in s.keychain_diagnostics.COMMANDS.items()},
                'profile_decode':['/usr/bin/security','cms','-D','-k',keychain,'-i',private/'profile.mobileprovision'],
                'keychain_list':['/usr/bin/security','list-keychains','-d','user'],
                'keychain_create':['/usr/bin/security','create-keychain','-p','synthetic-password',keychain],
                'keychain_unlock':['/usr/bin/security','unlock-keychain','-p','synthetic-password',keychain],
                'keychain_import':['/usr/bin/security','import',private/'distribution.p12','-k',keychain,'-P','CANARY_PASSWORD','-T','/usr/bin/codesign','-T','/usr/bin/security'],
                'keychain_access':['/usr/bin/security','set-key-partition-list','-S','apple-tool:,apple:,codesign:','-s','-k','synthetic-password',keychain],
                'keychain_select':['/usr/bin/security','list-keychains','-d','user','-s',keychain,'/original/login.keychain-db'],
                'keychain_restore':['/usr/bin/security','list-keychains','-d','user','-s','/original/login.keychain-db'],
                'keychain_restore_readback':['/usr/bin/security','list-keychains','-d','user'],
                'keychain_delete':['/usr/bin/security','delete-keychain',keychain],
                'signing_identity':['/usr/bin/security','find-identity','-v','-p','codesigning',keychain],
                'ios_config':['flutter','build','ios','--config-only','--release','--no-pub','--no-codesign','--build-number','17',*p.DEFINES],
                'build_settings':['/usr/bin/xcodebuild','-project',mobile/'ios/Runner.xcodeproj','-scheme','Runner','-configuration','Release','-sdk','iphoneos','-showBuildSettings','-json'],
                'workspace_settings':['/usr/bin/xcodebuild','-workspace',mobile/'ios/Runner.xcworkspace','-scheme','Runner','-configuration','Release','-sdk','iphoneos','-destination','generic/platform=iOS','-showBuildSettings','-json'],
                'signing_discovery':[s.sys.executable,root/'ci/github/signing_discovery.py'],
                'build_ipa':['flutter','build','ipa','--release','--no-pub','--build-number','17','--export-options-plist',private/'export.plist',*p.DEFINES],
                'verify_signature':['/usr/bin/codesign','--verify','--deep','--strict',app],
                'read_entitlements':['/usr/bin/codesign','-d','--entitlements',':-',app],
                'read_profile':['/usr/bin/security','cms','-D','-k',keychain,'-i',app/'embedded.mobileprovision'],
                'extract_certificate':['/usr/bin/codesign','-d','--extract-certificates',private/'leaf',app],
                'architecture':['/usr/bin/lipo','-archs',app/'Runner'],
                'source_clean':['git','status','--porcelain'],
                'source_commit':['git','rev-parse','HEAD'],
                'xcode_version':['/usr/bin/xcodebuild','-version'],
                'upload_ipa':['/usr/bin/xcrun','altool','--upload-app','--type','ios','--file',ipa,'--apiKey',PINS['asc_key_id'],'--apiIssuer',PINS['asc_issuer_id']],
            }
            self.assertEqual(set(expected_commands),s.LABELS)
            def run(label,argv,**kwargs):
                nonlocal failed,unlocked
                self.assertIn(label,s.LABELS,'unexpected command')
                self.assertEqual(argv,expected_commands[label],'unexpected argv')
                if label not in {'keychain_restore','keychain_delete','keychain_restore_readback'}:
                    self.assertFalse(failed,'continued after failure')
                    if not uploading:self.assertEqual(label,commands[len([x for x in calls if x not in {'keychain_restore','keychain_delete','keychain_restore_readback'}])])
                calls.append(label)
                if failure==label:failed=True;raise RuntimeError('CANARY_SECRET_OUTPUT')
                if label=='keychain_restore_readback':
                    return '"/original/login.keychain-db"\n' if 'keychain_restore' in calls else outputs['keychain_search_account']
                if label=='keychain_create':(private/'distribution.keychain-db').write_bytes(b'synthetic-keychain')
                if label=='keychain_unlock':
                    self.assertTrue(keychain.is_file());unlocked=True
                if label in {'profile_decode','read_profile'}:
                    self.assertTrue(unlocked,'CMS requires an unlocked owned keychain')
                    self.assertTrue(keychain.is_file());self.assertEqual(kwargs['cwd'],root)
                    self.assertTrue(argv[-1].is_absolute());self.assertTrue(argv[4].is_absolute())
                if label=='keychain_delete':(private/'distribution.keychain-db').unlink()
                if label=='keychain_import':
                    self.assertNotIn('-A',argv);self.assertIn('/usr/bin/codesign',argv)
                if label=='keychain_restore':self.assertEqual(argv,['/usr/bin/security','list-keychains','-d','user','-s','/original/login.keychain-db'])
                if label=='build_ipa':
                    s.profile_installation.verify(private,PINS)
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
            secret_reads=[]
            class SyntheticSecrets(dict):
                def __getitem__(self,key):secret_reads.append(key);return super().__getitem__(key)
            fake_secrets=SyntheticSecrets({q.SIGNING_SECRETS[0]:base64.b64encode(b'synthetic-p12').decode(),
                          q.SIGNING_SECRETS[1]:'CANARY_PASSWORD',q.SIGNING_SECRETS[2]:base64.b64encode(PROFILE_BYTES).decode()})
            native_cleanup=s.profile_installation.cleanup
            def clean_native(*args,**kwargs):
                if native_cleanup_failure:raise p.PolicyError('signed_native_cleanup')
                return native_cleanup(*args,**kwargs)
            with mock.patch.multiple(s,ROOT=root,WORK=work,PRIVATE=private,IPA=ipa,RECEIPT=receipt), \
                 mock.patch.object(s.profile_installation,'native_home',return_value=native_home), \
                 mock.patch.object(s.profile_installation,'cleanup',side_effect=clean_native), \
                 mock.patch.object(s,'runner',return_value=run) as runner_factory,mock.patch.object(s,'cleanup_runner',return_value=run), \
                 mock.patch.object(s.secrets,'token_hex',return_value='synthetic-password'), \
                 mock.patch.dict(s.os.environ,{'GITHUB_SHA':'a'*40},clear=True),mock.patch('builtins.print') as printed:
                if not uploading:
                    if failure or mutation or native_cleanup_failure:
                        with self.assertRaises((RuntimeError,p.PolicyError)):s.compile_internal(PINS,'17',ctx,fake_secrets)
                        self.assertFalse(receipt.exists())
                        if failure in {'keychain_list','keychain_create','keychain_unlock','profile_decode'} or mutation=='profile':
                            self.assertNotIn(q.SIGNING_SECRETS[0],secret_reads)
                            self.assertNotIn(q.SIGNING_SECRETS[1],secret_reads)
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
                    if mutation=='native_journal':(private/s.profile_installation.JOURNAL).write_text('{}')
                    if failure or mutation:
                        with self.assertRaises((RuntimeError,p.PolicyError)):s.upload(PINS,'17',{q.UPLOAD_SECRETS[0]:base64.b64encode(fake_key).decode()})
                    else:
                        s.upload(PINS,'17',{q.UPLOAD_SECRETS[0]:base64.b64encode(fake_key).decode()})
                        self.assertEqual(calls,['source_commit','source_clean','xcode_version','upload_ipa'])
                        with self.assertRaisesRegex(p.PolicyError,'signed_upload_ambiguous'):
                            s.upload(PINS,'17',{})
                    self.assertFalse(list((private/'private_keys').glob('*.p8')))
                self.assertNotIn('CANARY',str(printed.call_args_list))
                if not uploading:
                    self.assertEqual(runner_factory.call_args_list[0].args[0]['HOME'],str(native_home))
                    self.assertEqual(ctx['env']['HOME'],str(work/'home'))
                self.assertFalse((private/'distribution.p12').exists())
                self.assertEqual((private/'profile.mobileprovision').exists(),native_cleanup_failure)
                self.assertEqual((private/s.profile_installation.JOURNAL).exists(),native_cleanup_failure or mutation=='native_journal')
                if mutation=='native_journal':
                    self.assertNotIn('upload_ipa',calls);self.assertFalse((work/'upload-attempt.json').exists())
                    self.assertEqual(secret_reads,[])
                for relative in s.profile_installation.DIRECTORIES:
                    self.assertEqual((native_home/relative/(PINS['profile_uuid']+'.mobileprovision')).exists(),native_cleanup_failure)
                if failure not in {'keychain_restore','keychain_delete','keychain_restore_readback'}:
                    self.assertFalse((private/'search-list.json').exists())
                    self.assertFalse((private/'distribution.keychain-db').exists())

    def test_native_profile_cleanup_failure_blocks_receipt_and_keeps_recovery_source(self):
        self.exercise(native_cleanup_failure=True)

    def test_success_and_each_build_command_failure(self):
        stages=['profile_decode','keychain_list','keychain_create','keychain_unlock','keychain_import','keychain_access',
            'keychain_select',*s.keychain_diagnostics.COMMANDS,'signing_identity','ios_config','build_settings','workspace_settings','signing_discovery','build_ipa','verify_signature','read_entitlements',
            'read_profile','extract_certificate','architecture','source_clean','keychain_restore_readback','keychain_restore','keychain_delete']
        for stage in [None,*stages]:
            with self.subTest(stage=stage):self.exercise(failure=stage)

    def test_signed_payload_mutations(self):
        for mutation in ('profile','identity','settings','export','certificate'):
            with self.subTest(mutation=mutation):self.exercise(mutation=mutation)

    def test_upload_lifecycle_and_negatives(self):
        for stage in [None,'source_commit','source_clean','xcode_version','upload_ipa']:
            with self.subTest(stage=stage):self.exercise(failure=stage,uploading=True)
        for mutation in ('ipa','receipt','native_journal'):
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
