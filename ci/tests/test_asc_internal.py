"""One-build-only metadata changes; synthetic responses and keys only."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
from ci.github import asc_internal as i, asc_status as a, internal_policy as q
from ci.testflight import policy as p
from ci.tests import test_asc_status as fixtures


def payload(encryption=None):
    value=fixtures.payload();value['data'][0]['id']=i.BUILD_ID
    value['data'][0]['attributes']['usesNonExemptEncryption']=encryption
    value['data'][0]['relationships']['betaGroups']['data']=[]
    value['included'][1]['attributes']['internalBuildState']='MISSING_EXPORT_COMPLIANCE' if encryption is None else 'READY_FOR_BETA_TESTING'
    return value


def state(encryption=None):return a.project(payload(encryption),'1')


class InternalMetadata(unittest.TestCase):
    def test_contract_is_owner_only_exact_branch_protected_one_existing_secret(self):
        i.validate_workflow();job=i.job()
        for text in (q.BRANCH,"github.actor == 'dukkanai'","github.actor_id == '255427171'",'expected_sha == github.sha','github.run_attempt == 1'):
            self.assertIn(text,job['if'])
        self.assertEqual(job['permissions'],{'contents':'read'});self.assertEqual(job['environment'],q.ENVIRONMENT)
        self.assertEqual(job['runs-on'],'ubuntu-24.04');self.assertEqual(job['timeout-minutes'],8)
        values=[x['env'] for x in job['steps'] if 'env' in x]
        self.assertEqual(values,[{q.UPLOAD_SECRETS[0]:'${{ secrets.'+q.UPLOAD_SECRETS[0]+' }}'}])
        with mock.patch('builtins.print') as printed:self.assertEqual(i.main(['--check']),0)
        self.assertFalse(json.loads(printed.call_args.args[0])['credentials_read'])

    def test_preflight_checks_owner_debug_number_and_app_tree(self):
        env={'GITHUB_ACTOR':q.OWNER_LOGIN,'GITHUB_ACTOR_ID':str(q.OWNER_ID),'WAINEK_ASC_INTERNAL_TARGET':'asc-internal'}
        output=subprocess.CompletedProcess([],0,i.APP_TREE+'\n','')
        with mock.patch.object(a,'preflight',return_value='1'),mock.patch.object(a,'run_bounded',return_value=output):
            self.assertEqual(i.preflight(env),'1')
            for key,value in (('GITHUB_ACTOR','CANARY'),('GITHUB_ACTOR_ID','1'),('WAINEK_ASC_INTERNAL_TARGET','CANARY'),
                ('RUNNER_DEBUG','1'),('ACTIONS_STEP_DEBUG','true'),('ACTIONS_RUNNER_DEBUG','true')):
                with self.assertRaises(p.PolicyError):i.preflight({**env,key:value})
        with mock.patch.object(a,'preflight',return_value='2'),self.assertRaises(p.PolicyError):i.preflight(env)
        with mock.patch.object(a,'preflight',return_value='1'),mock.patch.object(a,'run_bounded',return_value=subprocess.CompletedProcess([],0,'CANARY','')),self.assertRaisesRegex(p.PolicyError,'asc_reviewed_app_tree'):
            i.preflight(env)

    def test_wrong_build_audience_processing_expiry_encryption_or_number_never_write(self):
        for field,value in (('id','OTHER'),('processingState','PROCESSING'),('buildAudienceType','APP_STORE_ELIGIBLE'),('expired',True),('usesNonExemptEncryption',True)):
            changed=payload()
            if field=='id':changed['data'][0]['id']='00000000-0000-0000-0000-000000000000'
            else:changed['data'][0]['attributes'][field]=value
            with mock.patch.object(a,'get_builds',return_value=changed),mock.patch.object(a,'token',return_value='CANARY'),mock.patch.object(a,'json_request') as write,self.assertRaises(p.PolicyError):
                i.build_state('1',None,q.REVIEWED_PINS)
            write.assert_not_called()
        with self.assertRaises(p.PolicyError):i.build_state('2',None,q.REVIEWED_PINS)

    def test_complete_writes_only_false_to_reviewed_build_and_reverifies(self):
        result={'data':{'type':'builds','id':i.BUILD_ID,'attributes':{'usesNonExemptEncryption':False,'CANARY':'CANARY'}}}
        with mock.patch.object(i,'build_state',side_effect=[state(),state(False)]) as read, \
             mock.patch.object(i,'patch_token',return_value='CANARY_TOKEN'),mock.patch.object(a,'json_request',return_value=result) as write, \
             mock.patch.object(a,'get_builds',return_value={'data':[]}),mock.patch.object(a,'token',return_value='CANARY'),mock.patch('builtins.print') as printed:
            i.complete('1',Path('/CANARY'),q.REVIEWED_PINS)
        self.assertEqual(read.call_count,2);write.assert_called_once()
        request=write.call_args.args[0];self.assertEqual(request.get_method(),'PATCH')
        self.assertEqual(request.full_url,'https://api.appstoreconnect.apple.com'+i.BUILD_PATH)
        self.assertEqual(json.loads(request.data),{'data':{'type':'builds','id':i.BUILD_ID,'attributes':{'usesNonExemptEncryption':False}}})
        self.assertNotIn('CANARY',str(printed.call_args_list))
        self.assertFalse(json.loads(printed.call_args_list[1].args[0])['build']['internal_available'])

    def test_already_declared_is_idempotent_and_conflicting_state_never_changes(self):
        with mock.patch.object(i,'build_state',side_effect=[state(False),state(False)]),mock.patch.object(a,'json_request') as write, \
             mock.patch.object(a,'get_builds',return_value={'data':[]}),mock.patch.object(a,'token',return_value='CANARY'),mock.patch('builtins.print'):
            i.complete('1',None,q.REVIEWED_PINS)
        write.assert_not_called()
        before=state();before['build']['internal_state']='OTHER'
        with mock.patch.object(i,'build_state',return_value=before),mock.patch.object(a,'json_request') as write,self.assertRaisesRegex(p.PolicyError,'asc_declaration_conflict'):
            i.complete('1',None,q.REVIEWED_PINS)
        write.assert_not_called()

    def test_network_failure_or_wrong_response_has_no_automatic_write_retry(self):
        for effect in (p.PolicyError('asc_network'),{'data':{'type':'builds','id':'CANARY','attributes':{'usesNonExemptEncryption':False}}}):
            with mock.patch.object(i,'build_state',return_value=state()) as read,mock.patch.object(i,'patch_token',return_value='CANARY'), \
                 mock.patch.object(a,'json_request',side_effect=effect if isinstance(effect,Exception) else None,return_value=effect) as write, \
                 mock.patch('builtins.print') as printed,self.assertRaises(p.PolicyError):i.complete('1',None,q.REVIEWED_PINS)
            write.assert_called_once();read.assert_called_once();printed.assert_not_called()

    def test_patch_jwt_is_scoped_to_single_exact_path_and_120_seconds(self):
        with mock.patch.object(a,'sign_message',return_value=b'\1'*64) as signer:
            token=i.patch_token(i.BUILD_PATH,None,q.REVIEWED_PINS)
        claims=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'=='))
        self.assertEqual(claims['scope'],['PATCH '+i.BUILD_PATH]);self.assertEqual(claims['exp']-claims['iat'],120)
        for path in ('/v1/builds/CANARY',a.request_path('1'),i.BUILD_PATH+'?expired=true'):
            with mock.patch.object(a,'sign_message') as signer,self.assertRaises(p.PolicyError):i.patch_token(path,None,None)
            signer.assert_not_called()
        with mock.patch.object(a,'sign_message') as signer,self.assertRaises(p.PolicyError):a.token(i.BUILD_PATH,None,None)
        signer.assert_not_called()

    def test_group_observation_is_read_only_and_never_echoes_names_or_external_ids(self):
        group={'type':'betaGroups','id':i.BUILD_ID,'attributes':{'isInternalGroup':True,'name':'CANARY',
            'publicLinkEnabled':False,'hasAccessToAllBuilds':False}}
        external={'type':'betaGroups','id':'CANARY','attributes':{'isInternalGroup':False,'name':'CANARY'}}
        result=i.group_observation({'data':[group,external]})
        self.assertEqual(result['external_group_count'],1);self.assertEqual(result['internal_groups'][0]['name_class'],'OTHER')
        self.assertNotIn('CANARY',json.dumps(result))
        for bad in ({'data':[{'type':'CANARY'}]},{'data':[group]*101},{'data':'CANARY'}):
            with self.assertRaises(p.PolicyError):i.group_observation(bad)

    def test_main_cleans_synthetic_material_after_ambiguous_write_and_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();work=root/'owned';unrelated=root/'unrelated';unrelated.write_text('PRESERVE')
            fake_key=b'-----BEGIN '+b'PRIVATE KEY-----\nCANARY\n'
            with mock.patch.multiple(a,ROOT=root,WORK=work),mock.patch.object(i,'validate_workflow'), \
                 mock.patch.object(i,'preflight',return_value='1'),mock.patch.object(i,'complete',side_effect=p.PolicyError('asc_patch_ambiguous')), \
                 mock.patch.dict(os.environ,{q.UPLOAD_SECRETS[0]:base64.b64encode(fake_key).decode()},clear=True),mock.patch('builtins.print') as printed:
                self.assertEqual(i.main(['--complete']),1)
            self.assertFalse(work.exists());self.assertEqual(unrelated.read_text(),'PRESERVE')
            self.assertNotIn('CANARY',str(printed.call_args_list));self.assertEqual(json.loads(printed.call_args.args[0])['safe_reason'],'asc_patch_ambiguous')
