"""Source-only diagnostic coverage: synthetic bytes, no compiler/network."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ci/native'))
import host_diagnostics as native
spec=importlib.util.spec_from_file_location('native_projection_outer',ROOT/'ci/ios/diagnostics.py')
outer=importlib.util.module_from_spec(spec);spec.loader.exec_module(outer)

class NativeProjectionTests(unittest.TestCase):
    def row(self,name='apple-bind'):
        row=native.safe_last_command(name,1,0.25,'FAILED','NONZERO_EXIT')
        row['tool_categories']=['COMPILER']
        return row
    def test_all_commands_cross_both_layers(self):
        self.assertEqual(native.NATIVE_COMMANDS,outer.NATIVE_COMMANDS)
        self.assertEqual(native.TOOL_CATEGORIES,outer.TOOL_CATEGORIES)
        for name in native.NATIVE_COMMANDS:
            row=self.row(name)
            self.assertEqual(outer.command_summary(row,{}),row)
    def test_command_inventory_matches_runtime_call_sites(self):
        tree=ast.parse((ROOT/'ci/native/native_runtime.py').read_text())
        derived=set()
        expansions={
            "name + '-modules'": {p+'-modules' for p in ('tool-input','binding-input','target-0','target-1')},
            "name + '-controls'": {p+'-controls' for p in ('tool-input','binding-input','target-0','target-1')},
            "sdk + '-clang'": {p+'-clang' for p in ('iphoneos','iphonesimulator')},
            "sdk + '-sysroot'": {p+'-sysroot' for p in ('iphoneos','iphonesimulator')},
            "sdk + '-sdk'": {p+'-sdk' for p in ('iphoneos','iphonesimulator')},
            "'target-' + variant + '-packages'": {'target-device-packages','target-simulator-packages'},
            "name + '-test-compile'": {'archive-test-compile','archivebridge-test-compile'},
            "name + '-tests'": {'archive-tests','archivebridge-tests'},
            "name + '-vet'": {'archive-vet','archivebridge-vet'},
            "'fuzz-' + fuzz": {'fuzz-FuzzStrictHistoryJSON','fuzz-FuzzArchiveOpen'},
            "tool + '-build'": {'gobind-build','gomobile-build'},
            "tool + '-buildinfo'": {'gobind-buildinfo','gomobile-buildinfo'},
        }
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='runtime' and node.func.attr=='run':
                label=node.args[3]
                if isinstance(label,ast.Constant):derived.add(label.value)
                else:derived.update(expansions[ast.unparse(label)])
        self.assertEqual(derived,native.NATIVE_COMMANDS | native.HOST_COMMANDS)
    def test_exact_fourth_stage_retains_apple_receipt(self):
        result=outer.native_summary(None,Mock(return_value={'status':'FAILED','native_runtime_test':False,'failed_stage':'unmodified-upstream-apple-bind','last_command':self.row(),'gate_category':'UNKNOWN_TOOL_FAILURE'}))
        self.assertEqual(result['last_command']['name'],'apple-bind')
        self.assertEqual(result['last_command']['tool_categories'],['COMPILER'])
    def test_unknown_command_rejected_and_cannot_reuse_receipt(self):
        self.assertIsNone(native.safe_last_command('/PRIVATE/token',1,1,'FAILED','NONZERO_EXIT'))
        row=self.row();row['name']='PRIVATE'
        with self.assertRaises(ValueError):outer.command_summary(row,{})
    def test_no_raw_values_escape(self):
        raw=b'clang: error: /PRIVATE/token secret=PRIVATE\nmodule lookup disabled by GOPROXY=off'
        categories=native.classify_tool_output(raw)
        self.assertEqual(categories,['COMPILER','GO_MODULE_OFFLINE'])
        row=self.row();row['tool_categories']=categories;row['argv']='PRIVATE';row['env']='PRIVATE';row['raw']=raw.decode()
        self.assertNotIn('PRIVATE',json.dumps(outer.command_summary(row,{})))
    def test_oversized_or_unknown_output_is_bounded_unknown(self):
        for raw in (b'x'*(8*1024*1024+1),b'PRIVATE',None):
            self.assertEqual(native.classify_tool_output(raw),['UNKNOWN_TOOL_FAILURE'])
    def test_fixed_classification_families(self):
        for raw,expected in [(b'missing go.sum entry','GO_MODULE_SUM'),(b'updates to go.mod needed','GO_MODULE_UPDATE'),(b'requires go >=','GO_VERSION'),(b'xcrun: error: PRIVATE','SDK_TOOL'),(b'gomobile: PRIVATE','GOMOBILE_BIND')]:
            self.assertIn(expected,native.classify_tool_output(raw))
        self.assertEqual(native.classify_gate_error(ValueError('input26 selected graph changed')),'GRAPH_MISMATCH')
        self.assertEqual(native.classify_gate_error(ValueError('PRIVATE')),'UNKNOWN_TOOL_FAILURE')
    def test_hostile_exception_text_not_invoked(self):
        class Hostile(Exception):
            def __str__(self): raise RuntimeError('PRIVATE')
        self.assertEqual(native.classify_gate_error(Hostile('PRIVATE')),'UNKNOWN_TOOL_FAILURE')
    def test_host_output_not_tool_projected(self):
        row=self.row();row['name']='archive-tests'
        with self.assertRaises(ValueError):outer.command_summary(row,{})
    def test_malformed_fields_and_false_pass_rejected(self):
        for key,value in [('tool_categories',['PRIVATE']),('tool_categories',['COMPILER']*10),('tool_categories','COMPILER'),('exit_code',True),('elapsed_seconds',float('nan')),('failed_tests',['PRIVATE']),('failure_categories',['TEST_FAILURE']),('outcome','PASS')]:
            row=self.row();row[key]=value
            with self.assertRaises(ValueError):outer.command_summary(row,{})
    def test_gate_category_is_enum_only(self):
        result=outer.native_summary(None,Mock(return_value={'status':'FAILED','native_runtime_test':False,'failed_stage':'artifact-inspection','gate_category':'PRIVATE'}))
        self.assertEqual(result['gate_category'],'UNKNOWN_TOOL_FAILURE')
        self.assertNotIn('PRIVATE',json.dumps(result))

if __name__=='__main__':unittest.main()
