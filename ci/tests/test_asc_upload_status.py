"""Synthetic Apple import records only, no credential files or network calls."""
import json
import unittest
from unittest import mock
from ci.github import asc_status as a, upload_status as u
from ci.testflight import policy as p


def payload():
    return {'data':[{'type':'buildUploads','id':'CANARY_IDENTIFIER','attributes':{
        'cfBundleShortVersionString':'0.1.0','cfBundleVersion':'1','platform':'IOS',
        'state':{'state':'PROCESSING','errors':[],'warnings':[],'infos':[]},'unexpected':'CANARY'}}]}


class UploadStatus(unittest.TestCase):
    def test_all_states_and_empty_uploads_are_distinct_from_build_availability(self):
        for state in sorted(u.STATES):
            value=payload();value['data'][0]['attributes']['state']['state']=state
            result=u.project(value,'1');self.assertEqual(result['uploads'][0]['state'],state)
            self.assertNotIn('internal_available',json.dumps(result));self.assertNotIn('CANARY',json.dumps(result))
        self.assertEqual(u.project({'data':[]},'1')['returned_uploads'],0)

    def test_error_codes_and_categories_never_include_descriptions_or_unknown_values(self):
        value=payload();state=value['data'][0]['attributes']['state'];state['state']='FAILED'
        state['errors']=[{'code':'ITMS-90022','description':'Missing required icon file CANARY at /private/CANARY'},
            {'code':'CANARY_CODE','description':'CANARY_TOKEN'},{'code':None,'description':['CANARY']}]
        state['warnings']=[{'code':'CANARY','description':'App icon contains an alpha channel CANARY'}]
        result=u.project(value,'1');self.assertEqual(result['uploads'][0]['errors']['codes'],['90022','OTHER'])
        self.assertEqual(result['uploads'][0]['errors']['categories'],['ICON_MISSING','UNCLASSIFIED'])
        self.assertEqual(result['uploads'][0]['warnings']['categories'],['ICON_ALPHA'])
        self.assertNotIn('CANARY',json.dumps(result));self.assertNotIn('/private',json.dumps(result))

    def test_each_diagnostic_pattern_is_finite_and_long_text_is_not_scanned_or_echoed(self):
        examples={'ICON_MISSING':'Missing app icon','ICON_ALPHA':'icon has transparency',
            'ICON_DIMENSIONS':'icon dimensions are invalid','INVALID_SIGNATURE':'invalid code signature',
            'SDK_UNSUPPORTED':'sdk version is unsupported','PRIVACY_USAGE':'Missing purpose string',
            'PRIVACY_MANIFEST':'privacy manifest is invalid','BUNDLE_METADATA':'CFBundleIdentifier is invalid',
            'MACHO_INVALID':'invalid Mach-O','ENCRYPTION_METADATA':'export compliance info is missing'}
        self.assertEqual(set(examples),set(u.PATTERNS))
        for expected,text in examples.items():
            result=u.details([{'code':'CANARY','description':text+' CANARY'}])
            self.assertIn(expected,result['categories']);self.assertNotIn('CANARY',json.dumps(result))
        self.assertEqual(u.details([{'description':'icon '+('CANARY'*1000)}])['categories'],['UNCLASSIFIED'])
        self.assertEqual(u.details(None),{'count':None,'codes':[],'categories':[]})

    def test_wrong_version_platform_shape_or_overbound_response_fails_closed(self):
        for field,bad in (('cfBundleVersion','2'),('cfBundleShortVersionString','CANARY'),('platform','CANARY'),('state',[])):
            value=payload();value['data'][0]['attributes'][field]=bad
            with self.assertRaises(p.PolicyError):u.project(value,'1')
        for value in ({'data':'CANARY'},{'data':payload()['data']*11},{'data':[{'type':'CANARY'}]}):
            with self.assertRaises(p.PolicyError):u.project(value,'1')
        for bad in ('CANARY',[None],[{}]*101):
            with self.assertRaises(p.PolicyError):u.details(bad)

    def test_unknown_upload_state_is_other_and_never_a_success(self):
        value=payload();value['data'][0]['attributes']['state']['state']='CANARY'
        result=u.project(value,'1');self.assertEqual(result['uploads'][0]['state'],'OTHER')
        self.assertNotIn('CANARY',json.dumps(result))

    def test_only_two_fixed_app_get_shapes_are_allowed_before_signing_or_http(self):
        for path in (a.request_path('1'),a.upload_request_path('1')):a.validate_request_path(path)
        for path in (a.upload_request_path('1').replace(p.ASC_APP_ID,'999'),a.request_path('1')+'&CANARY=1',
            a.request_path('1')+'#CANARY',a.request_path('1')+'\n',a.request_path('1').replace('version%5D=1','version%5D=0'),
            '/v1/certificates?filter%5Bversion%5D=1','https://CANARY'+a.request_path('1')):
            with mock.patch.object(a,'run_bounded') as process,mock.patch.object(a.urllib.request,'build_opener') as http:
                with self.assertRaises(p.PolicyError):a.token(path,None,None)
                with self.assertRaises(p.PolicyError):a.get_builds(path,'CANARY')
                process.assert_not_called();http.assert_not_called()
