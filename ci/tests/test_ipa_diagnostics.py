"""Synthetic output and metadata-only paths; never use Apple credentials."""
import ctypes
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock
from scripts import ipa_diagnostics as ipa,ci_process as cp
from ci.github import signing_discovery as homes,internal_testflight as signed,mac_unsigned as g
from ci.testflight import policy as p

SAMPLES={
    'PROFILE_NOT_FOUND':b"Error (Xcode): No profiles for 'CANARY_BUNDLE' were found",
    'PROFILE_MISMATCH':b'Provisioning profile CANARY does not include signing certificate CANARY',
    'IDENTITY_MISSING':b'No signing certificate "CANARY" found',
    'SIGNING_ACCESS':b'User interaction is not allowed.',
    'SIGNING_OPERATION':b'CANARY: errSecInternalComponent',
    'TRUST_CHAIN':b'Warning: unable to build chain to self-signed root for signer CANARY',
    'SCRIPT_FAILED':b'Command PhaseScriptExecution failed with a nonzero exit code',
    'COMPILE_FAILED':b'Swift Compiler Error (Xcode): CANARY',
    'SETTINGS_MISSING':b'No Xcode build settings have been found. CANARY',
    'DESTINATION_UNAVAILABLE':b'Unable to find a destination matching CANARY',
    'SIGNING_CONFLICT':b'Runner has conflicting provisioning settings CANARY',
    'PROFILE_UNSUPPORTED_TARGET':b'CANARY does not support provisioning profiles',
    'FLUTTER_CODESIGN_FAILED':b'Failed to codesign CANARY',
    'BUNDLE_FORMAT_INVALID':b'bundle format unrecognized CANARY',
    'SIGNING_REQUIRED':b'Runner requires a development team CANARY',
    'ACCOUNT_REQUIRED':b'No Accounts: CANARY',
    'PROFILE_TYPE':b'Provisioning profile CANARY is not a store profile',
    'ENTITLEMENTS_MISMATCH':b'unsupported entitlement CANARY',
    'CERTIFICATE_INVALID':b'Signing certificate CANARY is invalid',
    'RESOURCE_FORK':b'resource fork, Finder information CANARY',
    'BUILD_INPUT_MISSING':b'Build input file cannot be found CANARY',
    'LINKER_FAILED':b'Undefined symbols for architecture CANARY',
    'DUPLICATE_OUTPUT':b'Multiple commands produce CANARY',
    'SCRIPT_SANDBOX':b'Sandbox: CANARY deny(1)',
    'XCODE_LICENSE':b'You have not agreed to the Xcode license CANARY',
    'ARCHIVE_FAILED':b'** ARCHIVE FAILED **',
    'EXPORT_FAILED':b'error: exportArchive CANARY',
}


class IPAOutput(unittest.TestCase):
    def test_error_topics_are_finite_and_ignore_captured_unknown_values(self):
        result=ipa.classify(b'Error (Xcode): CANARY signing configuration file',True)
        self.assertEqual(result['error_topics'],['CONFIGURATION','FILE','SIGNING'])
        self.assertNotIn('CANARY',json.dumps(result))
        self.assertEqual(ipa.classify(b'CANARY signing configuration file',True)['error_topics'],[])
        self.assertEqual(ipa.project({**ipa.empty(),'error_topics':['CANARY']})['status'],'CLASSIFIER_FAILED')
    def test_each_category_and_combined_milestones_never_return_values(self):
        self.assertEqual(set(SAMPLES),set(ipa.PATTERNS))
        for name,sample in SAMPLES.items():
            with self.subTest(name=name):
                result=ipa.classify(sample,True);self.assertEqual(result['categories'],[name])
                self.assertEqual(ipa.reason(result),'build_ipa_'+name.lower())
                self.assertNotIn('CANARY',json.dumps(result))
        text=b'Archiving CANARY...\nRunning Xcode build...\nBuilt CANARY/Runner.xcarchive (1MB)\nBuilding App Store IPA...\nBuilt IPA to CANARY\n'+SAMPLES['PROFILE_NOT_FOUND']+b'\n'+SAMPLES['ARCHIVE_FAILED']
        result=ipa.classify(text,False);self.assertTrue(all(result['milestones'].values()))
        self.assertFalse(result['complete_output']);self.assertEqual(ipa.reason(result),'build_ipa_profile_not_found')
        self.assertNotIn('CANARY',json.dumps(result))

    def test_unknown_malformed_and_canary_projection_is_closed(self):
        for value in (b'',b'CANARY_UNKNOWN_ERROR',b'x'*2196,b'x'*5000+SAMPLES['PROFILE_NOT_FOUND']):
            self.assertEqual(ipa.classify(value,True)['status'],'UNCLASSIFIED')
        for value in (None,{}, {'status':[]},{**ipa.empty(),'extra':'CANARY'},
            {**ipa.empty(),'categories':['CANARY']},{**ipa.empty(),'complete_output':'CANARY'},
            {**ipa.empty(),'milestones':{'CANARY':True}},{**ipa.empty(),'status':'RECOGNIZED'}):
            result=ipa.project(value);self.assertEqual(result['status'],'CLASSIFIER_FAILED')
            self.assertNotIn('CANARY',json.dumps(result))

    def test_real_command_exit_success_failure_timeout_and_flood(self):
        payload=b'Archiving CANARY...\n'+SAMPLES['PROFILE_NOT_FOUND']+b'\n'
        for case in ('pass','fail','timeout','flood'):
            source='import os,time; os.write(2,'+repr(payload)+')'
            if case=='fail':source+='; raise SystemExit(1)'
            if case=='timeout':source+='; time.sleep(5)'
            detail={};kwargs={'cwd':Path.cwd(),'check':True,'output_profile':ipa.PROFILE,'diagnostic':detail,
                'seconds':.2 if case=='timeout' else 5,'maximum':8 if case=='flood' else 4096}
            with self.subTest(case=case):
                if case=='pass':cp.run_bounded([sys.executable,'-c',source],**kwargs)
                else:
                    with self.assertRaises((RuntimeError,TimeoutError)):cp.run_bounded([sys.executable,'-c',source],**kwargs)
                self.assertEqual(detail['failure_kind'],{'pass':'NONE','fail':'NONZERO_EXIT','timeout':'TIMEOUT','flood':'OUTPUT_BOUND'}[case])
                self.assertEqual(detail['ipa_summary']['complete_output'],case in ('pass','fail'))
                self.assertNotIn('CANARY',json.dumps(detail))

    def test_classifier_error_and_cleanup_error_do_not_authorize_success(self):
        actual=cp.cleanup_process
        for case in ('classifier','cleanup'):
            detail={}
            def cleanup(*args):return actual(*args)+[{'operation':'signal_term','type':'PermissionError','errno':1}]
            with mock.patch.object(ipa,'classify',side_effect=ValueError('CANARY') if case=='classifier' else None,return_value=ipa.empty()), \
                 mock.patch.object(cp,'cleanup_process',cleanup if case=='cleanup' else actual),self.assertRaises(RuntimeError):
                cp.run_bounded([sys.executable,'-c','raise SystemExit(1)'],cwd=Path.cwd(),check=True,diagnostic=detail,output_profile=ipa.PROFILE)
            self.assertEqual(detail['cleanup_failed'],case=='cleanup');self.assertNotIn('CANARY',json.dumps(detail))
            if case=='classifier':self.assertEqual(detail['ipa_summary']['status'],'CLASSIFIER_FAILED')

    def test_github_preserves_process_and_postverification_failures(self):
        for case in ('nonzero','post','cleanup'):
            overlay=mock.Mock()
            if case=='post':overlay.verify.side_effect=[None,p.PolicyError('sdk_base_changed')]
            def bounded(*args,**kwargs):
                self.assertEqual(kwargs['output_profile'],ipa.PROFILE);self.assertTrue(kwargs['check'])
                self.assertIs(kwargs['group_observer'],g.groups.capture)
                kwargs['diagnostic'].update(failure_kind='NONZERO_EXIT' if case=='nonzero' else 'CLEANUP' if case=='cleanup' else 'NONE',
                    exit_code=1 if case=='nonzero' else 0,cleanup_failed=case=='cleanup',ipa_summary=ipa.classify(SAMPLES['PROFILE_NOT_FOUND'],True))
                if case!='post':raise RuntimeError('CANARY')
                return mock.Mock(stdout='CANARY')
            with mock.patch.object(g,'resource_guard'),mock.patch.object(g,'run_bounded',bounded),mock.patch('builtins.print') as printed,self.assertRaises((p.PolicyError,RuntimeError)):
                signed.runner({},time.monotonic()+10,overlay)('build_ipa',['flutter','build','ipa'])
            row=json.loads(printed.call_args.args[0]);self.assertNotIn('CANARY',str(printed.call_args_list))
            self.assertEqual(row['cleanup_failed'],case=='cleanup')
            self.assertEqual(row['verification_phase'],'post_verification' if case=='post' else 'command')
            self.assertEqual(row['safe_reason'],'build_ipa_profile_not_found' if case=='nonzero' else 'sdk_base_changed' if case=='post' else 'OTHER')


class Discovery(unittest.TestCase):
    def test_different_or_same_foundation_home_and_profile_presence_without_contents(self):
        with tempfile.TemporaryDirectory(prefix='CANARY_HOME_') as tmp:
            root=Path(tmp).resolve();isolated=root/'.ci-github/home';native=root/'native';uuid='public-uuid'
            for home in (isolated,native):
                d=home/homes.PROFILE_DIRS[1];d.mkdir(parents=True);(d/(uuid+'.mobileprovision')).write_text('CANARY_PROFILE_CONTENT')
            with mock.patch.object(Path,'read_bytes',side_effect=AssertionError('content read')),mock.patch.object(Path,'read_text',side_effect=AssertionError('content read')):
                for home in (isolated,native):
                    result=homes.observe(root,str(isolated),uuid,lambda:home)
                    self.assertEqual(result['foundation_home_matches_isolated'],home==isolated)
                    self.assertTrue(result['isolated_xcode_profile_present']);self.assertFalse(result['isolated_legacy_profile_present'])
                    self.assertTrue(result['foundation_xcode_profile_present']);self.assertNotIn('CANARY',json.dumps(result))
                path=native/homes.PROFILE_DIRS[1]/(uuid+'.mobileprovision');path.unlink();path.symlink_to(root/'missing')
                self.assertFalse(homes.observe(root,str(isolated),uuid,lambda:native)['foundation_xcode_profile_present'])

    def test_unavailable_and_malformed_projections_expose_no_values(self):
        result=homes.observe(Path('/CANARY'),'/CANARY_HOME','public',mock.Mock(side_effect=OSError('CANARY')))
        self.assertEqual(result['status'],'UNAVAILABLE');self.assertIsNone(result['foundation_home_matches_isolated'])
        for value in (None,{},dict(result,unexpected='CANARY'),dict(result,foundation_home_matches_isolated='CANARY')):
            self.assertNotIn('CANARY',json.dumps(homes.project(value)))
        with mock.patch.object(homes.sys,'platform','linux'),mock.patch.object(homes.ctypes,'CDLL') as library:
            self.assertIsNone(homes.foundation_home());library.assert_not_called()

    def test_foundation_native_bridge_uses_only_home_query(self):
        foundation=mock.Mock();foundation.NSHomeDirectory.return_value=123
        cf=mock.Mock()
        def convert(pointer,buffer,size,encoding):buffer.value=b'/CANARY_NATIVE_HOME';return True
        cf.CFStringGetCString.side_effect=convert
        with mock.patch.object(homes.sys,'platform','darwin'),mock.patch.object(homes.ctypes,'CDLL',side_effect=[foundation,cf]) as libraries:
            self.assertEqual(homes.foundation_home(),Path('/CANARY_NATIVE_HOME'))
            self.assertEqual([c.args[0] for c in libraries.call_args_list],['/System/Library/Frameworks/Foundation.framework/Foundation','/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation'])
            foundation.NSHomeDirectory.assert_called_once_with()
            self.assertEqual(cf.CFStringGetCString.call_args.args[3],0x08000100)

    def test_owned_artifact_presence_is_boolean_bounded_and_reads_no_contents(self):
        with tempfile.TemporaryDirectory(prefix='CANARY_') as tmp:
            root=Path(tmp);mobile=root/'mobile';work=root/'work'
            archive=mobile/'build/ios/archive/Runner.xcarchive';archive.mkdir(parents=True);(archive/'Info.plist').write_text('CANARY')
            bundle=work/'tmp/flutter_ios_build_temp_dirCANARY/temporary_xcresult_bundle';bundle.mkdir(parents=True)
            with mock.patch.object(Path,'read_bytes',side_effect=AssertionError('read')),mock.patch.object(Path,'read_text',side_effect=AssertionError('read')):
                result=homes.artifact_presence(mobile,work)
            self.assertTrue(result['archive_directory_present']);self.assertTrue(result['archive_info_present'])
            self.assertTrue(result['temporary_result_bundle_present']);self.assertFalse(result['ipa_directory_present'])
            self.assertNotIn('CANARY',json.dumps(result))
            with mock.patch.object(Path,'iterdir',return_value=iter([root/'unrelated']*129)):
                self.assertIsNone(homes.artifact_presence(mobile,work)['temporary_result_bundle_present'])
            (archive/'Info.plist').unlink();archive.rmdir();archive.symlink_to(root,target_is_directory=True)
            result=homes.artifact_presence(mobile,work)
            self.assertIsNone(result['archive_directory_present']);self.assertIsNone(result['archive_info_present'])
