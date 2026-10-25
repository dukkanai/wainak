"""Mocked source-only harness tests: no compiler, network, native child or signals."""
import io
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import Mock, patch
import native_runtime as r
import host_diagnostics as d

class BudgetTests(unittest.TestCase):
    def make(self):
        runtime=r.Runtime.__new__(r.Runtime)
        runtime.repo=Path('/not-read');runtime.cancelled=False;runtime.reserved=0
        runtime.last_audit=None;runtime.last_aggregate=0;runtime.resource_final_audit_failed=False
        runtime.lock={'limits':{'aggregate_bytes':1000,'minimum_free_bytes':100}}
        return runtime
    def test_no_recursive_scan_per_member(self):
        runtime=self.make()
        with patch.object(r.time,'monotonic',return_value=0),patch.object(r,'byte_size',return_value=10) as size,patch.object(r.shutil,'disk_usage',return_value=Mock(free=10000)):
            for _ in range(1000):runtime.guard()
            self.assertEqual(size.call_count,4)
            runtime.guard(force=True);self.assertEqual(size.call_count,8)
    def test_periodic_growth_detected(self):
        runtime=self.make();clock=[0]
        with patch.object(r.time,'monotonic',side_effect=lambda:clock[0]),patch.object(r,'byte_size',return_value=10) as size,patch.object(r.shutil,'disk_usage',return_value=Mock(free=10000)):
            runtime.guard();size.return_value=300;clock[0]=2
            with self.assertRaises(r.BuildFailure):runtime.guard()
    def test_reserved_payload_cannot_exceed_aggregate(self):
        runtime=self.make()
        with patch.object(r,'byte_size',return_value=100),patch.object(r.shutil,'disk_usage',return_value=Mock(free=10000)):
            with self.assertRaises(r.BuildFailure):
                with runtime.reservation(601):self.fail('must fail before writing')
            self.assertEqual(runtime.reserved,0)
    def test_reserved_payload_preserves_free_floor(self):
        runtime=self.make()
        with patch.object(r,'byte_size',return_value=0),patch.object(r.shutil,'disk_usage',return_value=Mock(free=600)):
            with self.assertRaises(r.BuildFailure):
                with runtime.reservation(501):self.fail('must fail before writing')
    def test_known_write_consume_and_final_audit(self):
        runtime=self.make()
        with patch.object(r,'byte_size',return_value=0) as size,patch.object(r.shutil,'disk_usage',return_value=Mock(free=10000)):
            with self.assertRaises(r.BuildFailure):
                with runtime.reservation(100):
                    runtime.consume(70);self.assertEqual(runtime.reserved,30)
                    with self.assertRaises(ValueError):runtime.consume(31)
                    size.return_value=300
            # final full audit detects unrelated growth; never silently discards it.
    def test_final_audit_preserves_original_error(self):
        runtime=self.make()
        with patch.object(r,'byte_size',return_value=0) as size,patch.object(r.shutil,'disk_usage',return_value=Mock(free=10000)):
            primary=RuntimeError('private-not-printed')
            try:
                with runtime.reservation(100):size.side_effect=PermissionError();raise primary
            except RuntimeError as error:self.assertIs(error,primary)
            else:self.fail('original error lost')
            self.assertTrue(runtime.resource_final_audit_failed)
    def test_cancel_check_never_waits_for_periodic_audit(self):
        runtime=self.make();runtime.cancelled=True;runtime.last_audit=0
        with patch.object(r,'byte_size') as size:
            with self.assertRaises(r.BuildFailure):runtime.guard()
            size.assert_not_called()

class ProjectionTests(unittest.TestCase):
    def test_output_paths_and_subtests_not_exposed(self):
        events=[{'Action':'output','Test':'TestKnown/private','Output':'PRIVATE_KEY_CANARY'},
                {'Action':'fail','Test':'TestKnown/private'}, {'Action':'fail','Test':'Unknown_PRIVATE'}]
        for event in events:event['Package']='wainak.local/historyarchive'
        result,failed,valid=d.project_go_events(b''.join(json.dumps(e).encode()+b'\n' for e in events),{'TestKnown'},'wainak.local/historyarchive')
        self.assertTrue(failed);self.assertEqual(result['failed_tests'],['TestKnown'])
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('PRIVATE',json.dumps(result))
    def test_malformed_incomplete_and_depth_are_value_free(self):
        result,_,_=d.project_go_events(b'['*10000+b'0'+b']'*10000,{'TestKnown'},'wainak.local/historyarchive')
        self.assertEqual(set(result['failure_categories']),{'MALFORMED_TEST_JSON','INCOMPLETE_TEST_JSON'})
    def test_terminal_pass_is_required_and_fail_event_contradiction_rejected(self):
        pkg='wainak.local/historyarchive'
        for events,valid in [([{'Action':'pass','Package':pkg}],True),
                            ([{'Action':'run','Package':pkg,'Test':'TestKnown'}],False),
                            ([{'Action':'fail','Package':pkg,'Test':'TestKnown'},{'Action':'pass','Package':pkg}],False),
                            ([{'Action':'pass','Package':pkg},{'Action':'output','Package':pkg,'Output':'private'}],False)]:
            result,_,ok=d.project_go_events(b''.join(json.dumps(e).encode()+b'\n' for e in events),{'TestKnown'},pkg)
            self.assertEqual(ok,valid)
    def test_json_event_count_depth_encoding_and_duplicate_bound(self):
        pkg='wainak.local/historyarchive'
        for raw in [b'{}\n'*10001, b'['*33+b'0'+b']'*33+b'\n',
                    '{"Action":"pass","Package":"wainak.local/historyarchive"}'.encode('utf-16')+b'\n',
                    b'{"Action":"pass","Action":"pass","Package":"wainak.local/historyarchive"}\n']:
            result,_,ok=d.project_go_events(raw,{'TestKnown'},pkg)
            self.assertFalse(ok);self.assertIn('MALFORMED_TEST_JSON',result['failure_categories'])
    def test_unknown_command_not_public(self):
        self.assertIsNone(d.safe_last_command('PRIVATE',0,1,'PASS','NONE'))
    def test_numeric_fields_are_bounded(self):
        row=d.safe_last_command('archive-tests',True,float('nan'),'bad','bad')
        self.assertIsNone(row['exit_code']);self.assertEqual(row['elapsed_seconds'],3600)
        self.assertEqual(row['outcome'],'FAILED');self.assertEqual(row['failure_kind'],'OTHER')
    def test_only_pinned_public_top_level_declarations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'archive').mkdir();(root/'archivebridge').mkdir();hashes={}
            for relative in ('archive/archive_test.go','archive/interop_test.go','archivebridge/bridge_test.go'):
                p=root/relative;p.write_text('func TestPublic(t *testing.T) {}\n// func TestFake(t) {}\n')
                hashes[relative]=hashlib.sha256(p.read_bytes()).hexdigest()
            (root/'archive/private_test.go').write_text('func TestPrivate(t *testing.T) {}\n')
            self.assertEqual(d.declared_tests(root,hashes)['wainak.local/historyarchive'],{'TestPublic'})
            hashes['archive/archive_test.go']='0'*64
            with self.assertRaises(ValueError):d.declared_tests(root,hashes)
    def test_unbounded_or_nonstring_test_field_rejected(self):
        pkg='wainak.local/historyarchive'
        for test in ([],{},1,'T'*513):
            raw=json.dumps({'Action':'fail','Package':pkg,'Test':test}).encode()+b'\n'
            result,_,ok=d.project_go_events(raw,{'TestKnown'},pkg)
            self.assertFalse(ok);self.assertIn('MALFORMED_TEST_JSON',result['failure_categories'])

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'logs').mkdir()
        self.rt=r.Runtime.__new__(r.Runtime);self.rt.work=self.root;self.rt.sequence=0
        self.rt.guard=Mock();self.rt.test_names={'wainak.local/historyarchive':frozenset({'TestKnown'})};self.rt.last_command=None;self.rt.commands=[]
        self.rt.lock={'limits':{'process_seconds':1200,'process_output_bytes':1024}}
        self.proc=Mock();self.proc.returncode=0;self.proc.poll.return_value=0;self.proc.wait.return_value=0
        self.selector=Mock();self.selector.get_map.return_value={}
        self.selector.__enter__=Mock(return_value=self.selector);self.selector.__exit__=Mock(return_value=False)
        self.enterContext(patch.object(r.subprocess,'Popen',return_value=self.proc))
        self.enterContext(patch.object(r.selectors,'DefaultSelector',return_value=self.selector))
    def test_nonzero_no_json_is_failed_without_raw_log(self):
        self.proc.returncode=1;self.proc.wait.return_value=1
        with self.assertRaises(r.BuildFailure):self.rt.run(['/not-run'],self.root,{},'archive-tests',public_output=False,go_json=True)
        row=self.rt.last_command;self.assertEqual(row['outcome'],'FAILED')
        self.assertEqual(row['failure_kind'],'NONZERO_EXIT');self.assertIn('NO_TEST_FAILURE_EVENT',row['failure_categories'])
        self.assertEqual(list((self.root/'logs').iterdir()),[])
    def test_expired_shared_deadline_never_spawns(self):
        with patch.object(r.subprocess,'Popen') as spawn:
            with self.assertRaises(r.BuildFailure):self.rt.run(['/not-run'],self.root,{},'archive-tests',seconds=-1)
            spawn.assert_not_called()
        self.assertEqual(self.rt.last_command['failure_kind'],'TIMEOUT')
    def test_primary_survives_cleanup_permission(self):
        self.proc.wait.side_effect=ValueError('PRIVATE');self.proc.poll.return_value=None
        self.proc.terminate.side_effect=PermissionError('PRIVATE')
        with self.assertRaises(ValueError):self.rt.run(['/not-run'],self.root,{},'archive-tests',public_output=False)
        self.assertNotIn('PRIVATE',json.dumps(self.rt.last_command))
    def test_zero_exit_incomplete_json_is_not_success(self):
        with self.assertRaises(r.BuildFailure):self.rt.run(['/not-run'],self.root,{},'archive-tests',public_output=False,go_json=True)
        self.assertEqual(self.rt.last_command['outcome'],'FAILED')
        self.assertEqual(self.rt.commands[-1]['outcome'],'FAILED')
    def test_log_permission_marks_both_records_failed(self):
        real=Path.write_bytes
        def write(path, data):
            if path.suffix=='.log': raise PermissionError('PRIVATE')
            return real(path,data)
        with patch.object(Path,'write_bytes',write):
            with self.assertRaises(r.BuildFailure):self.rt.run(['/not-run'],self.root,{},'archive-tests')
        self.assertEqual(self.rt.last_command['outcome'],'FAILED')
        self.assertEqual(self.rt.commands[-1]['outcome'],'FAILED')
        saved=json.loads((self.root/'commands.json').read_text())
        self.assertEqual(saved[-1]['outcome'],'FAILED')
    def test_final_budget_audit_follows_result_write(self):
        import inspect
        source=inspect.getsource(r.finalize_native_result)
        self.assertLess(source.index("audit('RESULT_WRITE'"),source.index("audit('RESOURCE_GUARD'"))
        self.assertIn("status='FAILED'",source)
    def test_final_source_and_write_errors_preserve_primary(self):
        self.rt.stage='new-policy-host-tests';self.rt.resource_final_audit_failed=False
        result={'status':'FAILED','failed_stage':self.rt.stage};primary=ValueError('PRIVATE')
        with patch.object(r,'sha',side_effect=PermissionError('PRIVATE')):
            r.finalize_native_result(self.rt,self.root,self.root,result,{'archive/source.go':'x'},{},primary)
        saved=json.loads((self.root/'result.json').read_text())
        self.assertEqual(saved['status'],'FAILED');self.assertIn('SOURCE_GUARD',saved['final_audit_errors'])
        self.assertNotIn('PRIVATE',json.dumps(saved))
    def test_final_resource_failure_cannot_leave_pass_result(self):
        self.rt.stage='artifact-inspection';self.rt.resource_final_audit_failed=False
        self.rt.guard.side_effect=r.BuildFailure('workspace budget exceeded')
        result={'status':'PASS_UNSIGNED_NATIVE_BUILD_ONLY'}
        with patch.object(r,'sha',return_value='public-hash'):
            with self.assertRaises(r.BuildFailure):r.finalize_native_result(self.rt,self.root,self.root,result,{},{},None)
        saved=json.loads((self.root/'result.json').read_text())
        self.assertEqual(saved['status'],'FAILED');self.assertIn('RESOURCE_GUARD',saved['final_audit_errors'])
    def test_unknown_later_command_cannot_reuse_old_host_result(self):
        self.rt.last_command={'name':'archive-tests','outcome':'PASS'}
        self.rt.run(['/not-run'],self.root,{},'apple-bind')
        self.assertIsNone(self.rt.last_command)
    def test_runtime_env_has_no_external_compiler_cache_authority(self):
        age=self.root/'age';age.write_bytes(b'public-binary-fixture')
        env=r.runtime_test_env({'GOCACHE':'/outside','GOMODCACHE':'/outside','GOTMPDIR':'/outside'},self.root,age)
        for key in ('GOCACHE','GOMODCACHE','GOTMPDIR'):self.assertNotIn(key,env)
        self.assertEqual(env['HOME'],str(self.root/'home'));self.assertEqual(env['TMPDIR'],str(self.root/'tmp'))
    def test_host_compile_and_test_share_180s_source_guard(self):
        import inspect
        source=inspect.getsource(r.test_host_policy)
        self.assertIn('deadline=time.monotonic()+180',source)
        self.assertEqual(source.count('seconds=deadline-time.monotonic()'),2)
        self.assertIn("'tool','test2json'",source)
        self.assertIn("[go,'test','-json','-run=^$'",source)
        self.assertIn("'GOMODCACHE']==cache_after['GOMODCACHE']",source)

class HostBoundaryTests(unittest.TestCase):
    def test_cache_inventory_rejects_special_and_symlink_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);env={name:str(root/name) for name in ('GOCACHE','GOMODCACHE','GOTMPDIR')}
            for path in env.values():Path(path).mkdir()
            fifo=Path(env['GOCACHE'])/'fifo';os.mkfifo(fifo)
            with self.assertRaises(ValueError):r.cache_inventory(env)
            fifo.unlink();fifo.symlink_to(root)
            with self.assertRaises(ValueError):r.cache_inventory(env)
            fifo.unlink();fifo.write_bytes(b'public-cache')
            self.assertEqual(len(r.cache_inventory(env)['GOCACHE']),1)
    def test_real_python_orchestration_runtime_and_fuzz_paths_without_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/'repo';work=repo/'.ci-work/native';work.mkdir(parents=True)
            (work/'bin').mkdir()
            for module in ('archive','archivebridge'):
                (repo/module).mkdir();(repo/module/'source.go').write_text('package fixture\n')
            calls=[]
            class Fake:
                def __init__(self):self.repo=repo;self.work=work;self.resource_final_audit_failed=False
                def run(self,args,cwd,env,name,**kwargs):
                    calls.append((args,Path(cwd),dict(env),name,kwargs))
                    if name=='age-cli-build': (work/'bin/age').write_bytes(b'public-cli')
                    if name.endswith('-test-compile'):Path(args[args.index('-o')+1]).write_bytes(b'public-test')
                    return b''
            env={key:str(work/key) for key in ('GOCACHE','GOMODCACHE','GOTMPDIR')}
            lock=json.loads((Path(__file__).parent/'lock.json').read_text())
            empty={key:{} for key in env}
            with patch.object(r,'cache_inventory',return_value=empty):r.test_host_policy(Fake(),Path('/not-run/go'),work,env,lock)
            self.assertEqual({c[3] for c in calls},d.HOST_COMMANDS)
            for args,cwd,child,name,kwargs in calls:
                if name.endswith('-tests'):
                    self.assertEqual(child['HOME'],str(cwd.parent/'home'));self.assertEqual(child['TMPDIR'],str(cwd.parent/'tmp'))
                    self.assertEqual(child['WAINAK_ARCHIVE_SCAN_ROOT'],str(cwd.parent))
                    self.assertEqual(cwd.name,'module')
                    for key in env:self.assertNotIn(key,child)
                    self.assertTrue(kwargs['go_json']);self.assertFalse(kwargs['public_output'])
                if name.startswith('fuzz-'):
                    self.assertEqual(child['GOTMPDIR'],env['GOTMPDIR'])
                    self.assertEqual(cwd.parent/'home',Path(child['HOME']))
                    self.assertEqual(kwargs['seconds'],60)

    def test_each_compiled_runtime_resolves_all_relative_public_sources(self):
        # Exercise the actual orchestration with fake compilers; old parent cwd
        # deterministically fails these checks before any ABI assertion can run.
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/'repo';work=repo/'.ci-work/native';(work/'bin').mkdir(parents=True)
            sources={'archive':{'archive.go':b'package archive\n','archive_test.go':b'package archive\n','interop_test.go':b'package archive\n'},
                     'archivebridge':{'bridge.go':b'package archivebridge\n','bridge_test.go':b'package archivebridge\n'}}
            for module,files in sources.items():
                (repo/module).mkdir()
                for name,data in files.items():(repo/module/name).write_bytes(data)
            observed=[]
            class Fake:
                def __init__(self):self.repo=repo;self.work=work;self.resource_final_audit_failed=False
                def run(self,args,cwd,env,name,**kwargs):
                    if name=='age-cli-build':(work/'bin/age').write_bytes(b'public-cli')
                    if name.endswith('-test-compile'):Path(args[args.index('-o')+1]).write_bytes(b'public-test')
                    if name in ('archive-tests','archivebridge-tests'):
                        module=name.removesuffix('-tests');cwd=Path(cwd);root=Path(env['WAINAK_ARCHIVE_SCAN_ROOT'])
                        assert cwd==root/'module' and cwd.is_relative_to(root)
                        assert Path(env['HOME'])==root/'home' and Path(env['TMPDIR'])==root/'tmp'
                        for relative,data in sources[module].items():
                            assert (cwd/relative).is_file() and (cwd/relative).read_bytes()==data
                        assert not (root/next(iter(sources[module]))).exists()
                        observed.append(module)
                    return b''
            env={key:str(work/key) for key in ('GOCACHE','GOMODCACHE','GOTMPDIR')}
            lock=json.loads((Path(__file__).parent/'lock.json').read_text());empty={key:{} for key in env}
            with patch.object(r,'cache_inventory',return_value=empty):r.test_host_policy(Fake(),Path('/not-run/go'),work,env,lock)
            self.assertEqual(observed,['archive','archivebridge'])

if __name__=='__main__':unittest.main()
