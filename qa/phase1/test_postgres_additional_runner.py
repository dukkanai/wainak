"""No-DB guards for the portable six-case disposable PG QA runner."""
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

source = Path(__file__).with_name("postgres_additional_fixture.py")
spec = importlib.util.spec_from_file_location("qa_portable_pg_runner", source)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class RunnerGuards(unittest.TestCase):
    def test_import_does_not_replace_global_unittest_loader(self):
        self.assertEqual(unittest.defaultTestLoader.loadTestsFromModule.__func__.__module__, "unittest.loader")

    def test_six_unique_cases_are_unchanged_and_adjacent(self):
        self.assertEqual(len(runner.CASES), 6)
        self.assertEqual(len(set(runner.CASES)), 6)
        self.assertTrue(source.with_name("test_backend_independent.py").is_file())

    def test_missing_opt_in_never_loads_or_starts_harness(self):
        with patch.object(runner, "load_module") as load, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as failure:
                runner.main(["--backend-root", str(source.parent), "--expected-backend-commit", "a"*40])
        self.assertEqual(failure.exception.code, 2)
        load.assert_not_called()

    def test_bad_commit_format_never_runs_git(self):
        with patch.object(runner.subprocess, "run") as run:
            with self.assertRaises(RuntimeError):
                runner.exact_source(Path("/unused"), "HEAD")
        run.assert_not_called()

    def test_wrong_or_dirty_commit_fails_closed(self):
        for head, dirty in [("b"*40, ""), ("a"*40, " M backend/source.py")]:
            with self.subTest(dirty=bool(dirty)), patch.object(runner.subprocess, "run",
                side_effect=[SimpleNamespace(stdout=head+"\n"), SimpleNamespace(stdout=dirty)]):
                with self.assertRaises(RuntimeError):
                    runner.exact_source(Path("/unused"), "a"*40)

    def test_clean_exact_commit_is_accepted(self):
        with patch.object(runner.subprocess, "run",
            side_effect=[SimpleNamespace(stdout="a"*40+"\n"), SimpleNamespace(stdout="")]):
            self.assertEqual(runner.exact_source(Path("/unused"), "a"*40), "a"*40)

if __name__ == "__main__":
    unittest.main()
