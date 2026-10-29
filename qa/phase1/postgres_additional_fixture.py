"""Six independent persisted API checks through the owned disposable harness.

Explicit exact-commit backend root is required. No external DSN, production DB,
global unittest monkeypatch, or dependency on another QA worktree is accepted.
"""
import argparse
from datetime import date
import importlib.util
import re
from pathlib import Path
import subprocess
import sys
import unittest

CASES = (
    "test_third_party_every_relationship_action_and_report_attribution_denied",
    "test_candidate_and_relationship_responses_are_private_allowlists",
    "test_replay_returns_current_block_not_stale_purchase_right",
    "test_delete_revokes_existing_token_and_peer_gets_no_private_data",
    "test_messaging_upload_and_sensitive_fields_fail_closed",
    "test_known_candidate_can_report_even_after_target_blocks_them_first",
)

def exact_source(root, expected):
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("Expected a complete immutable commit SHA")
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
        check=True, capture_output=True, text=True).stdout.strip()
    if head != expected or dirty:
        raise RuntimeError("Expected clean exact backend commit; refusing mixed-source evidence")
    return head

def load_module(name, path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Reviewed regular fixture source is required")
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module

def extra_factory(qa):
    def extra(connect, restart, temporary):
        from wainek.domain import DevelopmentService
        from wainek.api import DevelopmentApplication
        from wainek.postgres import PostgresRepository
        from wainek.migrations import require_disposable_database
        if not callable(connect):
            raise RuntimeError("Only the harness-owned disposable connection factory is accepted")
        class DurableIndependentQA(qa.IndependentBackendReview):
            def setUp(self):
                with connect() as connection:
                    require_disposable_database(connection)
                    connection.execute("TRUNCATE wainak_phase1_dev.accounts CASCADE")
                self.s = DevelopmentService(today=lambda: date(2026, 10, 24),
                    repository=PostgresRepository(connect, enable_synthetic_persistence=True))
                self.app = DevelopmentApplication(enable_development=True, service=self.s)
                self.seq = 0
        return unittest.TestSuite(DurableIndependentQA(name) for name in CASES)
    return extra

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--expected-backend-commit", required=True)
    parser.add_argument("--run-disposable-postgres", action="store_true")
    args = parser.parse_args(argv)
    if not args.run_disposable_postgres:
        parser.error("Explicit disposable-fixture opt-in is required")
    root = args.backend_root.resolve(strict=True)
    print("backend_commit", exact_source(root, args.expected_backend_commit), flush=True)
    sys.path.insert(0, str(root / "backend"))
    harness = load_module("qa_owned_pg_harness", root / "backend/integration/run_postgres.py")
    qa = load_module("qa_independent_backend", Path(__file__).with_name("test_backend_independent.py"))
    try:
        return harness.main(extra_test_factory=extra_factory(qa),
                            argv=["--run-disposable-postgres"])
    finally:
        exact_source(root, args.expected_backend_commit)

if __name__ == "__main__":
    raise SystemExit(main())
