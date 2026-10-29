"""Safe summaries of synthetic unittest failures; never print failure messages."""
import json
from pathlib import Path
import sys
import time
import unittest
from unittest import mock
from scripts import regression_diagnostics as r, ci_process as cp
from ci.github import mac_unsigned as g
from ci.testflight import policy as p


class SafeRegressionDiagnostics(unittest.TestCase):
    def test_canary_failures_and_errors_are_only_public_ids(self):
        allowed=r.catalogue();name='test_regression_diagnostics.SafeRegressionDiagnostics.test_canary_failures_and_errors_are_only_public_ids'
        self.assertIn(name,allowed)
        data=(f'FAIL: {name.rsplit(".",1)[-1]} ({name}) (case=CANARY_SECRET)\n'
            'Traceback CANARY_PATH\nAssertionError: CANARY_PRIVATE\n'
            'ERROR: test_not_public (test_not_public.Bad.test_not_public)\n'
            'ERROR: test_signing_settings (unittest.loader._FailedTest.test_signing_settings)\n'
            'Ran 419 tests in 16.580s\nFAILED (failures=1, errors=2)\n').encode()
        result=r.classify(data,allowed)
        self.assertEqual(result,{'status':'IDENTIFIED','failures':[name],
            'errors':['unittest.loader._FailedTest.test_signing_settings'],'tests_run':419})
        self.assertNotIn('CANARY',json.dumps(result));self.assertNotIn('test_not_public',json.dumps(result))
        for value in (None,{}, {'status':[]}, {'status':'CANARY'},
            {'status':'IDENTIFIED','failures':['CANARY'],'errors':[],'tests_run':1}):
            self.assertEqual(r.safe_project(value)['status'],'CLASSIFIER_FAILED')

    def test_real_failed_child_remains_failed_and_never_exposes_traceback(self):
        source='''import unittest
class SafeRegressionDiagnostics(unittest.TestCase):
    def test_real_failed_child_remains_failed_and_never_exposes_traceback(self):
        self.fail("CANARY_PRIVATE_MESSAGE")
SafeRegressionDiagnostics.__module__="test_regression_diagnostics"
unittest.main(verbosity=0)
'''
        detail={}
        with self.assertRaises(RuntimeError) as caught:
            cp.run_bounded([sys.executable,'-c',source],cwd=Path.cwd(),seconds=5,
                check=True,diagnostic=detail,output_profile=r.PROFILE)
        self.assertEqual(detail['failure_kind'],'NONZERO_EXIT');self.assertFalse(detail['cleanup_failed'])
        summary=detail['regression_summary'];self.assertEqual(summary['status'],'IDENTIFIED')
        self.assertEqual(summary['failures'],['test_regression_diagnostics.SafeRegressionDiagnostics.test_real_failed_child_remains_failed_and_never_exposes_traceback'])
        self.assertEqual(summary['tests_run'],1)
        self.assertNotIn('CANARY',json.dumps(detail)+str(caught.exception))
        self.assertNotIn('Traceback',json.dumps(detail))

    def test_unclassified_and_classifier_failure_remain_closed(self):
        for case in ('unknown','classifier','cleanup'):
            detail={};actual=cp.cleanup_process
            def cleanup(*args):return actual(*args)+[{'operation':'signal_term','type':'PermissionError','errno':1}]
            with mock.patch.object(r,'catalogue',side_effect=ValueError('CANARY') if case=='classifier' else None,
                                   return_value=set()),mock.patch.object(cp,'cleanup_process',cleanup if case=='cleanup' else actual):
                with self.assertRaises(RuntimeError):
                    cp.run_bounded([sys.executable,'-c','print("CANARY"); raise SystemExit(1)'],cwd=Path.cwd(),
                        check=True,diagnostic=detail,output_profile=r.PROFILE)
            self.assertEqual(detail['cleanup_failed'],case=='cleanup')
            self.assertEqual(detail['regression_summary']['status'],'CLASSIFIER_FAILED' if case=='classifier' else 'UNCLASSIFIED')
            self.assertNotIn('CANARY',json.dumps(detail))

    def test_github_command_emits_safe_summary_and_fixed_failure_reason(self):
        name='test_regression_diagnostics.SafeRegressionDiagnostics.test_github_command_emits_safe_summary_and_fixed_failure_reason'
        for state in ('IDENTIFIED','UNCLASSIFIED','CLASSIFIER_FAILED'):
            def bounded(*args,**kwargs):
                self.assertEqual(kwargs['output_profile'],r.PROFILE);self.assertTrue(kwargs['check'])
                kwargs['diagnostic'].update(failure_kind='NONZERO_EXIT',exit_code=1,cleanup_failed=False,
                    regression_summary={'status':state,'failures':[name] if state=='IDENTIFIED' else [],'errors':[],'tests_run':1})
                raise RuntimeError('CANARY')
            with mock.patch.object(g,'run_bounded',bounded),mock.patch('builtins.print') as printed, self.assertRaises(p.PolicyError):
                g.run_checked('regressions',[sys.executable,'synthetic'],cwd=Path.cwd(),env={},deadline=time.monotonic()+5,guard=lambda:None,overlay=None)
            row=json.loads(printed.call_args.args[0]);self.assertEqual(row['regression_summary']['status'],state)
            self.assertEqual(row['safe_reason'],{'IDENTIFIED':'github_regressions_failed','UNCLASSIFIED':'github_regressions_unclassified','CLASSIFIER_FAILED':'github_regressions_classifier_failed'}[state])
            self.assertEqual(row['failure_kind'],'NONZERO_EXIT');self.assertNotIn('CANARY',str(printed.call_args_list))
