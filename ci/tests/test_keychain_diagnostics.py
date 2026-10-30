"""Synthetic observations and strict query routing; no Apple key access."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
from ci.github import keychain_diagnostics as k,internal_testflight as s,signing_settings as settings
from ci.tests.test_github_internal import PINS,settings as fixture_settings
from ci.testflight import policy as p
from scripts import ipa_diagnostics as ipa


class Projections(unittest.TestCase):
    def test_search_list_membership_count_and_exact_readback_without_paths(self):
        owned='/CANARY/owned.keychain-db';prior='/CANARY/other.keychain-db'
        result=k.search_list(f'  "{owned}"\n  "{prior}"\n',owned,[owned,prior])
        self.assertEqual(result,{'status':'OBSERVED','count':2,'owned_present':True,'matches_expected':True})
        self.assertFalse(k.search_list(f'"{prior}"',owned,[owned,prior])['owned_present'])
        self.assertEqual(k.search_list('',owned,[]),{'status':'OBSERVED','count':0,'owned_present':False,'matches_expected':True})
        self.assertNotIn('CANARY',json.dumps(result))

    def test_unknown_malformed_and_bounded_search_lists_never_echo(self):
        for value in (None,[], 'CANARY_WARNING', '"relative/CANARY"','"/CANARY"\n"/CANARY"','"/CANARY\x00"','x'*65537,'\n'.join('"/CANARY'+str(i)+'"' for i in range(33))):
            result=k.search_list(value,'/owned',[])
            self.assertEqual(result['status'],'UNCLASSIFIED');self.assertNotIn('CANARY',json.dumps(result))

    def test_implicit_pinned_identity_and_other_identity_are_boolean_only(self):
        pin=PINS['certificate_sha1'];other='F'*40
        text=f' 1) {pin} "CANARY_NAME"\n 2) {other} "CANARY_OTHER"\n 2 valid identities found\n'
        result=k.identities(text,pin)
        self.assertEqual(result,{'status':'OBSERVED','count':2,'pinned_present':True})
        self.assertEqual(k.identities('0 valid identities found',pin),{'status':'OBSERVED','count':0,'pinned_present':False})
        self.assertNotIn('CANARY',json.dumps(result));self.assertNotIn(other,json.dumps(result))

    def test_identity_unknown_and_inconsistent_results_are_unclassified(self):
        pin=PINS['certificate_sha1']
        for value in (None,'CANARY',f'1) {pin} "CANARY"\n0 valid identities found',
                      f'2) {pin} "CANARY"\n1 valid identities found',f'1) {pin} "CANARY"\n1 valid identities found\nCANARY',
                      f'1) {pin} "CANARY"\n2) {pin} "CANARY"\n2 valid identities found','x'*65537):
            self.assertEqual(k.identities(value,pin)['status'],'UNCLASSIFIED')

    def test_malformed_projection_and_canary_never_reach_json(self):
        for query in ('SEARCH_LIST','IDENTITIES'):
            for result in (None,{}, {'status':'CANARY'}, {'status':'OBSERVED','count':True,'pinned_present':'CANARY'},
                           {'status':'OBSERVED','count':100000,'pinned_present':True}):
                with mock.patch('builtins.print') as printed:k.emit('AFTER_SELECT','ACCOUNT',query,result)
                row=json.loads(printed.call_args.args[0]);self.assertEqual(row['status'],'UNCLASSIFIED')
                self.assertNotIn('CANARY',str(printed.call_args_list))

    def test_workspace_expanded_identity_classification_and_original_policy(self):
        for value,expected in ((None,'MISSING'),('','EMPTY'),(PINS['certificate_sha1'],'REVIEWED_PIN'),('F'*40,'OTHER'),('CANARY','OTHER'),([], 'WRONG_TYPE')):
            data=fixture_settings()
            if value is not None:data[0]['buildSettings']['EXPANDED_CODE_SIGN_IDENTITY']=value
            with mock.patch('builtins.print') as printed:settings.validate(json.dumps(data),PINS,scope='WORKSPACE')
            row=json.loads(printed.call_args.args[0]);self.assertEqual(row['scope'],'WORKSPACE')
            self.assertEqual(row['public_settings']['EXPANDED_CODE_SIGN_IDENTITY'],expected)
            self.assertNotIn('CANARY',str(printed.call_args_list));self.assertNotIn('F'*40,str(printed.call_args_list))
        data[0]['buildSettings']['DEVELOPMENT_TEAM']='CANARY'
        with mock.patch('builtins.print'),self.assertRaises(p.PolicyError):settings.validate(json.dumps(data),PINS,scope='WORKSPACE')

    def test_certificate_type_and_target_are_finite_and_never_captured_values(self):
        for name,category in (*ipa.CERTIFICATE_NAMES.items(),(b'CANARY_CERT','OTHER')):
            for target,kind in ((b'Runner','RUNNER'),(b'RunnerTests','RUNNER_TESTS'),(b'CANARY_TARGET','OTHER')):
                text=b'No signing certificate "'+name+b'" found (in target \''+target+b'\' from project \'CANARY_PROJECT\')'
                result=ipa.classify(text,True)
                self.assertEqual(result['requested_certificate_types'],[category]);self.assertEqual(result['failure_targets'],[kind])
                self.assertNotIn('CANARY',json.dumps(result))
        for field in ('requested_certificate_types','failure_targets'):
            self.assertEqual(ipa.project({**ipa.empty(),field:['CANARY']})['status'],'CLASSIFIER_FAILED')
        self.assertEqual(ipa.classify(b'CANARY UNKNOWN',True)['requested_certificate_types'],[])


class Routing(unittest.TestCase):
    def test_only_exact_readonly_probe_commands_and_all_process_guards(self):
        for label,command in k.COMMANDS.items():
            with mock.patch.object(s.g,'run_checked') as checked:
                run=s.runner({'HOME':'CANARY'},time.monotonic()+10,mock.Mock());run(label,list(command))
                kw=checked.call_args.kwargs;self.assertTrue(kw['stdout_only']);self.assertIsNotNone(kw['overlay'])
                checked.reset_mock()
                for unexpected in (list(command)+['-s','CANARY'],['/bin/echo','CANARY']):
                    with self.assertRaisesRegex(p.PolicyError,'signed_keychain_probe_command'):run(label,unexpected)
                checked.assert_not_called()

    def test_contexts_verified_and_home_change_confined_to_readonly_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve();env={'HOME':'/isolated','PATH':'/safe','TMPDIR':'/isolated/tmp'}
            actual=dict(env);ctx={'deadline':9999,'overlay':object()};calls=[]
            def query(label,command,**kwargs):
                calls.append((label,tuple(command)));return '' if label.startswith('keychain') else '0 valid identities found'
            with mock.patch.object(s.profile_installation,'native_home',return_value=home),mock.patch.object(s,'runner',return_value=query) as factory,mock.patch('builtins.print') as printed:
                s.probe_keychains('BEFORE_ARCHIVE',query,env,ctx,Path('/owned'),[],PINS)
            self.assertEqual(env,actual);self.assertEqual(factory.call_args.args[0],{**env,'HOME':str(home)})
            self.assertEqual(calls,list(k.COMMANDS.items()));self.assertNotIn(str(home),str(printed.call_args_list))

    def test_failure_in_each_query_stops_probes_without_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            for failure in k.COMMANDS:
                calls=[]
                def query(label,command,**kwargs):
                    calls.append(label)
                    if label==failure:raise RuntimeError('CANARY')
                    return '' if label.startswith('keychain') else '0 valid identities found'
                with mock.patch.object(s.profile_installation,'native_home',return_value=Path(tmp).resolve()),mock.patch.object(s,'runner',return_value=query),mock.patch('builtins.print'),self.assertRaises(RuntimeError):
                    s.probe_keychains('AFTER_SELECT',query,{}, {'deadline':9999,'overlay':None},Path('/owned'),[],PINS)
                self.assertEqual(calls,list(k.COMMANDS)[:list(k.COMMANDS).index(failure)+1])
