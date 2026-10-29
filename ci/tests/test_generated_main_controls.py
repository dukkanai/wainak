"""Synthetic pinned-upstream control fixtures; no Go/Apple execution."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ci/native'))
import native_runtime as runtime
import host_diagnostics as diagnostics
spec=importlib.util.spec_from_file_location('graph_outer',ROOT/'ci/ios/diagnostics.py')
outer=importlib.util.module_from_spec(spec);spec.loader.exec_module(outer)

class GeneratedMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name).resolve();self.binding=self.work/'binding';self.binding.mkdir()
        self.target=self.work/'tmp/gomobile-fixture/ios/src-arm64';self.target.mkdir(parents=True)
        (self.target/'go.mod').write_text('module gobind\ngo 1.27.3\n')
        self.local={'wainek.local/archivebridge':self.work/'archivebridge','wainek.local/historyarchive':self.work/'archive'}
        self.controls={'Module':{'Path':'gobind'},'Go':'1.27.3','Replace':[{'Old':{'Path':name},'New':{'Path':str(path)}} for name,path in {**self.local,'wainek.local/cibinding':self.binding}.items()]}
        self.rows=[{'Path':'gobind','Main':True}]
    def run_graph(self,**kwargs):
        fake=Mock();fake.work=self.work
        fake.run.side_effect=[b'\n'.join(json.dumps(row).encode() for row in self.rows),json.dumps(self.controls).encode()]
        return runtime.inspect_graph(fake,Path('/not-executed'),self.target,{},kwargs.pop('name','target-0'),set(),self.local,**kwargs)
    def test_pinned_upstream_fixture_explains_original_rejection(self):
        fixture=json.loads((ROOT/'ci/native/fixtures/upstream-main-replacement.json').read_text())
        self.assertEqual(fixture['upstream_commit'],'197770444867')
        main=fixture['original_main'];self.assertTrue(main['Main']);self.assertFalse(main.get('Version'));self.assertFalse(main.get('Replace'))
        self.assertEqual(main['Path'],'wainek.local/cibinding')
        # Pinned upstream emits this control even though main has no version.
        self.assertEqual(self.controls['Replace'][-1]['Old']['Path'],main['Path'])
        with self.assertRaisesRegex(Exception,'unapproved replacement'):self.run_graph()
        self.assertEqual(self.run_graph(generated_main=self.binding)['controls'],self.controls)
    def test_generated_both_targets_accept_exact_owned_control(self):
        for name in ('target-0','target-1'):self.run_graph(name=name,generated_main=self.binding)
    def test_control_only_not_selected_dependency(self):
        self.rows.append({'Path':'wainek.local/cibinding','Version':'v0.0.0','Replace':{'Dir':str(self.binding)}})
        with self.assertRaisesRegex(Exception,'owned main module selected'):self.run_graph(generated_main=self.binding)
    def test_generated_main_must_be_unique_gobind(self):
        for rows in ([],[{'Path':'wainek.local/cibinding','Main':True}],[{'Path':'gobind','Main':True}]*2):
            self.rows=rows
            with self.assertRaisesRegex(Exception,'generated target main module invalid'):self.run_graph(generated_main=self.binding)
    def test_non_generated_cwd_cannot_enable_exception(self):
        self.target=self.binding
        with self.assertRaisesRegex(Exception,'context invalid'):self.run_graph(generated_main=self.binding)
    def test_input_graph_cannot_enable_exception(self):
        for name in ('binding-input','tool-input','target-2'):
            with self.assertRaisesRegex(Exception,'context invalid'):self.run_graph(name=name,generated_main=self.binding)
    def test_arbitrary_or_relative_binding_path_rejected(self):
        for path in (self.work,self.work/'other',Path('binding'),self.work/'tmp/../binding'):
            with self.assertRaisesRegex(Exception,'path invalid'):self.run_graph(generated_main=path)
    def test_binding_symlink_rejected(self):
        self.binding.rmdir();other=self.work/'other';other.mkdir();self.binding.symlink_to(other,target_is_directory=True)
        with self.assertRaisesRegex(Exception,'path invalid'):self.run_graph(generated_main=self.binding)
    def test_parent_symlink_rejected(self):
        alias=self.work/'alias';real=self.work/'real';real.mkdir();(real/'binding').mkdir();alias.symlink_to(real,target_is_directory=True)
        self.work=alias
        with self.assertRaisesRegex(Exception,'(path|context) invalid'):self.run_graph(generated_main=alias/'binding')
    def test_unknown_escaped_or_symlink_control_path_rejected(self):
        for path in ('/PRIVATE','../binding',str(self.work/'tmp/../binding')):
            self.controls['Replace'][-1]['New']['Path']=path
            with self.assertRaisesRegex(Exception,'unapproved replacement'):self.run_graph(generated_main=self.binding)
    def test_duplicate_controls_rejected(self):
        self.controls['Replace'].append(copy.deepcopy(self.controls['Replace'][-1]))
        with self.assertRaisesRegex(Exception,'duplicate replacement'):self.run_graph(generated_main=self.binding)
    def test_versioned_controls_rejected(self):
        for side in ('Old','New'):
            self.controls['Replace'][-1][side]['Version']='v0.0.0'
            with self.assertRaisesRegex(Exception,'versioned replacement'):self.run_graph(generated_main=self.binding)
            self.controls['Replace'][-1][side].pop('Version')
    def test_toolchain_and_exclude_still_rejected(self):
        for key,value in [('Toolchain','go1.99.0'),('Exclude',[{'Path':'PRIVATE'}])]:
            self.controls[key]=value
            with self.assertRaisesRegex(Exception,'unapproved graph controls'):self.run_graph(generated_main=self.binding)
            self.controls.pop(key)
    def test_public_module_versions_still_rejected(self):
        self.rows.append({'Path':'golang.org/x/crypto','Version':'v99.0.0'})
        with self.assertRaisesRegex(Exception,'unapproved public module'):self.run_graph(generated_main=self.binding)
    def test_ordinary_local_controls_still_work(self):
        self.controls['Replace'].pop();self.run_graph()
    def test_graph_reason_enum_covers_every_graph_source_branch(self):
        self.assertEqual(diagnostics.GRAPH_REASONS,outer.GRAPH_REASONS)
        for message,reason in diagnostics.GRAPH_MESSAGES.items():
            self.assertEqual(diagnostics.graph_failure_reason(ValueError(message)),reason)
            row=outer.native_summary(None,Mock(return_value={'status':'FAILED','native_runtime_test':False,'failed_stage':'unmodified-upstream-apple-bind','gate_category':'GRAPH_MISMATCH','graph_reason':reason}))
            self.assertEqual(row['graph_reason'],reason)
    def test_unknown_graph_details_not_emitted(self):
        row=outer.native_summary(None,Mock(return_value={'status':'FAILED','native_runtime_test':False,'failed_stage':'unmodified-upstream-apple-bind','gate_category':'GRAPH_MISMATCH','graph_reason':'/PRIVATE/token'}))
        self.assertNotIn('graph_reason',row);self.assertNotIn('PRIVATE',json.dumps(row))

if __name__=='__main__':unittest.main()
