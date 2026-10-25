"""Static/mocked public diagnostic projections; no native processes or network."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

SPEC=importlib.util.spec_from_file_location('host_projection_diagnostics',Path(__file__).resolve().parents[1]/'ios/diagnostics.py')
d=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(d)
CANARY='PRIVATE_DO_NOT_EMIT'

class HostCommandProjectionTests(unittest.TestCase):
    def row(self):
        return {'name':'archive-tests','exit_code':1,'elapsed_seconds':12.5,'outcome':'FAILED',
                'failure_kind':'NONZERO_EXIT','failed_tests':['TestStrict'],
                'failure_categories':['TEST_FAILURE']}
    def project(self,row):
        return d.native_summary(None,Mock(return_value={'status':'FAILED','native_runtime_test':False,
            'failed_stage':'new-policy-host-tests','last_command':row,'secret':CANARY}),
            trusted_tests={'archive':frozenset({'TestStrict','FuzzArchiveOpen'}),'archivebridge':frozenset({'TestBridge'})})
    def invalid(self,row):
        got=self.project(row)
        self.assertEqual(got['availability'],'present')
        self.assertEqual(got['failed_stage'],'new-policy-host-tests')
        self.assertEqual(got['last_command'],{'availability':'invalid'})
        self.assertNotIn(CANARY,json.dumps(got))
    def test_exact_failure_and_drop_unknown_values(self):
        row=self.row();row.update(Output=CANARY,argv=[CANARY],path=CANARY)
        got=self.project(row)
        self.assertEqual(got['last_command'],self.row())
        self.assertNotIn(CANARY,json.dumps(got))
    def test_unknown_command_or_category_is_not_printed(self):
        for field,value in [('name',CANARY),('failure_kind',CANARY),('failure_categories',[CANARY])]:
            row=self.row();row[field]=value;self.invalid(row)
    def test_only_exact_top_level_package_names(self):
        for names in [[CANARY],['TestStrict/'+CANARY],['TestBridge'],['TestStrict','TestStrict']]:
            row=self.row();row['failed_tests']=names;self.invalid(row)
    def test_numeric_bounds_and_bool_rejected(self):
        for field,values in [('exit_code',[True,1.5,256,-256,CANARY]),('elapsed_seconds',[True,-1,3601,float('inf'),float('nan'),CANARY])]:
            for value in values:
                row=self.row();row[field]=value;self.invalid(row)
    def test_null_exit_with_timeout_stays_failed(self):
        row=self.row();row.update(exit_code=None,failure_kind='TIMEOUT',failed_tests=[],failure_categories=['NO_TEST_FAILURE_EVENT'])
        self.assertEqual(self.project(row)['last_command'],row)
    def test_nonzero_without_parsed_test_remains_failed(self):
        row=self.row();row.update(failed_tests=[],failure_categories=['NO_TEST_FAILURE_EVENT'])
        self.assertEqual(self.project(row)['last_command']['outcome'],'FAILED')
    def test_success_requires_zero_none_no_failures(self):
        good=self.row();good.update(outcome='PASS',exit_code=0,failure_kind='NONE',failed_tests=[],failure_categories=[])
        self.assertEqual(self.project(good)['last_command'],good)
        for field,value in [('exit_code',1),('failure_kind','TIMEOUT'),('failed_tests',['TestStrict']),('failure_categories',['TEST_FAILURE'])]:
            row=copy.deepcopy(good);row[field]=value;self.invalid(row)
    def test_failed_none_and_invalid_containers_rejected(self):
        row=self.row();row['failure_kind']='NONE';self.invalid(row)
        for row in [None,[],True,CANARY]:self.invalid(row)
        for field in ['name','outcome','failure_kind','failed_tests','failure_categories']:
            row=self.row();row[field]={};self.invalid(row)
    def test_list_bounds_and_duplicates(self):
        for field,value in [('failed_tests',['TestStrict']*33),('failure_categories',['TEST_FAILURE']*6),('failure_categories',['TEST_FAILURE']*2)]:
            row=self.row();row[field]=value;self.invalid(row)
    def test_optional_detail_invalid_cannot_mask_primary_stage(self):
        row=self.row();del row['elapsed_seconds'];self.invalid(row)
    def test_no_snapshot_does_not_admit_test_names(self):
        value={'status':'FAILED','native_runtime_test':False,'failed_stage':'new-policy-host-tests','last_command':self.row()}
        got=d.native_summary(None,Mock(return_value=value))
        self.assertEqual(got['last_command'],{'availability':'invalid'})

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.hashes={}
        for package,paths in d.TEST_SOURCES.items():
            for n,path in enumerate(paths):
                p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True)
                data=f'package p\nfunc TestPublic{package}{n}(t *testing.T) {{}}\n'.encode()
                p.write_bytes(data);self.hashes[path]=hashlib.sha256(data).hexdigest()
    def test_snapshot_is_immutable_and_bound_before_child(self):
        got=d.snapshot_test_names(self.root,self.hashes)
        p=self.root/'archive/archive_test.go';p.write_text('func Test'+CANARY+'(t *testing.T) {}')
        self.assertNotIn('Test'+CANARY,got['archive'])
        with self.assertRaises(TypeError):got['archive']=frozenset()
        with self.assertRaises(AttributeError):got['archive'].add(CANARY)
    def test_changed_source_missing_hash_or_symlink_fails(self):
        for hashes in [{},dict(self.hashes,**{'archive/archive_test.go':'0'*64})]:
            with self.assertRaises(ValueError):d.snapshot_test_names(self.root,hashes)
        p=self.root/'archive/archive_test.go';data=p.read_bytes();p.unlink()
        target=self.root/'target';target.write_bytes(data);p.symlink_to(target)
        with self.assertRaises(OSError):d.snapshot_test_names(self.root,self.hashes)
    def test_public_top_level_only_not_runtime_subtests(self):
        p=self.root/'archive/archive_test.go'
        data=b'package p\nfunc TestSafe(t *testing.T) { t.Run("'+CANARY.encode()+b'", nil) }\nfunc FuzzSafe(f *testing.F) {}\n'
        p.write_bytes(data);self.hashes['archive/archive_test.go']=hashlib.sha256(data).hexdigest()
        got=d.snapshot_test_names(self.root,self.hashes)
        self.assertIn('TestSafe',got['archive']);self.assertIn('FuzzSafe',got['archive'])
        self.assertNotIn(CANARY,str(got))

if __name__=='__main__':unittest.main()
