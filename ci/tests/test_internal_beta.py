"""Synthetic internal-delivery models only; no Apple calls or real credentials."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error
from ci.github import internal_beta as b, asc_status as a, internal_policy as q
from ci.testflight import policy as p

BID='11111111-2222-3333-4444-555555555555'
GID='22222222-3333-4444-5555-666666666666'
TID='33333333-4444-5555-6666-777777777777'
OWNER='canary_owner@example.invalid'


def row(kind,identifier,**attributes):return {'type':kind,'id':identifier,'attributes':attributes}
def owner():return {'data':[row('users',TID,username=OWNER,roles=['ACCOUNT_HOLDER'])]}
def group():return row('betaGroups',GID,name=b.GROUP_NAME,isInternalGroup=True,publicLinkEnabled=False,
    publicLink=None,publicLinkId=None,hasAccessToAllBuilds=False)
def tester():return row('betaTesters',TID,email=OWNER,inviteType='EMAIL',state='INVITED')


class Model(b.Client):
    def __init__(self):
        super().__init__(None,q.REVIEWED_PINS);self.calls=[];self.has_group=False;self.has_tester=False
        self.member=False;self.build_added=False;self.fail=None;self.after_write=False;self.foreign=False
    def request(self,operation):
        method,path,body,expected=self.spec(operation);self.calls.append(operation)
        if self.fail==operation and not self.after_write:raise p.PolicyError('beta_network')
        if operation=='OWNER_READ':result=owner()
        elif operation=='GROUPS_READ':result={'data':[group()] if self.has_group else []}
        elif operation=='GROUP_CREATE':self.has_group=True;result={'data':group()}
        elif operation in {'TESTER_READ','TESTER_APP_READ'}:result={'data':[tester()] if self.has_tester else []}
        elif operation=='TESTER_CREATE':self.has_tester=True;self.member=True;result={'data':tester()}
        elif operation=='GROUP_TESTERS_READ':
            result={'data':[tester()] if self.member else []}
            if self.foreign:result['data'].append(row('betaTesters',BID,email='other@example.invalid',inviteType='EMAIL',state='INVITED'))
        elif operation=='GROUP_BUILDS_READ':result={'data':[{'type':'builds','id':BID}] if self.build_added else []}
        elif operation=='ADD_OWNER':self.member=True;result=None
        elif operation=='ADD_BUILD':self.build_added=True;result=None
        else:raise AssertionError('Unexpected operation')
        if self.fail==operation and self.after_write:raise p.PolicyError('beta_network')
        return result
    def build_payload(self,*args):
        return {'data':[row('builds',BID,version='2',processingState='VALID',buildAudienceType='INTERNAL_ONLY',expired=False,
            usesNonExemptEncryption=False)|{'relationships':{'app':{'data':{'type':'apps','id':p.ASC_APP_ID}},
            'preReleaseVersion':{'data':{'type':'preReleaseVersions','id':'v'}},'buildBetaDetail':{'data':{'type':'buildBetaDetails','id':'b'}},
            'betaGroups':{'data':[{'type':'betaGroups','id':GID}] if self.build_added else []}}}],
            'included':[row('preReleaseVersions','v',version='0.1.0',platform='IOS'),
                row('buildBetaDetails','b',internalBuildState='IN_BETA_TESTING' if self.build_added else 'READY_FOR_BETA_TESTING'),group()]}


class BetaDelivery(unittest.TestCase):
    def exercise(self,model,expected_failure=False):
        with mock.patch.object(b,'BUILD_ID',BID),mock.patch.object(a,'get_builds',side_effect=model.build_payload), \
             mock.patch.object(a,'token',return_value='CANARY'),mock.patch('builtins.print') as printed:
            if expected_failure:
                with self.assertRaises(p.PolicyError):b.complete(model)
            else:b.complete(model)
        self.assertNotIn('canary',str(printed.call_args_list).casefold())
        return printed

    def test_complete_owner_only_delivery_and_idempotent_read_before_every_write(self):
        model=Model();printed=self.exercise(model)
        self.assertTrue(model.build_added and model.member)
        event=json.loads(printed.call_args_list[-2].args[0]);self.assertTrue(event['owner_only'])
        self.assertTrue(event['internal_availability_verified']);self.assertFalse(event['external_distribution'])
        first=model.calls[:];self.exercise(model)
        self.assertFalse(set(model.calls[len(first):])&{'GROUP_CREATE','TESTER_CREATE','ADD_OWNER','ADD_BUILD'})

    def test_existing_tester_is_linked_without_recreation(self):
        model=Model();model.has_group=True;model.has_tester=True;self.exercise(model)
        self.assertIn('ADD_OWNER',model.calls);self.assertNotIn('TESTER_CREATE',model.calls)

    def test_sparse_create_responses_require_full_independent_readback(self):
        class SparseModel(Model):
            def request(self,operation):
                result=super().request(operation)
                if operation in {'GROUP_CREATE','TESTER_CREATE'}:
                    result={'data':{key:result['data'][key] for key in ('type','id')}}
                return result
        model=SparseModel();self.exercise(model)
        self.assertTrue(model.build_added);self.assertGreaterEqual(model.calls.count('GROUPS_READ'),2)
        self.assertGreaterEqual(model.calls.count('GROUP_TESTERS_READ'),2)
        self.assertEqual(model.calls.count('TESTER_APP_READ'),1)

    def test_create_id_type_or_readback_disagreement_blocks_following_mutations(self):
        for operation in ('GROUP_CREATE','TESTER_CREATE'):
            class Mismatch(Model):
                def request(self,name):
                    result=super().request(name)
                    if name==operation:result=copy.deepcopy(result);result['data']['id']=BID
                    return result
            model=Mismatch();self.exercise(model,True);self.assertNotIn('ADD_BUILD',model.calls)
            if operation=='GROUP_CREATE':self.assertNotIn('TESTER_CREATE',model.calls)
        for bad in (None,{'data':None},{'data':{'type':'CANARY','id':GID}},{'data':{'type':'betaGroups','id':'CANARY'}}):
            with self.assertRaises(p.PolicyError):b.created_id(bad,'betaGroups')

    def test_every_operation_failure_stops_without_automatic_retry(self):
        for operation in sorted(b.OPERATIONS):
            model=Model();model.fail=operation
            if operation=='ADD_OWNER':model.has_group=True;model.has_tester=True
            with self.subTest(operation=operation):self.exercise(model,True)
            self.assertEqual(model.calls.count(operation),1)
            self.assertEqual(model.calls[-1],operation)

    def test_uncertain_applied_write_is_read_back_on_next_invocation_without_duplication(self):
        for operation in ('GROUP_CREATE','TESTER_CREATE','ADD_OWNER','ADD_BUILD'):
            model=Model();model.fail=operation;model.after_write=True
            if operation=='ADD_OWNER':model.has_group=True;model.has_tester=True
            self.exercise(model,True);model.fail=None;self.exercise(model)
            self.assertEqual(model.calls.count(operation),1);self.assertTrue(model.build_added)

    def test_foreign_group_members_prevent_any_invitation_or_build_assignment(self):
        model=Model();model.has_group=True;model.foreign=True;self.exercise(model,True)
        self.assertFalse(set(model.calls)&{'TESTER_CREATE','ADD_OWNER','ADD_BUILD'})

    def test_external_public_automatic_duplicate_or_unverified_owner_resources_rejected(self):
        opaque=owner();opaque['data'][0]['id']='CANARY_OPAQUE_USER_ID'
        self.assertEqual(b.select_owner(opaque),OWNER)
        for attribute,value in (('isInternalGroup',False),('publicLinkEnabled',True),('hasAccessToAllBuilds',True)):
            changed=group();changed['attributes'][attribute]=value
            with self.assertRaises(p.PolicyError):b.select_group({'data':[changed]})
        with self.assertRaises(p.PolicyError):b.select_group({'data':[group(),group()]})
        for changed in ({'data':[]},{'data':owner()['data']*2},{'data':[row('users',TID,username=OWNER,roles=['ADMIN'])]}):
            with self.assertRaises(p.PolicyError):b.select_owner(changed)
        for value in ('CANARY\n@example.invalid','wrong','owner@host\0.invalid'):
            with self.assertRaises(p.PolicyError):b.email(value)
        with self.assertRaises(p.PolicyError):b.rows({'data':[],'links':{'next':'CANARY'}},'users',2)

    def test_inspection_and_unverified_build_can_never_write_even_with_valid_ids(self):
        client=b.Client(None,q.REVIEWED_PINS);client.owner=OWNER;client.group=GID;client.tester=TID
        for operation in ('GROUP_CREATE','TESTER_CREATE','ADD_OWNER','ADD_BUILD',None,[], 'CANARY'):
            with mock.patch.object(a,'sign_message') as sign,mock.patch.object(b.urllib.request,'build_opener') as http,self.assertRaises(p.PolicyError):client.request(operation)
            sign.assert_not_called();http.assert_not_called()
        with mock.patch.object(b,'BUILD_ID',BID),mock.patch('builtins.print'):
            model=Model();b.inspect(model)
        self.assertEqual(model.calls,['OWNER_READ','GROUPS_READ'])

    def test_wrong_build_audience_flag_processing_or_id_rejected_before_writes(self):
        model=Model()
        for field,value in (('buildAudienceType','APP_STORE_ELIGIBLE'),('processingState','PROCESSING'),('expired',True),('usesNonExemptEncryption',None),('id',GID)):
            payload=model.build_payload()
            if field=='id':payload['data'][0]['id']=value
            else:payload['data'][0]['attributes'][field]=value
            with mock.patch.object(b,'BUILD_ID',BID),mock.patch.object(a,'get_builds',return_value=payload),mock.patch.object(a,'token',return_value='CANARY'),self.assertRaises(p.PolicyError):b.complete(model)
        self.assertEqual(model.calls,[])

    def test_http_failure_redacts_owner_headers_and_body_and_closes_response(self):
        client=b.Client(None,q.REVIEWED_PINS);stream=io.BytesIO(b'{"errors":[{"code":"CANARY","detail":"CANARY_PRIVATE"}]}')
        opener=mock.Mock();opener.open.side_effect=urllib.error.HTTPError('https://CANARY',403,'CANARY',{},stream)
        with mock.patch.object(a,'sign_message',return_value=b'\1'*64),mock.patch.object(b.urllib.request,'build_opener',return_value=opener), \
             mock.patch('builtins.print') as printed,self.assertRaisesRegex(p.PolicyError,'asc_forbidden'):client.request('OWNER_READ')
        self.assertTrue(stream.closed);self.assertNotIn('CANARY',str(printed.call_args_list))
        self.assertEqual(json.loads(printed.call_args.args[0])['status_code'],403)

    def test_post_status_and_body_are_exact_and_jwt_uses_documented_short_lived_write_form(self):
        for status,allowed in ((201,True),(200,False),(204,False)):
            client=b.Client(None,q.REVIEWED_PINS);client.owner=OWNER;client.verified_build=BID
            response=mock.MagicMock();response.__enter__.return_value=response;response.status=status
            response.read.return_value=json.dumps({'data':group()}).encode();opener=mock.Mock();opener.open.return_value=response
            with mock.patch.object(b,'BUILD_ID',BID),mock.patch.object(a,'sign_message',return_value=b'\1'*64), \
                 mock.patch.object(b.urllib.request,'build_opener',return_value=opener),mock.patch('builtins.print'):
                if allowed:client.request('GROUP_CREATE')
                else:
                    with self.assertRaises(p.PolicyError):client.request('GROUP_CREATE')
            request=opener.open.call_args.args[0];self.assertEqual(request.get_method(),'POST')
            body=json.loads(request.data);self.assertTrue(body['data']['attributes']['isInternalGroup'])
            self.assertFalse(body['data']['attributes']['publicLinkEnabled']);self.assertFalse(body['data']['attributes']['hasAccessToAllBuilds'])
            self.assertEqual(body['data']['relationships']['app']['data']['id'],p.ASC_APP_ID)
            jwt=request.get_header('Authorization').split()[1];claims=json.loads(base64.urlsafe_b64decode(jwt.split('.')[1]+'=='))
            self.assertNotIn('scope',claims);self.assertEqual(claims['exp']-claims['iat'],60)

    def test_each_read_remains_scoped_and_each_fixed_write_uses_sixty_second_jwt(self):
        for operation in sorted(b.OPERATIONS):
            client=b.Client(None,q.REVIEWED_PINS);client.owner=OWNER;client.verified_build=BID
            client.group=None if operation=='GROUP_CREATE' else GID
            client.tester=None if operation=='TESTER_CREATE' else TID
            with mock.patch.object(b,'BUILD_ID',BID):method,path,body,expected=client.spec(operation)
            response=mock.MagicMock();response.__enter__.return_value=response;response.status=expected
            response.read.return_value=b'' if expected==204 else b'{"data":[]}'
            opener=mock.Mock();opener.open.return_value=response
            with mock.patch.object(b,'BUILD_ID',BID),mock.patch.object(a,'sign_message',return_value=b'\1'*64), \
                 mock.patch.object(b.urllib.request,'build_opener',return_value=opener),mock.patch('builtins.print') as printed:
                client.request(operation)
            request=opener.open.call_args.args[0]
            self.assertEqual(request.get_method(),method)
            self.assertEqual(request.full_url,'https://api.appstoreconnect.apple.com'+path)
            jwt=request.get_header('Authorization').split()[1]
            claims=json.loads(base64.urlsafe_b64decode(jwt.split('.')[1]+'=='))
            self.assertEqual(claims['iss'],q.REVIEWED_PINS['asc_issuer_id'])
            self.assertEqual(claims['aud'],'appstoreconnect-v1')
            if method=='GET':
                self.assertEqual(claims['scope'],['GET '+path]);self.assertEqual(claims['exp']-claims['iat'],120)
            else:
                self.assertNotIn('scope',claims);self.assertEqual(claims['exp']-claims['iat'],60)
                self.assertIn(operation,{'GROUP_CREATE','TESTER_CREATE','ADD_OWNER','ADD_BUILD'})
                self.assertEqual(json.loads(request.data),body)
            self.assertNotIn('canary',str(printed.call_args_list).casefold())

    def test_documented_null_internal_link_fields_require_explicit_no_link_and_no_automatic_builds(self):
        for enabled in (False,None):
            value=group();value['attributes']['publicLinkEnabled']=enabled
            self.assertEqual(b.select_group({'data':[value]}),GID)
            for field,bad in (('publicLinkEnabled',True),('publicLinkEnabled',0),('publicLink','CANARY'),
                    ('publicLinkId','CANARY'),('isInternalGroup',False),('hasAccessToAllBuilds',True)):
                changed=copy.deepcopy(value);changed['attributes'][field]=bad
                with self.assertRaises(p.PolicyError):b.select_group({'data':[changed]})
            for missing in ('publicLinkEnabled','publicLink','publicLinkId','hasAccessToAllBuilds','isInternalGroup'):
                changed=copy.deepcopy(value);del changed['attributes'][missing]
                with self.assertRaises(p.PolicyError):b.select_group({'data':[changed]})

    def test_tester_shape_diagnostics_are_finite_and_unknown_values_still_fail_closed(self):
        for field,value,reason in (('email','CANARY_PRIVATE','beta_tester_email'),
                ('inviteType',None,'beta_tester_invite'),('inviteType','CANARY','beta_tester_invite'),
                ('inviteType',{},'beta_tester_invite'),('state',None,'beta_tester_state'),
                ('state','CANARY','beta_tester_state'),('state',[],'beta_tester_state')):
            value_row=tester();value_row['attributes'][field]=value
            with mock.patch('builtins.print') as printed,self.assertRaisesRegex(p.PolicyError,reason):
                b.select_tester({'data':[value_row]},OWNER)
            event=json.loads(printed.call_args.args[0]);self.assertEqual(event['event'],'BETA_TESTER_SHAPE')
            self.assertEqual(event['count'],1);self.assertNotIn('canary',json.dumps(event).casefold())
            self.assertIn(event['invite_type'],{'EMAIL','PUBLIC_LINK','MISSING','NULL','OTHER'})
            self.assertIn(event['state'],{'NOT_INVITED','INVITED','ACCEPTED','INSTALLED','REVOKED','MISSING','NULL','OTHER'})

    def test_empty_multiple_and_missing_tester_fields_have_distinct_safe_diagnostics(self):
        with mock.patch('builtins.print') as printed:
            self.assertIsNone(b.select_tester({'data':[]},OWNER))
        self.assertEqual(json.loads(printed.call_args.args[0])['count'],0)
        with mock.patch('builtins.print') as printed,self.assertRaisesRegex(p.PolicyError,'beta_tester_count'):
            b.select_tester({'data':[tester(),tester()]},OWNER)
        self.assertEqual(json.loads(printed.call_args.args[0])['count'],2)
        for field,reason in (('email','beta_tester_email'),('inviteType','beta_tester_invite'),('state','beta_tester_state')):
            value=tester();del value['attributes'][field]
            with mock.patch('builtins.print') as printed,self.assertRaisesRegex(p.PolicyError,reason):
                b.select_tester({'data':[value]},OWNER)
            self.assertNotIn('canary',str(printed.call_args_list).casefold())
        for kind in ('users','betaGroups','betaTesters'):
            with self.assertRaisesRegex(p.PolicyError,'beta_response'):
                b.rows({'data':[{'type':kind,'id':TID}]},kind,2)
        self.assertEqual(len(b.rows({'data':[{'type':'builds','id':BID}]},'builds',2)),1)

    def test_explicit_null_state_is_only_enrollment_metadata_before_first_build(self):
        value=tester();value['attributes']['state']=None
        with mock.patch('builtins.print'):
            self.assertEqual(b.select_tester({'data':[value]},OWNER,pending_first_build=True),TID)
            with self.assertRaisesRegex(p.PolicyError,'beta_tester_state'):
                b.select_tester({'data':[value]},OWNER)
            for field,bad in (('email','CANARY'),('inviteType','PUBLIC_LINK'),('state','CANARY')):
                changed=copy.deepcopy(value);changed['attributes'][field]=bad
                with self.assertRaises(p.PolicyError):b.select_tester({'data':[changed]},OWNER,pending_first_build=True)
            del value['attributes']['state']
            with self.assertRaisesRegex(p.PolicyError,'beta_tester_state'):
                b.select_tester({'data':[value]},OWNER,pending_first_build=True)
            with self.assertRaisesRegex(p.PolicyError,'beta_context'):
                b.select_tester({'data':[]},OWNER,pending_first_build='CANARY')

    def test_initial_null_state_resolves_only_in_fixed_app_context_after_assignment(self):
        class PendingModel(Model):
            def request(self,operation):
                result=super().request(operation)
                if operation in {'TESTER_READ','GROUP_TESTERS_READ'}:
                    for value in result['data']:value['attributes']['state']=None
                return result
        model=PendingModel();self.exercise(model);self.assertTrue(model.build_added)
        previous=len(model.calls);self.exercise(model)
        self.assertFalse(set(model.calls[previous:])&{'GROUP_CREATE','TESTER_CREATE','ADD_OWNER','ADD_BUILD'})
        client=b.Client(None,q.REVIEWED_PINS);client.owner=OWNER;client.group=GID
        method,path,body,status=client.spec('TESTER_APP_READ')
        query=b.urllib.parse.parse_qs(b.urllib.parse.urlsplit(path).query)
        self.assertEqual((method,body,status),('GET',None,200))
        self.assertEqual(query['filter[apps]'],[p.ASC_APP_ID]);self.assertEqual(query['filter[email]'],[OWNER])

    def test_unknown_missing_null_or_uninvited_app_state_never_claims_delivery_or_repeats_build_write(self):
        for state in (None,'CANARY','NOT_INVITED','REVOKED','MISSING'):
            class UninvitedModel(Model):
                def request(self,operation):
                    result=super().request(operation)
                    if operation=='TESTER_APP_READ':
                        if state=='MISSING':del result['data'][0]['attributes']['state']
                        else:result['data'][0]['attributes']['state']=state
                    return result
            model=UninvitedModel();printed=self.exercise(model,True)
            self.assertTrue(model.build_added);self.assertNotIn('BETA_DELIVERY_VERIFIED',str(printed.call_args_list))
            self.exercise(model,True);self.assertEqual(model.calls.count('ADD_BUILD'),1)

    def test_delayed_build_activation_stays_pending_and_next_read_does_not_reassign(self):
        class ActivatingModel(Model):
            ready=False
            def build_payload(self,*args):
                result=super().build_payload(*args)
                if not self.ready:result['included'][1]['attributes']['internalBuildState']='READY_FOR_BETA_TESTING'
                return result
        model=ActivatingModel();printed=self.exercise(model,True)
        self.assertNotIn('BETA_DELIVERY_VERIFIED',str(printed.call_args_list));self.assertTrue(model.build_added)
        model.ready=True;self.exercise(model);self.assertEqual(model.calls.count('ADD_BUILD'),1)

    def test_expired_client_deadline_never_signs_or_opens_network(self):
        client=b.Client(None,q.REVIEWED_PINS);client.deadline=0
        with mock.patch.object(a,'sign_message') as sign,mock.patch.object(b.urllib.request,'build_opener') as http,self.assertRaisesRegex(p.PolicyError,'beta_deadline'):client.request('OWNER_READ')
        sign.assert_not_called();http.assert_not_called()

    def test_membership_post_requires_empty_204_and_exact_owner_id(self):
        for output,allowed in ((b'',True),(b'CANARY',False)):
            client=b.Client(None,q.REVIEWED_PINS);client.owner=OWNER;client.group=GID;client.tester=TID;client.verified_build=BID
            response=mock.MagicMock();response.__enter__.return_value=response;response.status=204;response.read.return_value=output
            opener=mock.Mock();opener.open.return_value=response
            with mock.patch.object(b,'BUILD_ID',BID),mock.patch.object(a,'sign_message',return_value=b'\1'*64), \
                 mock.patch.object(b.urllib.request,'build_opener',return_value=opener),mock.patch('builtins.print') as printed:
                if allowed:self.assertIsNone(client.request('ADD_OWNER'))
                else:
                    with self.assertRaisesRegex(p.PolicyError,'beta_response'):client.request('ADD_OWNER')
            request=opener.open.call_args.args[0];self.assertEqual(json.loads(request.data),{'data':[{'type':'betaTesters','id':TID}]})
            self.assertTrue(request.full_url.endswith('/'+GID+'/relationships/betaTesters'))
            self.assertNotIn('CANARY',str(printed.call_args_list))

    def test_owner_debug_number_app_tree_and_workflow_boundaries(self):
        value=b.job();self.assertEqual(value['permissions'],{'contents':'read'});self.assertEqual(value['environment'],q.ENVIRONMENT)
        self.assertIn("github.actor == 'dukkanai'",value['if']);self.assertIn('github.actor_id',value['if'])
        self.assertEqual(value['runs-on'],'ubuntu-24.04');self.assertEqual(value['timeout-minutes'],8)
        env={'GITHUB_ACTOR':q.OWNER_LOGIN,'GITHUB_ACTOR_ID':str(q.OWNER_ID),'WAINEK_BETA_TARGET':b.TARGET}
        result=subprocess.CompletedProcess([],0,b.APP_TREE+'\n','')
        with mock.patch.object(a,'preflight',return_value='2'),mock.patch.object(a,'run_bounded',return_value=result):
            b.preflight(env)
            for key,value in (('GITHUB_ACTOR','CANARY'),('GITHUB_ACTOR_ID','1'),('RUNNER_DEBUG','1'),('WAINEK_BETA_TARGET','other')):
                with self.assertRaises(p.PolicyError):b.preflight({**env,key:value})
        with mock.patch.object(a,'preflight',return_value='1'),self.assertRaises(p.PolicyError):b.preflight(env)
        with mock.patch.object(a,'preflight',return_value='2'),mock.patch.object(a,'run_bounded',return_value=subprocess.CompletedProcess([],0,'CANARY','')),self.assertRaisesRegex(p.PolicyError,'beta_app_tree'):b.preflight(env)

    def test_disabled_plan_never_reads_secret_and_cleanup_always_removes_only_synthetic_material(self):
        reviewed_job=b.job()
        with mock.patch.object(b,'BUILD_ID',None),mock.patch.object(b,'job',return_value=reviewed_job),mock.patch('builtins.print') as printed:
            self.assertEqual(b.main(['--check']),0);self.assertEqual(b.main(['--complete']),1)
        self.assertEqual(json.loads(printed.call_args.args[0])['safe_reason'],'beta_plan')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();work=root/'owned';other=root/'other';other.write_text('PRESERVE')
            key=b'-----BEGIN '+b'PRIVATE KEY-----\nCANARY\n'
            with mock.patch.multiple(a,ROOT=root,WORK=work),mock.patch.object(b,'preflight'),mock.patch.object(b,'read_build',return_value={'found':False}),mock.patch.object(b,'inspect',side_effect=p.PolicyError('beta_owner')), \
                 mock.patch.dict(os.environ,{q.UPLOAD_SECRETS[0]:base64.b64encode(key).decode()},clear=True),mock.patch('builtins.print') as printed:
                self.assertEqual(b.main(['--inspect']),1)
            self.assertFalse(work.exists());self.assertEqual(other.read_text(),'PRESERVE');self.assertNotIn('CANARY',str(printed.call_args_list))

    def test_inspection_observes_build_then_owner_without_any_write_and_cleans_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();work=root/'owned';model=Model()
            key=b'-----BEGIN '+b'PRIVATE KEY-----\nCANARY\n'
            with mock.patch.multiple(a,ROOT=root,WORK=work),mock.patch.object(b,'preflight'),mock.patch.object(b,'Client',return_value=model), \
                 mock.patch.object(a,'get_builds',side_effect=model.build_payload),mock.patch.object(a,'token',return_value='CANARY'), \
                 mock.patch.dict(os.environ,{q.UPLOAD_SECRETS[0]:base64.b64encode(key).decode()},clear=True),mock.patch('builtins.print') as printed:
                self.assertEqual(b.main(['--inspect']),0)
            self.assertEqual(model.calls,['OWNER_READ','GROUPS_READ']);self.assertFalse(work.exists())
            events=[json.loads(c.args[0]) for c in printed.call_args_list]
            self.assertEqual(events[0]['event'],'ASC_BUILD_STATUS');self.assertEqual(events[-1]['event'],'BETA_OWNER_INSPECTION')
            self.assertNotIn('canary',str(printed.call_args_list).casefold())
