import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock
from ci.github import mac_unsigned as g
from ci.testflight import policy as p


class GithubMacPolicy(unittest.TestCase):
    def env(self,root):
        return {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'dukkanai/wainak','GITHUB_EVENT_NAME':'workflow_dispatch',
            'GITHUB_REF':'refs/heads/dev/ios-testflight-internal-20261029','RUNNER_ENVIRONMENT':'github-hosted',
            'RUNNER_OS':'macOS','RUNNER_ARCH':'ARM64','WAINEK_REPOSITORY_VISIBILITY':'public',
            'WAINEK_RUNNER_LABEL':'macos-26','GITHUB_SHA':'a'*40,'WAINEK_EXPECTED_SHA':'a'*40,
            'GITHUB_WORKSPACE':str(root),'PATH':'/usr/bin:/bin','HOME':str(root/'CANARY'),
            'APP_STORE_CONNECT_PRIVATE_KEY':'CANARY','GH_TOKEN':'CANARY'}

    def test_preflight_public_manual_standard_exact_sha_and_disk(self):
        env=self.env(g.ROOT)
        g.preflight(env,'darwin','arm64',10*g.GIB)
        for key in ('GITHUB_REPOSITORY','GITHUB_EVENT_NAME','GITHUB_REF','RUNNER_ENVIRONMENT','RUNNER_ARCH',
                    'WAINEK_REPOSITORY_VISIBILITY','WAINEK_RUNNER_LABEL','GITHUB_SHA','WAINEK_EXPECTED_SHA','GITHUB_WORKSPACE'):
            with self.subTest(key=key),self.assertRaises(p.PolicyError):
                g.preflight({**env,key:'wrong'},'darwin','arm64',10*g.GIB)
        for host,machine,space in [('linux','arm64',10*g.GIB),('darwin','x86_64',10*g.GIB),('darwin','arm64',10*g.GIB-1)]:
            with self.assertRaises(p.PolicyError):g.preflight(env,host,machine,space)

    def test_checkout_alias_is_resolved_and_other_target_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();alias=root/'alias';alias.symlink_to(root,target_is_directory=True)
            other=root/'other';other.mkdir();wrong=root/'wrong';wrong.symlink_to(other,target_is_directory=True)
            with mock.patch.object(g,'ROOT',root):
                for path in (root,alias):g.preflight({**self.env(root),'GITHUB_WORKSPACE':str(path)},'darwin','arm64',10*g.GIB)
                for path in (other,wrong):
                    with self.assertRaisesRegex(p.PolicyError,'github_checkout'):
                        g.preflight({**self.env(root),'GITHUB_WORKSPACE':str(path)},'darwin','arm64',10*g.GIB)

    def test_fresh_work_rejects_existing_and_dangling_symbolic_directories(self):
        for kind in ('directory','dangling'):
            for name in ('work','build'):
                with self.subTest(kind=kind,name=name),tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp).resolve();mobile=root/'mobile';mobile.mkdir();work=root/'work'
                    g.fresh_work(work,mobile)
                    target=work if name=='work' else mobile/'build'
                    if kind=='directory':target.mkdir()
                    else:target.symlink_to(root/'absent',target_is_directory=True)
                    with self.assertRaisesRegex(p.PolicyError,'github_fresh_work'):g.fresh_work(work,mobile)

    def test_resource_guard_keeps_disk_time_and_logical_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with mock.patch.object(g.shutil,'disk_usage',return_value=mock.Mock(free=4*g.GIB-1)):
                with self.assertRaises(p.PolicyError):g.resource_guard(root,root,time.monotonic()+60)
            with self.assertRaises(p.PolicyError):g.resource_guard(root,root,0)
            with mock.patch.object(g.shutil,'disk_usage',return_value=mock.Mock(free=10*g.GIB)), \
                 mock.patch.object(Path,'rglob',return_value=[mock.Mock(is_file=lambda:True,is_symlink=lambda:False,stat=lambda:mock.Mock(st_size=8*g.GIB+1))]):
                with self.assertRaises(p.PolicyError):g.resource_guard(root,root,time.monotonic()+60)

    def test_complete_orchestration_and_each_command_failure(self):
        # Mocks reject extra commands, altered arguments, ordering and credential leaks.
        for fail in (None,*sorted(g.LABELS)):
            with self.subTest(command=fail):self.exercise(fail)

    def exercise(self,fail,post_failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();mobile=root/'apps/mobile';mobile.mkdir(parents=True)
            (root/'ci').mkdir();pins=json.loads((g.ROOT/'ci/ios-host-pins.json').read_text())
            (root/'ci/ios-host-pins.json').write_text(json.dumps(pins))
            work=root/'.ci-github';base=work/'sdk/flutter';app=mobile/'build/ios/iphoneos/Runner.app'
            env=self.env(root);calls=[]
            overlay=mock.Mock(base=base)
            if post_failure:overlay.verify.side_effect=[None,p.PolicyError('sdk_package_config_changed')]
            overlay.command.return_value=[base/'bin/cache/dart-sdk/bin/dart','reviewed_fixture.dart','analyze','--no-pub']
            overlay.report.return_value={'event':'TESTFLIGHT_SDK_DELTA'}
            def prepare(work_arg,run):
                self.assertEqual(work_arg,work)
                run('sdk_head',['git','rev-parse','HEAD'],cwd=base)
                run('sdk_inventory',['git','ls-tree','-rz','HEAD','--',*g.sdk.SOURCE_PATHS],cwd=base)
                run('sdk_provider_dependencies',[base/'bin/cache/dart-sdk/bin/dart','pub','get','--enforce-lockfile','--no-precompile'],cwd=base/'packages/flutter_tools')
                run('sdk_dependencies',[base/'bin/cache/dart-sdk/bin/dart','pub','get','--enforce-lockfile','--no-precompile'],cwd=work/'analyzer_overlay/flutter_tools')
                return overlay
            commands=[
                ('source_commit',['git','rev-parse','HEAD']),('source_clean',['git','status','--porcelain']),
                ('publication',[g.sys.executable,'scripts/check_publication.py']),
                ('preparation',[g.sys.executable,'ci/check_preparation.py']),
                ('regressions',[g.sys.executable,'-m','unittest','discover','-s','ci/tests','-q']),
                ('xcode_version',['/usr/bin/xcodebuild','-version']),
                ('extract_sdk',['/usr/bin/ditto','-x','-k',work/'flutter.zip',work/'sdk']),
                ('flutter_version',['flutter','--version','--machine']),
                ('sdk_head',['git','rev-parse','HEAD']),
                ('sdk_inventory',['git','ls-tree','-rz','HEAD','--',*g.sdk.SOURCE_PATHS]),
                ('sdk_provider_dependencies',[base/'bin/cache/dart-sdk/bin/dart','pub','get','--enforce-lockfile','--no-precompile']),
                ('sdk_dependencies',[base/'bin/cache/dart-sdk/bin/dart','pub','get','--enforce-lockfile','--no-precompile']),
                ('pub_get',['flutter','pub','get','--enforce-lockfile']),('analyze',overlay.command()),
                ('entry_test',['flutter','test','--no-pub','--concurrency=1',*p.DEFINES,'test/testflight_entrypoint_test.dart']),
                ('compile_unsigned',['flutter','build','ios','--release','--no-pub','--no-codesign',*p.DEFINES]),
                ('verify_unsigned',[g.sys.executable,root/'ci/ios/check_unsigned.py',app]),
                ('architecture',['/usr/bin/lipo','-archs',app/'Runner']),
                ('source_unchanged',['git','diff','--exit-code','HEAD','--'])]
            self.assertEqual(set(x[0] for x in commands),g.LABELS)
            def command(argv,**kw):
                self.assertLess(len(calls),len(commands),'unexpected command')
                label,expected=commands[len(calls)];calls.append(label)
                self.assertEqual(list(map(str,argv)),list(map(str,expected)))
                self.assertNotIn('GH_TOKEN',kw['env']);self.assertNotIn('APP_STORE_CONNECT_PRIVATE_KEY',kw['env'])
                self.assertTrue(kw['check']);self.assertIs(kw['group_observer'],g.groups.capture)
                self.assertEqual(kw.get('output_profile'),g.regressions.PROFILE if label=='regressions' else None)
                self.assertGreater(kw['seconds'],0);self.assertLessEqual(kw['seconds'],1200)
                self.assertEqual(kw['cwd'],mobile if label in {'pub_get','analyze','entry_test','compile_unsigned'} else
                    base/'packages/flutter_tools' if label=='sdk_provider_dependencies' else base if label in {'sdk_head','sdk_inventory'} else work/'analyzer_overlay/flutter_tools' if label=='sdk_dependencies' else root)
                kw['diagnostic'].update(failure_kind='NONE',exit_code=0,output_bytes=0,cleanup_failed=False)
                if fail==label:
                    kw['diagnostic'].update(failure_kind='NONZERO_EXIT',exit_code=9)
                    raise RuntimeError('CANARY')
                output=''
                if label=='source_commit':output='a'*40
                elif label=='xcode_version':output='Xcode 26.4.1\nBuild version 17E202\n'
                elif label=='flutter_version':output=json.dumps({field:pins['flutter'][key] for field,key in [
                    ('frameworkVersion','version'),('frameworkRevision','framework_revision'),('engineRevision','engine_revision'),('dartSdkVersion','dart_version')]})
                elif label=='compile_unsigned':app.mkdir(parents=True);(app/'Runner').write_bytes(b'fixture')
                elif label=='verify_unsigned':output='PASS_UNSIGNED_APP'
                elif label=='architecture':output='arm64'
                return subprocess.CompletedProcess([],0,output,'CANARY')
            with mock.patch.object(g,'ROOT',root),mock.patch.dict(g.os.environ,env,clear=True), \
                 mock.patch.object(g.sys,'platform','darwin'),mock.patch.object(g.platform,'machine',return_value='arm64'), \
                 mock.patch.object(g.shutil,'disk_usage',return_value=mock.Mock(free=12*g.GIB)), \
                 mock.patch.object(g,'run_bounded',side_effect=command),mock.patch.object(g.sdk,'prepare',side_effect=prepare), \
                 mock.patch.object(g,'download',side_effect=lambda spec,target,guard:target.write_bytes(b'fixture')), \
                 mock.patch.object(g,'dispose_check',return_value={'status':'PASS_SDK_DISPOSE_MODELS'}),mock.patch('builtins.print') as printed:
                if post_failure:
                    with self.assertRaisesRegex(p.PolicyError,'sdk_package_config_changed'):g.execute()
                elif fail=='regressions':
                    with self.assertRaisesRegex(p.PolicyError,'^github_regressions_classifier_failed$'):g.execute()
                elif fail:
                    with self.assertRaisesRegex(RuntimeError,'CANARY'):g.execute()
                else:g.execute()
            rows=[json.loads(call.args[0]) for call in printed.call_args_list]
            self.assertNotIn('CANARY',json.dumps(rows))
            if post_failure:
                self.assertEqual(calls[-1],'pub_get')
                self.assertEqual(rows[-1]['failure_kind'],'POST_VERIFICATION')
                self.assertEqual(rows[-1]['command_outcome'],'PASS')
                self.assertFalse(any(x.get('status')=='PASS_UNSIGNED_FAKE_UI_COMPILE_ONLY' for x in rows))
            elif fail:
                self.assertEqual(calls[-1],fail)
                self.assertFalse(any(x.get('status')=='PASS_UNSIGNED_FAKE_UI_COMPILE_ONLY' for x in rows))
            else:
                self.assertEqual(calls,[x[0] for x in commands])
                self.assertEqual(rows[-1]['status'],'PASS_UNSIGNED_FAKE_UI_COMPILE_ONLY')
                self.assertIs(rows[-1]['apple_upload'],False)

    def test_download_requires_exact_hash_before_extraction(self):
        pins=json.loads((g.ROOT/'ci/ios-host-pins.json').read_text())['flutter']
        response=mock.MagicMock();response.__enter__.return_value=response
        response.geturl.return_value=pins['archive_url'];response.read.side_effect=[b'CANARY',b'']
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(g.urllib.request,'urlopen',return_value=response):
            with self.assertRaisesRegex(p.PolicyError,'github_sdk_archive_hash'):
                g.download(pins,Path(tmp)/'archive',lambda:None)

    def test_workflow_manual_only_standard_read_permissions_no_secret_or_upload(self):
        # Exact reviewed text blocks guard dispatch isolation without a YAML dependency.
        text=(g.ROOT/'.github/workflows/ci.yml').read_text()
        section=text.split('\n  mac-unsigned:\n')[1].split('\n  mac-internal:')[0]
        for expected in ("github.event_name == 'workflow_dispatch'", "inputs.target == 'mac-unsigned'",
                         'github.event.repository.private == false', 'inputs.expected_sha == github.sha',
                         'runs-on: macos-26', 'timeout-minutes: 45', 'contents: read', 'persist-credentials: false'):
            self.assertIn(expected,section)
        for forbidden in ('secrets.', 'upload-artifact', 'write', 'large', 'self-hosted', 'codemagic', 'testflight'):
            # Branch name contains testflight; it does not invoke the signed driver.
            if forbidden=='testflight':self.assertNotIn('ci/testflight/build.py',section)
            else:self.assertNotIn(forbidden,section)
        self.assertEqual(text.count("if: ${{ inputs.target != 'mac-unsigned' && inputs.target != 'mac-internal' && inputs.target != 'asc-status' }}"),9)

    def test_initial_policy_reasons_are_finite_and_never_print_exception_messages(self):
        for error,expected in [(p.PolicyError('github_initial_disk'),'github_initial_disk'),
            (p.PolicyError('sdk_tool_lock_hash'),'sdk_tool_lock_hash'),(p.PolicyError('sdk_generated_config_missing'),'sdk_generated_config_missing'),
            (p.PolicyError('CANARY'),'OTHER'),(RuntimeError('CANARY'),'OTHER')]:
            with mock.patch.object(g,'execute',side_effect=error),mock.patch('builtins.print') as printed:
                self.assertEqual(g.main(),1)
            row=json.loads(printed.call_args.args[0])
            self.assertEqual(row['safe_reason'],expected)
            self.assertFalse(row['artifact_eligible']);self.assertNotIn('CANARY',json.dumps(row))

class GithubCommandVerification(unittest.TestCase):
    def test_command_and_verification_outcomes_are_separate_and_safe(self):
        import time
        for case in ('success','pre','post','process','post_resource'):
            with self.subTest(case=case):
                overlay=mock.Mock();guard=mock.Mock();detail={}
                if case=='pre':overlay.verify.side_effect=p.PolicyError('sdk_package_config_changed')
                if case=='post':overlay.verify.side_effect=[None,p.PolicyError('sdk_package_config_changed')]
                if case=='post_resource':guard.side_effect=[None,p.PolicyError('github_time_disk')]
                def run(*args,**kwargs):
                    kwargs['diagnostic'].update(failure_kind='NONZERO_EXIT' if case=='process' else 'NONE',
                        exit_code=9 if case=='process' else 0,cleanup_failed=False,output_bytes=351)
                    if case=='process':raise RuntimeError('CANARY')
                    return subprocess.CompletedProcess([],0,'CANARY','CANARY')
                with mock.patch.object(g,'run_bounded',side_effect=run) as runner,mock.patch('builtins.print') as printed:
                    action=lambda:g.run_checked('pub_get',['fixed'],cwd=g.ROOT,env={'HOME':'CANARY'},
                        deadline=time.monotonic()+60,guard=guard,overlay=overlay)
                    if case=='success':self.assertEqual(action(),'CANARY')
                    else:
                        with self.assertRaises((p.PolicyError,RuntimeError)):action()
                row=json.loads(printed.call_args.args[0]);self.assertNotIn('CANARY',json.dumps(row))
                if case=='pre':
                    runner.assert_not_called();self.assertEqual(row['command_outcome'],'NOT_RUN')
                    self.assertEqual(row['failure_kind'],'PRE_VERIFICATION');self.assertIsNone(row['exit_code'])
                elif case in {'post','post_resource'}:
                    self.assertEqual(row['command_outcome'],'PASS');self.assertEqual(row['process_failure_kind'],'NONE')
                    self.assertEqual(row['failure_kind'],'POST_VERIFICATION');self.assertEqual(row['exit_code'],0)
                    self.assertEqual(row['verification_phase'],'post_verification');self.assertFalse(row['cleanup_failed'])
                elif case=='process':
                    self.assertEqual(row['command_outcome'],'FAILED');self.assertEqual(row['failure_kind'],'NONZERO_EXIT')
                    self.assertEqual(row['verification_phase'],'command')
                else:
                    self.assertEqual(row['outcome'],'PASS');self.assertEqual(row['verification_phase'],'complete')

    def test_postverification_failure_stops_full_driver_before_analyze(self):
        # Full orchestration fixture keeps command ordering and forbids extras.
        case=GithubMacPolicy()
        case.exercise(None, post_failure=True)
