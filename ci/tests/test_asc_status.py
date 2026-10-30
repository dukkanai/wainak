"""Apple status contract and synthetic crypto/HTTP only; no real Apple key/API."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error
from ci.github import asc_status as a,internal_policy as q
from ci.testflight import policy as p

BUILD='11111111-2222-3333-4444-555555555555'


def payload():
    return {'data':[{'type':'builds','id':BUILD,'attributes':{'version':'1','processingState':'VALID','buildAudienceType':'INTERNAL_ONLY','expired':False,'usesNonExemptEncryption':None,'name':'CANARY'},
        'relationships':{'app':{'data':{'type':'apps','id':p.ASC_APP_ID}},'preReleaseVersion':{'data':{'type':'preReleaseVersions','id':'v'}},
            'buildBetaDetail':{'data':{'type':'buildBetaDetails','id':'b'}},'betaGroups':{'data':[{'type':'betaGroups','id':'g'}]}}}],
        'included':[{'type':'preReleaseVersions','id':'v','attributes':{'version':'0.1.0','platform':'IOS'}},
                    {'type':'buildBetaDetails','id':'b','attributes':{'internalBuildState':'IN_BETA_TESTING'}},
                    {'type':'betaGroups','id':'g','attributes':{'isInternalGroup':True,'name':'CANARY'}}]}


class Status(unittest.TestCase):
    def test_api_failure_reports_fixed_status_route_and_categories_without_body_or_token(self):
        body=json.dumps({'errors':[{'code':'ENTITY_ERROR.ATTRIBUTE.INVALID','title':'Invalid attribute',
            'detail':'CANARY_TOKEN private values','source':{'pointer':'/data/attributes/usesNonExemptEncryption'}}]}).encode()
        stream=io.BytesIO(body);opener=mock.Mock()
        opener.open.side_effect=urllib.error.HTTPError('https://CANARY',409,'CANARY_TOKEN',{},stream)
        with mock.patch.object(a.urllib.request,'build_opener',return_value=opener),mock.patch('builtins.print') as printed,self.assertRaisesRegex(p.PolicyError,'asc_conflict'):
            a.get_builds(a.request_path('1'),'CANARY_TOKEN')
        event=json.loads(printed.call_args.args[0]);self.assertEqual(event['status_code'],409)
        self.assertEqual(event['route'],'BUILD_LIST');self.assertEqual(event['method'],'GET');self.assertEqual(event['outcome'],'FAILED')
        self.assertEqual(event['error_summary']['codes'],['ENTITY_ERROR.ATTRIBUTE.INVALID'])
        self.assertEqual(event['error_summary']['categories'],['ENCRYPTION_DECLARATION','INVALID_ATTRIBUTE'])
        self.assertNotIn('CANARY',str(printed.call_args_list));self.assertTrue(stream.closed)

    def test_invalid_duplicate_unknown_and_oversized_error_bodies_never_escape_projection(self):
        for body in (b'CANARY',b'{"errors":[],"errors":"CANARY"}',b'[]',b'CANARY'*4000):
            result=a.http_error_summary(body);self.assertIsNone(result['count']);self.assertNotIn('CANARY',json.dumps(result))
        result=a.http_error_summary(json.dumps({'errors':[{'code':'CANARY','detail':'CANARY','source':{'pointer':'/CANARY'}}]}).encode())
        self.assertEqual(result,{'count':1,'codes':['OTHER'],'categories':['UNCLASSIFIED']})

    def test_success_and_unexpected_success_status_remain_distinct_and_bounded(self):
        for status,passes in ((200,True),(201,False),(202,False),(204,False)):
            response=mock.MagicMock();response.__enter__.return_value=response
            response.status=status;response.read.return_value=b'{"private":"CANARY"}'
            opener=mock.Mock();opener.open.return_value=response
            with mock.patch.object(a.urllib.request,'build_opener',return_value=opener),mock.patch('builtins.print') as printed:
                if passes:self.assertEqual(a.get_builds(a.request_path('1'),'CANARY')['private'],'CANARY')
                else:
                    with self.assertRaisesRegex(p.PolicyError,'asc_http'):a.get_builds(a.request_path('1'),'CANARY')
            event=json.loads(printed.call_args.args[0]);self.assertEqual(event['status_code'],status)
            self.assertEqual(event['outcome'],'PASS' if passes else 'FAILED');self.assertNotIn('CANARY',str(printed.call_args_list))
            if passes:response.read.assert_called_once_with(512*1024+1)
            else:response.read.assert_not_called()

    def test_lookup_counts_distinguish_empty_missing_and_unexpected_version_without_values(self):
        empty=a.project({'data':[]},'1');self.assertEqual(empty['lookup']['returned_builds'],0)
        for mode,field in (('missing','missing_prerelease'),('version','other_marketing_version'),('platform','other_platform')):
            changed=payload()
            if mode=='missing':changed['included']=changed['included'][1:]
            else:changed['included'][0]['attributes']['version' if mode=='version' else 'platform']='CANARY'
            result=a.project(changed,'1');self.assertFalse(result['found'])
            self.assertEqual(result['lookup']['returned_builds'],1);self.assertEqual(result['lookup'][field],1)
            self.assertEqual(result['lookup']['expected_ios_version'],0);self.assertNotIn('CANARY',json.dumps(result))
        self.assertEqual(a.project(payload(),'1')['lookup']['expected_ios_version'],1)

    def test_read_polling_is_bounded_and_refreshes_only_fixed_get_tokens(self):
        with mock.patch.object(a,'get_builds',return_value={'data':[]}) as query, \
             mock.patch.object(a,'token',return_value='CANARY_TOKEN') as token, \
             mock.patch.object(a.time,'sleep') as pause,mock.patch('builtins.print') as printed:
            a.read_status('1',Path('/synthetic/private.p8'),q.REVIEWED_PINS)
        self.assertEqual(query.call_count,4);self.assertEqual(token.call_count,4)
        self.assertEqual(pause.call_args_list,[mock.call(30)]*3)
        self.assertTrue(all(c.args==(a.request_path('1'),'CANARY_TOKEN') for c in query.call_args_list))
        self.assertNotIn('CANARY',str(printed.call_args_list))
        self.assertEqual([json.loads(c.args[0])['read_attempt'] for c in printed.call_args_list],[1,2,3,4])

    def test_read_stops_on_first_matching_build_without_claiming_processing_complete(self):
        processing=payload();processing['data'][0]['attributes']['processingState']='PROCESSING'
        with mock.patch.object(a,'get_builds',side_effect=[{'data':[]},processing]) as query, \
             mock.patch.object(a,'token',return_value='CANARY_TOKEN'), \
             mock.patch.object(a.time,'sleep') as pause,mock.patch('builtins.print') as printed:
            a.read_status('1',Path('/synthetic/private.p8'),q.REVIEWED_PINS)
        self.assertEqual(query.call_count,2);pause.assert_called_once_with(30)
        result=json.loads(printed.call_args.args[0]);self.assertTrue(result['found'])
        self.assertFalse(result['build']['internal_available'])

    def test_read_does_not_retry_http_or_projection_failure(self):
        for effect in (p.PolicyError('asc_unauthorized'),{'data':'CANARY'}):
            with mock.patch.object(a,'get_builds',side_effect=effect if isinstance(effect,Exception) else None,return_value=effect) as query, \
                 mock.patch.object(a,'token',return_value='CANARY_TOKEN'), \
                 mock.patch.object(a.time,'sleep') as pause,mock.patch('builtins.print') as printed,self.assertRaises(p.PolicyError):
                a.read_status('1',Path('/synthetic/private.p8'),q.REVIEWED_PINS)
            self.assertEqual(query.call_count,1);pause.assert_not_called();printed.assert_not_called()

    def test_contract_uses_only_existing_environment_p8_and_fixed_branch(self):
        a.validate_workflow();job=a.job();self.assertEqual(job['permissions'],{'contents':'read'})
        self.assertEqual(job['environment'],q.ENVIRONMENT);self.assertEqual(job['runs-on'],'ubuntu-24.04')
        self.assertIn(q.BRANCH,job['if']);self.assertIn('expected_sha == github.sha',job['if'])
        secrets=[step['env'] for step in job['steps'] if 'env' in step]
        self.assertEqual(len(secrets),1);self.assertEqual(set(secrets[0]),{q.UPLOAD_SECRETS[0]})
        self.assertNotIn('asc-status',q.job()['if'])

    def test_public_projection_availability_and_canary_isolation(self):
        result=a.project(payload(),'1');self.assertTrue(result['build']['internal_available'])
        self.assertNotIn('CANARY',json.dumps(result))
        for attribute,value in (('processingState','PROCESSING'),('expired',True),('buildAudienceType','APP_STORE_ELIGIBLE')):
            changed=payload();changed['data'][0]['attributes'][attribute]=value
            self.assertFalse(a.project(changed,'1')['build']['internal_available'])
        changed=payload();changed['included'][1]['attributes']['internalBuildState']='CANARY'
        result=a.project(changed,'1');self.assertEqual(result['build']['internal_state'],'OTHER');self.assertNotIn('CANARY',json.dumps(result))
        self.assertFalse(a.project({'data':[]},'1')['found'])

    def test_wrong_app_number_shapes_and_duplicate_builds_fail_closed(self):
        for mutation in ('app','version','duplicate','shape','expired_type'):
            changed=payload()
            if mutation=='app':changed['data'][0]['relationships']['app']['data']['id']='999'
            elif mutation=='version':changed['data'][0]['attributes']['version']='CANARY'
            elif mutation=='duplicate':changed['data']*=2
            elif mutation=='expired_type':changed['data'][0]['attributes']['expired']='CANARY'
            else:changed={'data':'CANARY'}
            with self.subTest(mutation=mutation),self.assertRaises(p.PolicyError):a.project(changed,'1')

    def test_external_groups_and_different_marketing_version_never_claim_internal(self):
        changed=payload();changed['included'][2]['attributes']['isInternalGroup']=False
        self.assertFalse(a.project(changed,'1')['build']['internal_available'])
        changed['included'][0]['attributes']['version']='2.0.0'
        self.assertFalse(a.project(changed,'1')['found'])

    def test_invalid_context_rejected_before_any_child_query(self):
        with mock.patch.object(a,'run_bounded') as runner,self.assertRaisesRegex(p.PolicyError,'asc_context'):
            a.preflight({'GITHUB_REPOSITORY':'CANARY'})
        runner.assert_not_called()

    def test_der_rejects_invalid_noncanonical_and_unexpected_values(self):
        for value in (None,b'',b'CANARY',bytes.fromhex('3006020100020101'),bytes.fromhex('300702020001020101'),bytes.fromhex('3006020180020101')):
            with self.assertRaises(p.PolicyError):a.der_signature(value)
        self.assertEqual(a.der_signature(bytes.fromhex('3006020101020102')),b'\0'*31+b'\1'+b'\0'*31+b'\2')

    def test_http_errors_never_expose_body_or_auth(self):
        for code,reason in ((400,'asc_bad_request'),(401,'asc_unauthorized'),(403,'asc_forbidden'),(404,'asc_not_found'),
                            (405,'asc_method_not_allowed'),(409,'asc_conflict'),(422,'asc_unprocessable'),
                            (302,'asc_http'),(429,'asc_rate_limited'),(500,'asc_server_error')):
            opener=mock.Mock();opener.open.side_effect=urllib.error.HTTPError('https://CANARY',code,'CANARY_TOKEN',{},None)
            with mock.patch.object(a.urllib.request,'build_opener',return_value=opener),self.assertRaisesRegex(p.PolicyError,'^'+reason+'$') as caught:
                a.get_builds(a.request_path('1'),'CANARY_TOKEN')
            self.assertNotIn('CANARY',str(caught.exception))
            request=opener.open.call_args.args[0];self.assertEqual(request.get_method(),'GET')
            self.assertEqual(request.host,'api.appstoreconnect.apple.com')
        self.assertIsNone(a.NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_real_openssl_es256_roundtrip_with_ephemeral_synthetic_key(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp).resolve();key=work/'synthetic.p8';public=work/'public.pem'
            # Test-only local key; never an Apple credential and never printed.
            subprocess.run(['/usr/bin/openssl','genpkey','-algorithm','EC','-pkeyopt','ec_paramgen_curve:prime256v1','-out',str(key)],check=True,capture_output=True)
            subprocess.run(['/usr/bin/openssl','pkey','-in',str(key),'-pubout','-out',str(public)],check=True,capture_output=True)
            with mock.patch.multiple(a,ROOT=work,WORK=work):
                jwt=a.token(a.request_path('1'),key,q.REVIEWED_PINS)
            header,claims,signature=jwt.split('.')
            decode=lambda text:json.loads(base64.urlsafe_b64decode(text+'='*(-len(text)%4)))
            self.assertEqual(decode(header)['alg'],'ES256');body=decode(claims)
            self.assertEqual(body['exp']-body['iat'],120);self.assertEqual(body['scope'],['GET '+a.request_path('1')])
            self.assertEqual(len(base64.urlsafe_b64decode(signature+'='*(-len(signature)%4))),64)
            result=subprocess.run(['/usr/bin/openssl','dgst','-sha256','-verify',str(public),'-signature',str(work/'signature.der'),str(work/'message')],capture_output=True)
            self.assertEqual(result.returncode,0)

    def test_cleanup_only_owned_files_and_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();work=root/'owned';work.mkdir(mode=0o700)
            for name in a.FILES:(work/name).write_bytes(b'CANARY')
            other=root/'unrelated';other.write_bytes(b'OTHER')
            with mock.patch.multiple(a,ROOT=root,WORK=work):a.cleanup()
            self.assertFalse(work.exists());self.assertEqual(other.read_bytes(),b'OTHER')
            work.symlink_to(root,target_is_directory=True)
            with mock.patch.multiple(a,ROOT=root,WORK=work),self.assertRaises(p.PolicyError):a.cleanup()
