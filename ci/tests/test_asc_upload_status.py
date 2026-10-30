"""Synthetic Apple diagnostics only, no credential files or network calls."""
import json
import unittest
from unittest import mock
from ci.github import asc_status as a, upload_status as u
from ci.testflight import policy as p


class UploadStatus(unittest.TestCase):
    def test_group_observation_never_echoes_unexpected_names_or_external_ids(self):
        internal={'type':'betaGroups','id':'11111111-2222-3333-4444-555555555555','attributes':{'isInternalGroup':True,
            'name':'CANARY','publicLinkEnabled':False,'hasAccessToAllBuilds':False}}
        external={'type':'betaGroups','id':'CANARY','attributes':{'isInternalGroup':False}}
        result=u.project_groups({'data':[internal,external]})
        self.assertEqual(result['external_group_count'],1);self.assertEqual(result['internal_groups'][0]['name_class'],'OTHER')
        self.assertNotIn('CANARY',json.dumps(result))
        for value in ({'data':[internal]*101},{'data':'CANARY'},{'data':[{'type':'CANARY'}]}):
            with self.assertRaises(p.PolicyError):u.project_groups(value)

    def test_error_codes_and_categories_never_include_descriptions_or_unknown_values(self):
        errors=[{'code':'ITMS-90022','description':'Missing required icon file CANARY at /private/CANARY'},
            {'code':'CANARY_CODE','description':'CANARY_TOKEN'},{'code':None,'description':['CANARY']}]
        result=u.details(errors);self.assertEqual(result['codes'],['90022','OTHER'])
        self.assertEqual(result['categories'],['ICON_MISSING','UNCLASSIFIED'])
        self.assertEqual(u.details([{'code':'CANARY','description':'App icon contains an alpha channel CANARY'}])['categories'],['ICON_ALPHA'])
        self.assertNotIn('CANARY',json.dumps(result));self.assertNotIn('/private',json.dumps(result))

    def test_each_diagnostic_pattern_is_finite_and_long_text_is_not_scanned_or_echoed(self):
        examples={'ICON_MISSING':'Missing app icon','ICON_ALPHA':'icon has transparency',
            'ICON_DIMENSIONS':'icon dimensions are invalid','INVALID_SIGNATURE':'invalid code signature',
            'SDK_UNSUPPORTED':'sdk version is unsupported','PRIVACY_USAGE':'Missing purpose string',
            'PRIVACY_MANIFEST':'privacy manifest is invalid','BUNDLE_METADATA':'CFBundleIdentifier is invalid',
            'MACHO_INVALID':'invalid Mach-O','ENCRYPTION_METADATA':'export compliance info is missing',
            'ENCRYPTION_DECLARATION':'usesNonExemptEncryption','ATTRIBUTE_NOT_EDITABLE':'attribute is not editable',
            'INVALID_ATTRIBUTE':'invalid attribute','UNSUPPORTED_ATTRIBUTE':'attribute is not supported',
            'INTERNAL_ONLY_RESTRICTION':'internal-only build','RELATED_RESOURCE_MISSING':'missing relationship',
            'AGREEMENT_REQUIRED':'agreement required','METHOD_NOT_ALLOWED':'The request method is not valid for the resource path'}
        self.assertEqual(set(examples),set(u.PATTERNS))
        for expected,text in examples.items():
            result=u.details([{'code':'CANARY','description':text+' CANARY'}])
            self.assertIn(expected,result['categories']);self.assertNotIn('CANARY',json.dumps(result))
        self.assertEqual(u.details([{'description':'icon '+('CANARY'*1000)}])['categories'],['UNCLASSIFIED'])
        self.assertEqual(u.details(None),{'count':None,'codes':[],'categories':[]})

    def test_diagnostic_shape_and_bound_remain_strict(self):
        for bad in ('CANARY',[None],[{}]*101):
            with self.assertRaises(p.PolicyError):u.details(bad)

    def test_method_rejection_is_classified_without_captured_error_text(self):
        result=a.http_error_summary(json.dumps({'errors':[{'code':'METHOD_NOT_ALLOWED',
            'title':'The request method is not valid for the resource path. CANARY',
            'detail':'CANARY_PRIVATE'}]}).encode())
        self.assertEqual(result,{'count':1,'codes':['METHOD_NOT_ALLOWED'],'categories':['METHOD_NOT_ALLOWED']})
        self.assertNotIn('CANARY',json.dumps(result))

    def test_only_fixed_app_get_shapes_are_allowed_before_signing_or_http(self):
        for path in (a.request_path('1'),a.group_request_path()):a.validate_request_path(path)
        for path in (a.group_request_path().replace(p.ASC_APP_ID,'999'),a.request_path('1')+'&CANARY=1',
            a.request_path('1')+'#CANARY',a.request_path('1')+'\n',a.request_path('1').replace('version%5D=1','version%5D=0'),
            '/v1/certificates?filter%5Bversion%5D=1','https://CANARY'+a.request_path('1')):
            with mock.patch.object(a,'run_bounded') as process,mock.patch.object(a.urllib.request,'build_opener') as http:
                with self.assertRaises(p.PolicyError):a.token(path,None,None)
                with self.assertRaises(p.PolicyError):a.get_builds(path,'CANARY')
                process.assert_not_called();http.assert_not_called()
