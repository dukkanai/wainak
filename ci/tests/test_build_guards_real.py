"""Real owned-filesystem/harmless-child regressions; no compiler or network."""
import contextlib
import errno
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

CI=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(CI/'native'),str(CI/'ios'),str(CI)]
import build_guards as g
import native_runtime as n
import host_diagnostics as h
import check_static as c
spec=importlib.util.spec_from_file_location('guard_ios_build',CI/'ios/build.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
import diagnostics as d

class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def test_absent_optional_root(self):
        self.assertEqual(g.tree_size(self.root/'absent'),0)
    def test_metadata_and_payload_counted_by_both_drivers(self):
        (self.root/'d').mkdir();(self.root/'d'/'f').write_bytes(b'x'*100)
        expected=sum(p.lstat().st_size for p in [self.root,self.root/'d',self.root/'d'/'f'])
        self.assertEqual(n.byte_size(self.root),expected);self.assertEqual(b.size(self.root),expected)
    def test_real_denied_subdirectory_fails_closed_for_both_drivers(self):
        self.assertNotEqual(os.geteuid(),0,'run this suite as the unprivileged build user')
        denied=self.root/'denied';denied.mkdir();(denied/'payload').write_bytes(b'x'*4096);denied.chmod(0)
        try:
            for function in (n.byte_size,b.size):
                with self.assertRaises(PermissionError):function(self.root)
        finally:denied.chmod(0o700)
    def test_real_disappearance_retries_complete_snapshot(self):
        victim=self.root/'vanishing';victim.write_bytes(b'PUBLIC')
        original=g.os.scandir;calls=[]
        @contextlib.contextmanager
        def race(fd):
            with original(fd) as entries: rows=list(entries)
            calls.append(1)
            if len(calls)==1:victim.unlink()
            yield iter(rows)
        with patch.object(g.os,'scandir',race):
            self.assertEqual(g.tree_size(self.root),self.root.stat().st_size)
        self.assertEqual(len(calls),2)
    def test_repeated_disappearance_fails_after_three_attempts(self):
        with patch.object(g.os,'scandir',side_effect=FileNotFoundError(errno.ENOENT,'PRIVATE')) as scan:
            with self.assertRaises(FileNotFoundError):g.tree_size(self.root)
            self.assertEqual(scan.call_count,3)
    def test_eio_never_retried_or_counted_as_zero(self):
        with patch.object(g.os,'scandir',side_effect=OSError(errno.EIO,'PRIVATE')) as scan:
            with self.assertRaises(OSError) as got:g.tree_size(self.root)
            self.assertEqual(got.exception.errno,errno.EIO);self.assertEqual(scan.call_count,1)
    def test_root_link_and_special_file_rejected(self):
        link=self.root/'link';link.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(OSError):g.tree_size(link)
        link.unlink();os.mkfifo(self.root/'fifo')
        with self.assertRaises(OSError):g.tree_size(self.root)
    def test_child_link_counted_but_not_followed(self):
        (self.root/'loop').symlink_to(self.root,target_is_directory=True)
        self.assertEqual(g.tree_size(self.root),self.root.stat().st_size+(self.root/'loop').lstat().st_size)

class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.hashes={'archive/a.go':'unused','archivebridge/b.go':'unused'}
        for relative in self.hashes:
            p=self.root/relative;p.parent.mkdir();p.write_text('package public\n')
    def test_exact_inventory(self):self.assertEqual(c.validate_source_inventory(self.root,self.hashes),set(self.hashes))
    def test_extra_go_assembly_syso_and_directory_rejected(self):
        for name in ('extra.go','extra.s','extra.syso','extra.txt'):
            p=self.root/'archive'/name;p.write_text('PUBLIC')
            try:
                with self.assertRaises(ValueError):c.validate_source_inventory(self.root,self.hashes)
            finally:p.unlink()
        (self.root/'archive'/'nested').mkdir()
        with self.assertRaises(ValueError):c.validate_source_inventory(self.root,self.hashes)
    def test_missing_or_symlink_source_rejected(self):
        p=self.root/'archive'/'a.go';p.unlink()
        with self.assertRaises(ValueError):c.validate_source_inventory(self.root,self.hashes)
        p.symlink_to(self.root/'archivebridge'/'b.go')
        with self.assertRaises(ValueError):c.validate_source_inventory(self.root,self.hashes)
    def test_notices_link_rejected(self):
        (self.root/'archive'/'notices').symlink_to(self.root/'archivebridge',target_is_directory=True)
        with self.assertRaises(ValueError):c.validate_source_inventory(self.root,self.hashes)

class ExecutionProofTests(unittest.TestCase):
    def project(self,events,expected=None):
        package='wainak.local/historyarchive'
        raw=b''.join(json.dumps(dict(Package=package,**row)).encode()+b'\n' for row in events)
        return h.project_go_events(raw,{'TestOne','FuzzOne'},package,expected)
    def test_package_pass_only_is_not_test_evidence(self):
        row,_,ok=self.project([{'Action':'pass'}]);self.assertFalse(ok)
        self.assertIn('MISSING_TEST_EXECUTION',row['failure_categories'])
    def test_run_without_top_level_pass_is_rejected(self):
        row,_,ok=self.project([{'Action':'run','Test':'TestOne'},{'Action':'pass'}],{'TestOne'})
        self.assertFalse(ok)
    def test_full_declared_execution_passes(self):
        events=[]
        for name in ('TestOne','FuzzOne'):events += [{'Action':'run','Test':name},{'Action':'pass','Test':name}]
        row,_,ok=self.project(events+[{'Action':'pass'}]);self.assertTrue(ok)
        self.assertEqual(row['test_counts'],{'expected':2,'run':2,'passed':2,'skipped':0})
    def test_fuzz_target_requires_its_own_execution(self):
        events=[{'Action':'run','Test':'FuzzOne'},{'Action':'pass','Test':'FuzzOne'},{'Action':'pass'}]
        self.assertTrue(self.project(events,{'FuzzOne'})[2])
        self.assertFalse(self.project(events,{'TestOne'})[2])
    def test_skip_and_subtest_skip_fail_closed(self):
        for test in ('TestOne','TestOne/PRIVATE'):
            events=[{'Action':'run','Test':'TestOne'},{'Action':'skip','Test':test},{'Action':'pass','Test':'TestOne'},{'Action':'pass'}]
            row,_,ok=self.project(events,{'TestOne'});self.assertFalse(ok)
            self.assertIn('SKIPPED_TEST',row['failure_categories']);self.assertNotIn('PRIVATE',json.dumps(row))
    def test_duplicate_pass_and_unknown_test_rejected(self):
        for bad in ({'Action':'pass','Test':'TestOne'},{'Action':'run','Test':'PRIVATE'}):
            events=[{'Action':'run','Test':'TestOne'},{'Action':'pass','Test':'TestOne'},bad,{'Action':'pass'}]
            self.assertFalse(self.project(events,{'TestOne'})[2])

class RealChildTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'logs').mkdir()
    def native(self):
        runtime=n.Runtime.__new__(n.Runtime)
        runtime.repo=runtime.work=self.root;runtime.sequence=0;runtime.commands=[];runtime.last_command=None
        runtime.guard=Mock();runtime.test_names={'wainak.local/historyarchive':frozenset({'TestOne'})}
        runtime.lock={'limits':{'process_seconds':10,'process_output_bytes':4096}}
        return runtime
    def args(self,seconds):
        return [sys.executable,'-c',f'import os,time;os.close(1);os.close(2);time.sleep({seconds})']
    def test_native_child_can_finish_more_than_five_seconds_after_eof(self):
        runtime=self.native();start=time.monotonic()
        runtime.run(self.args(5.4),self.root,{},'archive-tests',seconds=10)
        self.assertGreater(time.monotonic()-start,5);self.assertEqual(runtime.last_command['outcome'],'PASS')
    def test_outer_child_can_finish_more_than_five_seconds_after_eof(self):
        runner=b.Runner.__new__(b.Runner)
        runner.work=self.root;runner.flutter=self.root;runner.sources=runner.flutter_sources={'fixture':'hash'}
        runner.sequence=0;runner.results=[];runner.cancelled=False;runner.guard=Mock();runner.env={}
        with patch.object(b,'git_snapshot',return_value={'fixture':'hash'}),patch.object(b,'emit'):
            runner.run('xcode-version',self.args(5.4),cwd=self.root,timeout=10)
        self.assertEqual(runner.results[-1]['status'],'PASS')
    def test_native_closed_output_still_obeys_actual_deadline(self):
        runtime=self.native();start=time.monotonic()
        with self.assertRaises(n.BuildFailure):runtime.run(self.args(5),self.root,{},'archive-tests',seconds=.2)
        self.assertLess(time.monotonic()-start,3);self.assertEqual(runtime.last_command['failure_kind'],'TIMEOUT')
    def test_primary_errno_survives_cleanup_and_outer_projection(self):
        runtime=self.native();error=PermissionError(errno.EACCES,'PRIVATE','/PRIVATE')
        runtime.guard.side_effect=error
        with self.assertRaises(PermissionError):runtime.run(self.args(1),self.root,{},'archive-tests')
        row=runtime.last_command
        self.assertEqual(row['primary'],{'operation':'preflight','type':'PermissionError','errno':errno.EACCES})
        self.assertEqual(d.command_summary(row,{'archive':{'TestOne'}})['primary'],row['primary'])
        self.assertNotIn('PRIVATE',json.dumps(row))
    def test_value_free_error_projection_rejects_arbitrary_fields(self):
        row={'name':'archive-tests','exit_code':-15,'elapsed_seconds':1,'outcome':'FAILED','failure_kind':'SPAWN_OR_IO','failed_tests':[],'failure_categories':[],
             'primary':{'operation':'PRIVATE','type':'OSError','errno':5}}
        with self.assertRaises(ValueError):d.command_summary(row,{})
    def test_success_cannot_claim_skipped_or_missing_tests(self):
        row={'name':'archive-tests','exit_code':0,'elapsed_seconds':1,'outcome':'PASS','failure_kind':'NONE','failed_tests':[],'failure_categories':[],
             'test_counts':{'expected':1,'run':0,'passed':0,'skipped':0}}
        with self.assertRaises(ValueError):d.command_summary(row,{})

if __name__=='__main__':unittest.main()
