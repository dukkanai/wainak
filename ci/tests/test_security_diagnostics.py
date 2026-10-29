"""Synthetic errors only; never read a credential or invoke Apple's security."""
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest import mock

from scripts import ci_process as process, security_diagnostics as security
from ci.github import internal_testflight as signed, internal_policy as q, mac_unsigned as g
from ci.testflight import policy as p


class Classification(unittest.TestCase):
    def test_exact_known_messages_and_numeric_statuses(self):
        for code,(status,message) in security.ERRORS.items():
            for prefix in security.PREFIXES:
                for text in (message,b'OSStatus '+str(status).encode()):
                    for newline in (b'',b'\n',b'\r\n'):
                        with self.subTest(code=code,prefix=prefix,newline=newline):
                            self.assertEqual(security.classify(prefix+text+newline),code)

    def test_unrecognized_mutated_ambiguous_and_canary_outputs_never_escape(self):
        known=security.PREFIXES[0]+security.ERRORS['PKCS12_VERIFY_FAILURE'][1]
        values=[b'',b'x'*96,b'x'*4097,b'CANARY_PRIVATE_VALUE',known+b' CANARY',
            b'CANARY '+known,known+b'\nCANARY',known+b'\n'+known,
            b'\n'+known,known+b'\0',known.lower(),known.replace(b': ',b':\t'),
            b'security: SecKeychainItemImport: OSStatus -999999',
            b'/CANARY/path: '+known,known.decode(),None]
        for data in values:
            with self.subTest(index=values.index(data)):
                self.assertEqual(security.classify(data),'UNCLASSIFIED')
        self.assertEqual(security.project('CANARY'),'CLASSIFIER_FAILED')
        self.assertEqual(security.project({'CANARY':True}),'CLASSIFIER_FAILED')

    def test_real_process_nonzero_classification_preserves_failure_and_withholds_output(self):
        for code,(_,message) in security.ERRORS.items():
            detail={};payload=security.PREFIXES[0]+message+b'\n'
            with self.subTest(code=code),self.assertRaises(RuntimeError) as caught:
                process.run_bounded([sys.executable,'-c','import os; os.write(2,'+repr(payload)+'); raise SystemExit(1)'],
                    cwd=Path.cwd(),seconds=5,check=True,diagnostic=detail,output_profile=security.PROFILE)
            self.assertEqual(detail['security_error'],code)
            self.assertEqual(detail['failure_kind'],'NONZERO_EXIT');self.assertEqual(detail['exit_code'],1)
            self.assertFalse(detail['cleanup_failed']);self.assertNotIn(message.decode(),str(caught.exception))
            self.assertEqual(set(detail),{'failure_kind','exit_code','output_bytes','cleanup_failed','security_error',
                'cleanup_errors','cleanup_errors_truncated'})

    def test_success_timeout_and_output_bound_do_not_infer_error_from_partial_output(self):
        payload=security.PREFIXES[0]+security.ERRORS['PKCS12_VERIFY_FAILURE'][1]+b'\n'
        for case in ('success','timeout','bound'):
            detail={};source='import os,time; os.write(2,'+repr(payload)+')'
            if case=='timeout':source+='; time.sleep(5)'
            kwargs={'seconds':.15 if case=='timeout' else 5,'maximum':32 if case=='bound' else 4096}
            with self.subTest(case=case):
                if case=='success':
                    result=process.run_bounded([sys.executable,'-c',source],cwd=Path.cwd(),check=True,
                        diagnostic=detail,output_profile=security.PROFILE,**kwargs)
                    self.assertEqual(result.returncode,0)
                else:
                    with self.assertRaises((RuntimeError,TimeoutError)):
                        process.run_bounded([sys.executable,'-c',source],cwd=Path.cwd(),check=True,
                            diagnostic=detail,output_profile=security.PROFILE,**kwargs)
                self.assertEqual(detail['security_error'],'NOT_APPLICABLE')
                self.assertEqual(detail['failure_kind'],{'success':'NONE','timeout':'TIMEOUT','bound':'OUTPUT_BOUND'}[case])

    def test_classifier_failure_invalid_return_and_cleanup_failure_remain_closed(self):
        original_cleanup=process.cleanup_process
        def failed_cleanup(*args):
            errors=original_cleanup(*args)
            return errors+[{'operation':'signal_term','type':'PermissionError','errno':1}]
        for case in ('raise','invalid','cleanup'):
            detail={}
            classifier=mock.Mock(side_effect=ValueError('CANARY')) if case=='raise' else mock.Mock(return_value='CANARY' if case=='invalid' else 'AUTH_FAILED')
            with mock.patch.object(security,'classify',classifier), \
                 mock.patch.object(process,'cleanup_process',failed_cleanup if case=='cleanup' else original_cleanup), \
                 self.assertRaises(RuntimeError) as caught:
                process.run_bounded([sys.executable,'-c','print("CANARY"); raise SystemExit(1)'],
                    cwd=Path.cwd(),seconds=5,check=True,diagnostic=detail,output_profile=security.PROFILE)
            self.assertNotIn('CANARY',json.dumps(detail)+str(caught.exception))
            self.assertEqual(detail['failure_kind'],'NONZERO_EXIT')
            self.assertEqual(detail['cleanup_failed'],case=='cleanup')
            self.assertEqual(detail['security_error'],'AUTH_FAILED' if case=='cleanup' else 'CLASSIFIER_FAILED')

    def test_profile_is_closed_and_opt_in(self):
        with mock.patch.object(process.subprocess,'Popen') as spawn:
            for profile in ('CANARY',{},True):
                with self.assertRaises(ValueError):
                    process.run_bounded([],cwd=Path.cwd(),output_profile=profile)
            spawn.assert_not_called()
        detail={}
        with mock.patch.object(security,'classify',side_effect=AssertionError('not enabled')),self.assertRaises(RuntimeError):
            process.run_bounded([sys.executable,'-c','raise SystemExit(1)'],cwd=Path.cwd(),check=True,diagnostic=detail)
        self.assertNotIn('security_error',detail)


class Integration(unittest.TestCase):
    def test_import_only_routes_classifier(self):
        with mock.patch.object(g,'run_checked') as checked:
            run=signed.runner({},time.monotonic()+10)
            for label,command,enabled in [('keychain_import',['/usr/bin/security','import'],True),
                ('keychain_import',['unexpected','import'],False),('profile_decode',['/usr/bin/security','cms'],False),
                ('build_ipa',['flutter','build','ipa'],False)]:
                run(label,command)
                self.assertEqual(checked.call_args.kwargs.get('output_profile'),security.PROFILE if enabled else None)

    def test_command_and_final_failure_classification_safe_projection(self):
        for code in sorted(security.CODES-{'NOT_APPLICABLE'}):
            def bounded(*args,**kwargs):
                self.assertEqual(kwargs['output_profile'],security.PROFILE)
                self.assertTrue(kwargs['check']);self.assertIs(kwargs['group_observer'],g.groups.capture)
                kwargs['diagnostic'].update(failure_kind='NONZERO_EXIT',exit_code=1,output_bytes=96,
                    cleanup_failed=False,security_error=code)
                raise RuntimeError('CANARY_RAW_OUTPUT')
            with self.subTest(code=code),mock.patch.object(g,'resource_guard'),mock.patch.object(g,'run_bounded',bounded), \
                 mock.patch('builtins.print') as printed:
                with self.assertRaisesRegex(p.PolicyError,'^security_'+code.lower()+'$'):
                    signed.runner({},time.monotonic()+10)('keychain_import',['/usr/bin/security','import','CANARY'])
                row=json.loads(printed.call_args.args[0]);self.assertEqual(row['security_error'],code)
                self.assertEqual(row['safe_reason'],'security_'+code.lower())
                self.assertEqual(row['failure_kind'],'NONZERO_EXIT');self.assertFalse(row['cleanup_failed'])
                self.assertNotIn('CANARY',str(printed.call_args_list))
            with mock.patch.object(signed,'preflight',return_value='1'),mock.patch.object(g,'execute',return_value={}), \
                 mock.patch.object(signed,'compile_internal',side_effect=p.PolicyError('security_'+code.lower())), \
                 mock.patch('builtins.print') as printed:
                self.assertEqual(signed.main(['--build']),1)
                row=json.loads(printed.call_args.args[0]);self.assertEqual(row['safe_reason'],'security_'+code.lower())
                self.assertFalse(row['artifact_eligible'])

    def test_postverification_and_timeout_not_relabelled_as_import_failure(self):
        for phase in ('post','timeout','cleanup'):
            overlay=mock.Mock()
            if phase=='post':overlay.verify.side_effect=[None,p.PolicyError('sdk_base_changed')]
            def bounded(*args,**kwargs):
                kind={'post':'NONE','timeout':'TIMEOUT','cleanup':'CLEANUP'}[phase]
                kwargs['diagnostic'].update(failure_kind=kind,exit_code=0 if phase!='timeout' else None,
                    cleanup_failed=phase=='cleanup',security_error='NOT_APPLICABLE')
                if phase=='timeout':raise TimeoutError('CANARY')
                if phase=='cleanup':raise RuntimeError('CANARY')
                return subprocess.CompletedProcess([],0,'CANARY','')
            with mock.patch.object(g,'resource_guard'),mock.patch.object(g,'run_bounded',bounded),mock.patch('builtins.print') as printed:
                with self.assertRaises((p.PolicyError,TimeoutError,RuntimeError)):
                    signed.runner({},time.monotonic()+10,overlay)('keychain_import',['/usr/bin/security','import'])
                row=json.loads(printed.call_args.args[0]);self.assertEqual(row['security_error'],'NOT_APPLICABLE')
                self.assertEqual(row['verification_phase'],'post_verification' if phase=='post' else 'command')
                self.assertEqual(row['cleanup_failed'],phase=='cleanup');self.assertNotIn('CANARY',str(printed.call_args_list))
