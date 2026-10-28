"""No-DB fail-closed checks for the QA runner itself."""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr

spec=importlib.util.spec_from_file_location('qa_matching_runner',Path(__file__).with_name('run_matching_independent.py'))
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
SHA='a'*40

class MatchingRunnerGuards(unittest.TestCase):
    def reject_args(self,args):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            runner.main(args)
        self.assertEqual(error.exception.code,2)

    def test_requires_disposable_opt_in(self):
        self.reject_args(['--backend-root','/tmp','--expected-backend-commit',SHA])

    def test_requires_full_expected_commit(self):
        self.reject_args(['--backend-root','/tmp','--expected-backend-commit','abc', '--run-disposable-identity'])

    def test_requires_fixture_and_adjacent_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            self.reject_args(['--backend-root',d,'--expected-backend-commit',SHA,'--run-disposable-identity'])

    def root(self,d):
        p=Path(d)
        for f in ('backend/integration/run_identity.py','qa/phase2/test_auth_independent.py'):
            q=p/f
            q.parent.mkdir(parents=True,exist_ok=True)
            q.write_text('# non-executable guard fixture only\n')
        return ['--backend-root',d,'--expected-backend-commit',SHA,'--run-disposable-identity']

    def test_wrong_commit_is_rejected_before_fixture_import(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.root(d)
            with mock.patch.object(runner.subprocess,'check_output',side_effect=['b'*40+'\n','']), self.assertRaisesRegex(RuntimeError,'expected clean commit'):
                runner.main(args)

    def test_dirty_candidate_is_rejected_before_fixture_import(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.root(d)
            with mock.patch.object(runner.subprocess,'check_output',side_effect=[SHA+'\n',' M backend/x.py\n']), self.assertRaisesRegex(RuntimeError,'expected clean commit'):
                runner.main(args)

if __name__=='__main__':unittest.main()
