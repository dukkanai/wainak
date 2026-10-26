"""Synthetic artifact checks only. No Apple command or native binary executes."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ci/native'))
import native_runtime as runtime
import artifact_diagnostics as diagnostic
spec=importlib.util.spec_from_file_location('artifact_outer',ROOT/'ci/ios/diagnostics.py')
outer=importlib.util.module_from_spec(spec);spec.loader.exec_module(outer)
NAMES=diagnostic.ABI_NAMES

def symbols():return '\n'.join('0000000000000010 T _Archivebridge'+name for name in NAMES)+'\n'
def loads(variant):return 'Load command 0\n      cmd LC_BUILD_VERSION\n platform '+('2' if variant=='device' else '7')+'\n    minos 15.0\n'

class ArtifactDiagnosticTests(unittest.TestCase):
    def test_schema_constants_match(self):
        self.assertEqual(set(NAMES),outer.ARTIFACT_ABI_NAMES)
        self.assertEqual(diagnostic.CHECKS,outer.ARTIFACT_CHECKS)
        self.assertEqual(diagnostic.REASONS,outer.ARTIFACT_REASONS)
    def test_original_symbol_acceptance_preserved(self):
        self.assertTrue(diagnostic.strict_symbols_present(symbols()))
        for text in (symbols().replace(' T ',' U '),symbols().replace('0000000000000010',''),symbols().replace('_ArchivebridgeCancel','_ArchivebridgeCancelSuffix'),symbols().replace(' T ',' D ')):
            self.assertFalse(diagnostic.strict_symbols_present(text))
    def test_bsd_defined_undefined_nontext_and_addressless(self):
        text='00000001 T _ArchivebridgeCancel\n         U _ArchivebridgeClose\n00000002 D _ArchivebridgeEpoch\n-------- T _ArchivebridgeImportHistory\n         T _ArchivebridgeHistorySnapshot\n'
        row=diagnostic.symbol_summary(text)
        self.assertEqual(row['hex_text'],['Cancel']);self.assertEqual(row['addressless_text'],['HistorySnapshot','ImportHistory'])
        self.assertEqual(row['undefined'],['Close']);self.assertEqual(row['nontext'],['Epoch']);self.assertEqual(row['format_counts']['bsd'],5)
    def test_posix_and_darwin_are_diagnostics_not_acceptance(self):
        text='_ArchivebridgeCancel T 0000 0\n0000 (__TEXT,__text) external _ArchivebridgeClose\n         (undefined) external _ArchivebridgeEpoch\n'
        row=diagnostic.symbol_summary(text)
        self.assertEqual(row['defined'],['Cancel','Close']);self.assertEqual(row['undefined'],['Epoch'])
        self.assertEqual(row['format_counts']['posix'],1);self.assertEqual(row['format_counts']['darwin'],2)
        self.assertFalse(diagnostic.strict_symbols_present(text))
    def test_unrecognized_known_symbol_not_reported_absent(self):
        row=diagnostic.symbol_summary('PRIVATE ??? _ArchivebridgeCancel\n')
        self.assertEqual(row['unrecognized'],['Cancel']);self.assertNotIn('Cancel',row['missing'])
        self.assertNotIn('PRIVATE',json.dumps(row))
    def test_symbol_bounds(self):
        self.assertFalse(diagnostic.symbol_summary('x'*(8*1024*1024+1))['complete'])
        self.assertFalse(diagnostic.symbol_summary('x\n'*100001)['complete'])
        self.assertFalse(diagnostic.symbol_summary('x'*4097)['complete'])
    def test_large_whitespace_uses_bounded_token_parser(self):
        text=(' '*4096+'\n')*1000
        row=diagnostic.symbol_summary(text)
        self.assertEqual(row['format_counts']['other'],1000)
        self.assertEqual(diagnostic.load_summary(text)['counts']['build_records'],0)
    def test_load_counts_do_not_emit_actual_values(self):
        row=diagnostic.load_summary(loads('device')+'Load command 1\n cmd LC_BUILD_VERSION\n platform PRIVATE\n minos 99.99\n')
        self.assertEqual(row['counts']['platform_device'],1);self.assertEqual(row['counts']['platform_other'],1)
        self.assertEqual(row['counts']['minimum_match'],1);self.assertEqual(row['counts']['minimum_other'],1)
        self.assertNotIn('PRIVATE',json.dumps(row));self.assertNotIn('99.99',json.dumps(row))
    def test_fixed_reason_no_exception_formatting(self):
        class Hostile(Exception):
            def __str__(self):raise AssertionError('PRIVATE')
        self.assertEqual(diagnostic.reason(Hostile('PRIVATE')),'UNKNOWN')
        self.assertEqual(diagnostic.reason(ValueError('defined native binding symbols missing')),'SYMBOLS')
    def test_outer_rejects_malformed_details(self):
        good={'checks':[],'symbols':[{'variant':'device',**diagnostic.symbol_summary(symbols())}],'loads':[]}
        self.assertEqual(outer.artifact_summary(good),good)
        for key,value in [('defined',['PRIVATE']),('complete',1),('format_counts',{'bsd':True,'posix':0,'darwin':0,'other':0}),('missing',['Cancel'])]:
            row=copy.deepcopy(good);row['symbols'][0][key]=value
            with self.assertRaises(ValueError):outer.artifact_summary(row)
    def test_outer_strips_unknown_fields_and_preserves_valid_checks_on_failure(self):
        data={'status':'FAILED','native_runtime_test':False,'failed_stage':'artifact-inspection','artifact_inspection':{'checks':[{'check':'symbols','variant':'device','outcome':'FAILED','reason':'SYMBOLS','private':'PRIVATE'}],'symbols':[],'loads':[],'raw':'PRIVATE'}}
        row=outer.native_summary(None,Mock(return_value=data));self.assertNotIn('PRIVATE',json.dumps(row));self.assertEqual(row['artifact_inspection']['checks'][0]['reason'],'SYMBOLS')
    def test_outer_receipt_bounds_and_false_pass(self):
        for value in ([{'check':'symbols','variant':'device','outcome':'PASS','reason':'SYMBOLS'}], [{}]*25):
            with self.assertRaises(ValueError):outer.artifact_summary({'checks':value,'symbols':[],'loads':[]})
    def test_invalid_optional_receipt_preserves_primary_failure(self):
        data={'status':'FAILED','native_runtime_test':False,'failed_stage':'artifact-inspection',
              'gate_category':'UNKNOWN_TOOL_FAILURE','artifact_inspection':{'checks':['PRIVATE']}}
        row=outer.native_summary(None,Mock(return_value=data))
        self.assertEqual(row['status'],'FAILED');self.assertEqual(row['failed_stage'],'artifact-inspection')
        self.assertEqual(row['artifact_inspection'],{'availability':'invalid'})
        self.assertNotIn('PRIVATE',json.dumps(row))

class ArtifactAggregationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.output=self.root/'Archivebridge.xcframework';self.output.mkdir()
        self.libs=[];self.frameworks={};self.header=b'public fixture';headers=['ref.h','Archivebridge.objc.h','Universe.objc.h','Archivebridge.h']
        self.lock={'apple':{'header_sha256':hashlib.sha256(self.header).hexdigest(),'headers':headers,'framework_plist_minimum_os_upstream':'100.0'}}
        for variant,ident in [('device','ios-arm64'),('simulator','ios-arm64-simulator')]:
            framework=self.output/ident/'Archivebridge.framework';(framework/'Headers').mkdir(parents=True);(framework/'Modules').mkdir()
            (framework/'Headers/Archivebridge.objc.h').write_bytes(self.header)
            (framework/'Modules/module.modulemap').write_text('framework module "Archivebridge" {\n'+''.join('header "'+h+'"\n' for h in headers)+'export *\n}')
            (framework/'Archivebridge').write_bytes(b'!<arch>\npublic fixture')
            (framework/'Info.plist').write_bytes(plistlib.dumps({'MinimumOSVersion':'100.0'}))
            lib={'SupportedPlatform':'ios','SupportedArchitectures':['arm64'],'LibraryIdentifier':ident,'LibraryPath':'Archivebridge.framework'}
            if variant=='simulator':lib['SupportedPlatformVariant']='simulator'
            self.libs.append(lib);self.frameworks[variant]=framework
        self.write_metadata();self.outputs={v:{'slice-architecture':b'arm64\n','slice-symbols':symbols().encode(),'slice-load-commands':loads(v).encode()} for v in self.frameworks}
        self.calls=[];self.rt=Mock();self.rt.repo=self.root
        def run(args,cwd,env,name):
            variant='simulator' if 'ios-arm64-simulator' in str(args[-1]) else 'device';self.calls.append((variant,name));value=self.outputs[variant][name]
            if isinstance(value,BaseException):raise value
            return value
        self.rt.run.side_effect=run
    def write_metadata(self):self.output.joinpath('Info.plist').write_bytes(plistlib.dumps({'AvailableLibraries':self.libs}))
    def invoke(self):return runtime.inspect_xcframework(self.rt,self.output,{},self.lock)
    def test_valid_both_slices_pass(self):
        self.assertEqual(len(self.invoke()),2);self.assertEqual(len(self.calls),6)
        receipt=outer.artifact_summary(self.rt.artifact_receipt);self.assertTrue(all(c['outcome']=='PASS' for c in receipt['checks']))
    def test_symbol_and_load_and_plist_failures_all_collected_before_failure(self):
        self.outputs['device']['slice-symbols']=symbols().replace('_ArchivebridgeCancel','_PRIVATE').encode()
        self.outputs['simulator']['slice-load-commands']=loads('device').replace('15.0','16.0').encode()
        (self.frameworks['device']/'Info.plist').write_bytes(plistlib.dumps({'MinimumOSVersion':'99.0'}))
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        receipt=outer.artifact_summary(self.rt.artifact_receipt);reasons={c['reason'] for c in receipt['checks'] if c['outcome']=='FAILED'}
        self.assertTrue({'SYMBOLS','LOAD_PLATFORM','FRAMEWORK_PLIST'}<=reasons);self.assertEqual(len(self.calls),6)
        self.assertNotIn('PRIVATE',json.dumps(receipt))
    def test_header_and_modulemap_fail_do_not_hide_other_safe_checks(self):
        (self.frameworks['device']/'Headers/Archivebridge.objc.h').write_bytes(b'changed')
        (self.frameworks['simulator']/'Modules/module.modulemap').write_text('wrong')
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        self.assertEqual(len(self.calls),6);self.assertEqual(len(self.rt.artifact_receipt['symbols']),2)
    def test_invalid_container_skips_dependent_tools(self):
        (self.frameworks['device']/'Archivebridge').write_bytes(b'not archive')
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        self.assertEqual(self.calls,[('simulator',n) for n in ('slice-architecture','slice-symbols','slice-load-commands')])
    def test_invalid_path_never_runs_tools_for_that_slice(self):
        self.libs[0]['LibraryIdentifier']='../PRIVATE';self.write_metadata()
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        self.assertTrue(all(v=='simulator' for v,n in self.calls));self.assertNotIn('PRIVATE',json.dumps(self.rt.artifact_receipt))
    def test_runtime_resource_failure_is_not_caught_or_replaced(self):
        primary=runtime.BuildFailure('workspace budget exceeded');self.outputs['device']['slice-symbols']=primary
        with self.assertRaises(runtime.BuildFailure) as caught:self.invoke()
        self.assertIs(caught.exception,primary);self.assertEqual(len(self.calls),2)
    def test_decode_failure_continues_other_readonly_checks(self):
        self.outputs['device']['slice-symbols']=b'\xff'
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        self.assertEqual(len(self.calls),6);self.assertIn('DECODE',{c['reason'] for c in self.rt.artifact_receipt['checks']})
    def test_non_dict_top_level_plist_records_metadata_failure(self):
        (self.output/'Info.plist').write_bytes(plistlib.dumps([]))
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        self.assertEqual(self.rt.artifact_receipt['checks'][0]['reason'],'METADATA');self.assertFalse(self.calls)
    def test_non_dict_framework_plist_does_not_hide_other_slice(self):
        (self.frameworks['device']/'Info.plist').write_bytes(plistlib.dumps([]))
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        self.assertEqual(len(self.calls),6);self.assertIn('FRAMEWORK_PLIST',{c['reason'] for c in self.rt.artifact_receipt['checks']})
    def test_bad_metadata_stops_before_any_tools(self):
        self.libs=[];self.write_metadata()
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        self.assertFalse(self.calls)
    def finalized_runtime(self):
        (self.root/'lock.json').write_text('{}\n')
        return SimpleNamespace(work=self.root,stage='artifact-inspection',last_command=None,
            resource_final_audit_failed=False,full_audits=0,peak_reserved=0,
            artifact_receipt=self.rt.artifact_receipt,guard=lambda **kwargs:None)
    def test_failed_artifact_receipt_survives_real_file_projection(self):
        self.outputs['device']['slice-symbols']=symbols().replace('_ArchivebridgeCancel','_PRIVATE').encode()
        with self.assertRaisesRegex(Exception,'artifact validation failed'):self.invoke()
        rt=self.finalized_runtime()
        result={'status':'FAILED','native_runtime_test':False}
        runtime.finalize_native_result(rt,self.root,self.root,result,{},{},runtime.InvalidRecipe('artifact validation failed'))
        projected=outer.native_summary(self.root/'result.json')
        self.assertEqual(projected['status'],'FAILED');self.assertEqual(projected['failed_stage'],'artifact-inspection')
        receipt=projected['artifact_inspection']
        self.assertEqual(len(receipt['symbols']),2);self.assertEqual(len(receipt['loads']),2)
        self.assertIn('SYMBOLS',{row['reason'] for row in receipt['checks']})
        self.assertNotIn('PRIVATE',json.dumps(projected))
    def test_final_resource_failure_retains_receipt_without_pass(self):
        self.invoke();rt=self.finalized_runtime()
        rt.guard=Mock(side_effect=runtime.BuildFailure('workspace budget exceeded'))
        result={'status':'PASS_UNSIGNED_NATIVE_BUILD_ONLY','native_runtime_test':False}
        with self.assertRaises(runtime.BuildFailure):runtime.finalize_native_result(rt,self.root,self.root,result,{},{},None)
        projected=outer.native_summary(self.root/'result.json')
        self.assertEqual(projected['status'],'FAILED');self.assertEqual(projected['failed_stage'],'artifact-inspection')
        self.assertEqual(len(projected['artifact_inspection']['symbols']),2)

if __name__=='__main__':unittest.main()
