"""Supplement the owned disposable harness with six independent persisted API checks."""
import importlib.util
from pathlib import Path
import sys
import unittest
from datetime import date

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("qa_owned_pg_harness", ROOT/"backend/integration/run_postgres.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
qa_spec = importlib.util.spec_from_file_location("qa_independent_backend",
    "/home/chatbot/wainak-dev/qa-phase1/qa/phase1/test_backend_independent.py")
qa = importlib.util.module_from_spec(qa_spec)
qa_spec.loader.exec_module(qa)
original_loader = unittest.defaultTestLoader.loadTestsFromModule

def load_with_independent_cases(module, *args, **kwargs):
    from wainak.domain import DevelopmentService
    from wainak.api import DevelopmentApplication
    from wainak.postgres import PostgresRepository
    from wainak.migrations import require_disposable_database
    suite = original_loader(module, *args, **kwargs)
    class DurableIndependentQA(qa.IndependentBackendReview):
        def setUp(self):
            if module.CONNECT is None:
                raise RuntimeError("Only the harness-owned disposable connection is accepted")
            with module.CONNECT() as connection:
                require_disposable_database(connection)
                connection.execute("TRUNCATE wainak_phase1_dev.accounts CASCADE")
            self.s = DevelopmentService(today=lambda: date(2026,10,24),
                repository=PostgresRepository(module.CONNECT, enable_synthetic_persistence=True))
            self.app = DevelopmentApplication(enable_development=True, service=self.s)
            self.seq = 0
    for name in (
        "test_third_party_every_relationship_action_and_report_attribution_denied",
        "test_candidate_and_relationship_responses_are_private_allowlists",
        "test_replay_returns_current_block_not_stale_purchase_right",
        "test_delete_revokes_existing_token_and_peer_gets_no_private_data",
        "test_messaging_upload_and_sensitive_fields_fail_closed",
        "test_known_candidate_can_report_even_after_target_blocks_them_first",
    ):
        suite.addTest(DurableIndependentQA(name))
    return suite

unittest.defaultTestLoader.loadTestsFromModule = load_with_independent_cases
sys.argv = [str(ROOT/"backend/integration/run_postgres.py"), "--run-disposable-postgres"]
raise SystemExit(harness.main())
