"""Synthetic Xcode data and local child processes; no Mac or credential access."""
import copy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest import mock
from ci.github import signing_settings as settings, internal_testflight as signed, mac_unsigned as g
from ci.testflight import policy as p
from ci.tests import test_github_internal as fixtures
from scripts.ci_process import run_bounded
PINS=fixtures.PINS
valid_settings=fixtures.settings


class Settings(unittest.TestCase):
    def test_valid_public_projection_never_echoes_environment_or_defines(self):
        value=valid_settings();value[0]['buildSettings'].update(HOME='/CANARY',TOKEN='CANARY',UNLISTED='CANARY')
        with mock.patch('builtins.print') as printed:settings.validate(json.dumps(value),PINS)
        row=json.loads(printed.call_args.args[0]);self.assertEqual(row['outcome'],'PASS')
        self.assertEqual(row['public_settings']['PROVISIONING_PROFILE_SPECIFIER'],'REVIEWED_UUID')
        self.assertEqual(set(row['public_settings']),set(settings.PUBLIC)|{'PROVISIONING_PROFILE_SPECIFIER'})
        self.assertNotIn('CANARY',str(printed.call_args_list));self.assertNotIn('DART_DEFINES',str(printed.call_args_list))

    def test_syntax_shape_duplicates_and_unexpected_types_have_fixed_reasons(self):
        base=valid_settings()
        variants=[('CANARY\n'+json.dumps(base),'signed_settings_json'),
            (json.dumps(base)+'\nCANARY','signed_settings_json'),('', 'signed_settings_json'),
            ('[] []','signed_settings_json'),('NaN','signed_settings_nonfinite'),('1e999','signed_settings_nonfinite'),
            ('{"target":"Runner","target":"Runner"}','signed_settings_duplicate_key'),
            ('9'*5000,'signed_settings_json_bound')]
        for value in (None,{},[],[None],[1],[[]],[{}],[{'target':'Runner','buildSettings':None}],base*129):
            variants.append((json.dumps(value),'signed_settings_shape'))
        for value in (None,[],{},1):
            changed=copy.deepcopy(base);changed[0]['buildSettings']['DART_DEFINES']=value
            variants.append((json.dumps(changed),'signed_settings_defines_type'))
        variants.extend([(json.dumps(base*2),'runner_settings'),(json.dumps([{'target':'Other'}]),'runner_settings')])
        for text,reason in variants:
            with self.subTest(reason=reason),mock.patch('builtins.print') as printed,self.assertRaisesRegex(p.PolicyError,'^'+reason+'$'):
                settings.validate(text,PINS)
            row=json.loads(printed.call_args.args[0]);self.assertEqual(row['safe_reason'],reason)
            self.assertEqual(row['outcome'],'FAILED');self.assertNotIn('CANARY',str(printed.call_args_list))
        # Python JSON implementations have different recursion limits. Either
        # parser rejection or the strict target-shape rejection must fail closed.
        with mock.patch('builtins.print'),self.assertRaises(p.PolicyError) as caught:
            settings.validate('['*2000+'0'+']'*2000,PINS)
        self.assertIn(str(caught.exception),{'signed_settings_json_bound','signed_settings_shape'})
        with mock.patch.object(settings.json,'loads',side_effect=RecursionError),mock.patch('builtins.print'), \
             self.assertRaisesRegex(p.PolicyError,'signed_settings_json_bound'):
            settings.validate('[]',PINS)

    def test_each_guard_still_rejects_wrong_identity_signing_profile_and_mode(self):
        mutations=[(key,'CANARY') for key in settings.PUBLIC]+[
            ('CODE_SIGNING_ALLOWED','NO'),('CODE_SIGNING_REQUIRED','NO'),('CODE_SIGN_STYLE','Automatic'),
            ('CODE_SIGN_IDENTITY','Apple Development'),('PROVISIONING_PROFILE_SPECIFIER',PINS['profile_name']),
            ('PROVISIONING_PROFILE_SPECIFIER',PINS['profile_uuid'].upper()),
            ('PROVISIONING_PROFILE_SPECIFIER','CANARY'),('DART_DEFINES','CANARY'),
            ('FRAMEWORK_SEARCH_PATHS','archivebridge'),('OTHER_LDFLAGS','WAINEK_ARCHIVE_BRIDGE')]
        for key,value in mutations:
            changed=valid_settings();changed[0]['buildSettings'][key]=value
            with self.subTest(key=key),mock.patch('builtins.print') as printed,self.assertRaises(p.PolicyError):
                settings.validate(json.dumps(changed),PINS)
            self.assertNotIn('CANARY',str(printed.call_args_list))

    def test_failure_prevents_ipa_and_preserves_lifecycle_cleanup(self):
        # Existing strict command model rejects unexpected calls and ensures cleanup.
        lifecycle=fixtures.Lifecycle()
        for mutation in ('settings_json','settings_type','settings_defines_type'):
            lifecycle.exercise(mutation=mutation)


class Channels(unittest.TestCase):
    def test_stderr_warning_breaks_old_json_but_stdout_only_passes_same_policy(self):
        payload=json.dumps(valid_settings())
        source='import os; os.write(2,b"CANARY_WARNING\\n"); os.write(1,'+repr(payload.encode())+')'
        old=run_bounded([sys.executable,'-c',source],cwd=Path.cwd(),seconds=5,check=True)
        with self.assertRaises(json.JSONDecodeError):json.loads(old.stdout)
        detail={}
        result=run_bounded([sys.executable,'-c',source],cwd=Path.cwd(),seconds=5,check=True,stdout_only=True,diagnostic=detail)
        self.assertEqual(result.stdout,payload);self.assertEqual(result.stderr,'')
        self.assertEqual(detail['stderr_bytes'],len(b'CANARY_WARNING\n'))
        self.assertEqual(detail['output_bytes'],detail['stdout_bytes']+detail['stderr_bytes'])
        with mock.patch('builtins.print') as printed:settings.validate(result.stdout,PINS)
        self.assertNotIn('CANARY',str(printed.call_args_list)+json.dumps(detail))

    def test_both_streams_share_bound_and_nonzero_timeout_remain_fail_closed(self):
        cases=[('stderr_flood','import os; os.write(2,b"x"*10000)',128,5,'OUTPUT_BOUND'),
            ('combined_bound','import os; os.write(1,b"x"*90); os.write(2,b"x"*90)',128,5,'OUTPUT_BOUND'),
            ('nonzero','import os; os.write(1,b"[]"); os.write(2,b"CANARY"); raise SystemExit(2)',4096,5,'NONZERO_EXIT'),
            ('timeout','import os,time; os.write(2,b"CANARY"); time.sleep(5)',4096,.15,'TIMEOUT')]
        for case,source,maximum,seconds,kind in cases:
            detail={}
            with self.subTest(case=case),self.assertRaises((RuntimeError,TimeoutError)) as caught:
                run_bounded([sys.executable,'-c',source],cwd=Path.cwd(),seconds=seconds,maximum=maximum,
                    check=True,stdout_only=True,diagnostic=detail)
            self.assertEqual(detail['failure_kind'],kind);self.assertFalse(detail['cleanup_failed'])
            self.assertNotIn('CANARY',str(caught.exception)+json.dumps(detail))

    def test_stderr_closed_and_cleanup_errors_are_preserved(self):
        from scripts import ci_process
        real=ci_process.subprocess.Popen
        children=[]
        def spawn(*args,**kwargs):
            child=real(*args,**kwargs);children.append(child);return child
        with mock.patch.object(ci_process.subprocess,'Popen',side_effect=spawn):
            run_bounded([sys.executable,'-c','pass'],cwd=Path.cwd(),stdout_only=True,check=True)
        self.assertTrue(children[0].stdout.closed);self.assertTrue(children[0].stderr.closed)
        close=mock.Mock(side_effect=PermissionError(1,'CANARY'))
        fake=mock.Mock(stdout=None,stderr=mock.Mock(close=close));fake.poll.return_value=0
        from ci.ios.diagnostics import cleanup_process
        with mock.patch('ci.ios.diagnostics.os.killpg',side_effect=ProcessLookupError):
            errors=cleanup_process(fake,None)
        self.assertIn({'operation':'close_stderr','type':'PermissionError','errno':1},errors)
        self.assertNotIn('CANARY',json.dumps(errors))

    def test_mode_is_opt_in_only_for_settings_and_command_diagnostic_has_counts(self):
        with mock.patch.object(g,'run_checked') as checked:
            run=signed.runner({},time.monotonic()+10)
            run('build_settings',['/usr/bin/xcodebuild']);self.assertTrue(checked.call_args.kwargs['stdout_only'])
            run('ios_config',['flutter']);self.assertNotIn('stdout_only',checked.call_args.kwargs)
        def bounded(*args,**kwargs):
            self.assertTrue(kwargs['stdout_only']);self.assertTrue(kwargs['check'])
            kwargs['diagnostic'].update(failure_kind='NONE',exit_code=0,cleanup_failed=False,stdout_bytes=2,stderr_bytes=6,output_bytes=8)
            return mock.Mock(stdout='[]')
        with mock.patch.object(g,'resource_guard'),mock.patch.object(g,'run_bounded',bounded),mock.patch('builtins.print') as printed:
            signed.runner({},time.monotonic()+10)('build_settings',['/usr/bin/xcodebuild'])
            row=json.loads(printed.call_args.args[0]);self.assertEqual(row['capture_mode'],'STDOUT_ONLY')
            self.assertEqual((row['stdout_bytes'],row['stderr_bytes']),(2,6))
