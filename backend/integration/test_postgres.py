"""Only loaded by run_postgres.py after creating its own disposable database."""

import multiprocessing
import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import psycopg

from wainek.domain import DevelopmentService, DomainError, POLICY_VERSION
from wainek.api import DevelopmentApplication
from wainek.migrations import RepositoryConfigurationError, apply_initial_migration
from wainek.postgres import PostgresRepository

CONNECT = None
CONNECT_WRONG_DATABASE = None
RESTART_CONTAINER = None


def service():
    if CONNECT is None:
        raise RuntimeError("Use the disposable harness; no external DSN is accepted.")
    return DevelopmentService(today=lambda: date(2026,10,24),
        repository=PostgresRepository(CONNECT, enable_synthetic_persistence=True))


def accept_in_process(actor, relationship, barrier, queue):
    """forked child creates its own connection; no inherited open connection."""
    try:
        barrier.wait(timeout=10)
        service().respond_exclusive(actor, relationship, {"decision": "accept"})
        queue.put("accepted")
    except DomainError:
        queue.put("rejected")
    except Exception:
        queue.put("unexpected_error")


class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        if CONNECT is None:
            raise RuntimeError("Integration tests require the disposable harness, never a supplied live DSN.")
        with CONNECT() as connection:
            connection.execute("TRUNCATE wainak_phase1_dev.accounts CASCADE")
        self.counter = 0
        self.app = service()

    def account(self, gender="male"):
        self.counter += 1
        result = self.app.register({"email": f"pg-{self.counter}@example.invalid", "birth_date": "1996-01-01",
            "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        actor = result["account"]["id"]
        self.app.verify_email(actor, {"simulate_verified": True})
        self.app.update_profile(actor, {"gender": gender, "country": "SA", "marital_status": "single",
            "declared_wives": 0, "marriage_goal": "build_family", "discoverable": True})
        self.app.update_preferences(actor, {"min_age": 18, "max_age": 80, "countries": [], "marital_statuses": ["single","married"]})
        return actor, result["access_token"]

    def pair(self):
        a, at = self.account()
        b, bt = self.account("female")
        rel = self.app.request(a, {"candidate_id": b}, "request-001")["id"]
        self.app.respond(b, rel, {"decision": "accept"})
        self.app.activate(a, rel, {"simulate_entitlement": True})
        return a, b, rel, at, bt

    def count(self, table):
        allowed = {"accounts","consents","sessions","relationships","exclusive_claims","safety_blocks","reports","request_idempotency"}
        self.assertIn(table, allowed)
        with CONNECT() as connection:
            return connection.execute("SELECT count(*) FROM wainak_phase1_dev." + table).fetchone()[0]

    def test_data_survives_service_reconstruction_and_real_container_restart(self):
        a, b, rel, at, bt = self.pair()
        self.app.answer(a, {"question_id": "family_plan", "option_id": "children"})
        self.app.report(b, {"target_id": a, "category": "harassment", "relationship_id": rel})
        before = self.app.me(a)
        RESTART_CONTAINER()
        restarted = service()
        self.assertEqual(restarted.authenticate(at), a)
        self.assertEqual(restarted.me(a), before)
        self.assertEqual(restarted.relationship(b, rel)["status"], "active_cards")
        self.assertEqual(restarted.assessment(a)["answers"], {"family_plan":"children"})
        self.assertEqual(self.count("reports"), 1)
        self.assertEqual(self.count("consents"), 2)

    def test_failed_transition_rolls_back_all_partial_database_replacement(self):
        a, b, rel, _, _ = self.pair()
        before = service().relationship(a, rel)
        repository = PostgresRepository(CONNECT, enable_synthetic_persistence=True)
        with self.assertRaises(psycopg.errors.CheckViolation):
            with repository.transaction() as state:
                state.relationships[rel]["status"] = "ended"
                state.reports["rpt_" + "a"*32] = {"id":"rpt_" + "a"*32,"reporter_id":a,"target_id":b,
                    "relationship_id":rel,"category":"not_an_allowed_category","status":"recorded_development_only","evidence_uploaded":False}
        self.assertEqual(service().relationship(a, rel), before)
        self.assertEqual(self.count("reports"), 0)
        self.assertEqual(self.count("accounts"), 2)
        self.assertEqual(self.count("consents"), 2)

    def test_two_independent_processes_competing_for_exclusivity_have_one_winner(self):
        a, b, first, _, _ = self.pair()
        c, _ = self.account("female")
        second = self.app.request(a, {"candidate_id": c}, "request-002")["id"]
        self.app.respond(c, second, {"decision":"accept"})
        self.app.activate(a, second, {"simulate_entitlement":True})
        self.app.request_exclusive(a, first, {"confirm":True})
        self.app.request_exclusive(a, second, {"confirm":True})
        context = multiprocessing.get_context("fork")
        barrier, queue = context.Barrier(2), context.Queue()
        children = [context.Process(target=accept_in_process,args=(actor,rel,barrier,queue)) for actor,rel in ((b,first),(c,second))]
        try:
            for child in children:
                child.start()
            for child in children:
                child.join(15)
                self.assertFalse(child.is_alive(), "Synthetic race child timed out")
                self.assertEqual(child.exitcode, 0)
            self.assertEqual(sorted(queue.get(timeout=3) for _ in children), ["accepted","rejected"])
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                    child.join()
            queue.close()
        states = {service().relationship(a, rel)["status"] for rel in (first,second)}
        self.assertEqual(states, {"exclusive_cards","frozen"})
        self.assertEqual(self.count("exclusive_claims"), 2)

    def test_block_activation_race_across_distinct_repository_connections(self):
        for iteration in range(10):
            a, _ = self.account()
            b, _ = self.account("female")
            rel = self.app.request(a, {"candidate_id": b}, f"race-{iteration:04d}")["id"]
            self.app.respond(b, rel, {"decision":"accept"})
            barrier = threading.Barrier(2)
            def block():
                barrier.wait(timeout=5)
                return service().block(b,{"target_id":a})
            def activate():
                barrier.wait(timeout=5)
                try:
                    return service().activate(a,rel,{"simulate_entitlement":True})
                except DomainError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(block),pool.submit(activate)]
                for future in futures:
                    future.result(timeout=15)
            result = service().relationship(a,rel)
            self.assertEqual(result["status"],"blocked")
            self.assertFalse(result["permissions"]["can_send_cards"])
            self.assertIsNone(result["peer"])

    def test_idempotency_persists_and_replays_current_blocked_state(self):
        a, b, rel, _, _ = self.pair()
        service().block(b,{"target_id":a})
        replay = service().request(a,{"candidate_id":b},"request-001")
        self.assertEqual(replay["id"],rel)
        self.assertEqual(replay["status"],"blocked")
        self.assertEqual(self.count("request_idempotency"),1)

    def test_parallel_same_idempotency_key_creates_one_durable_relationship(self):
        a,_=self.account()
        b,_=self.account("female")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:service().request(a,{"candidate_id":b},"parallel-key"),range(8)))
        self.assertEqual(len({value["id"] for value in results}),1)
        self.assertEqual(self.count("relationships"),1)
        self.assertEqual(self.count("request_idempotency"),1)

    def test_json_adapter_can_inject_persistence_without_changing_synthetic_mode(self):
        a,token=self.account()
        app=DevelopmentApplication(enable_development=True,service=service())
        def request(path):
            response={}
            def start(status,headers):
                response["status"]=status
            data=b"".join(app({"REQUEST_METHOD":"GET","PATH_INFO":path,"HTTP_HOST":"127.0.0.1",
                "HTTP_AUTHORIZATION":"Bearer "+token,"wsgi.input":io.BytesIO()},start))
            self.assertTrue(response["status"].startswith("200"))
            return json.loads(data)
        self.assertEqual(request("/health"),{"status":"ok","mode":"synthetic_development_only","durable_storage":True})
        self.assertEqual(request("/v1/me")["id"],a)

    def test_target_first_block_preserves_reporting_but_not_discovery(self):
        a, _ = self.account()
        b, _ = self.account("female")
        self.app.block(a,{"target_id":b})
        result=service().report(b,{"target_id":a,"category":"child_safety"})
        self.assertFalse(result["evidence_uploaded"])
        with self.assertRaises(DomainError):
            service().candidate(b,a)

    def test_database_unique_pair_and_claim_constraints_reject_direct_bypass(self):
        a,b,rel,_,_=self.pair()
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with CONNECT() as connection:
                connection.execute("""INSERT INTO wainak_phase1_dev.relationships(id,initiator_id,recipient_id,status)
                    VALUES (%s,%s,%s,'requested')""",("rel_"+"b"*32,b,a))
        self.app.request_exclusive(a,rel,{"confirm":True})
        self.app.respond_exclusive(b,rel,{"decision":"accept"})
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with CONNECT() as connection:
                connection.execute("INSERT INTO wainak_phase1_dev.exclusive_claims VALUES (%s,%s)",(a,rel))
        self.assertEqual(self.count("exclusive_claims"),2)

    def test_database_rejects_exclusivity_without_both_member_claims(self):
        a,b,rel,_,_=self.pair()
        with self.assertRaises(psycopg.errors.CheckViolation):
            with CONNECT() as connection:
                connection.execute("SET LOCAL search_path = wainak_phase1_dev, pg_catalog")
                connection.execute("UPDATE relationships SET status='exclusive_cards' WHERE id=%s",(rel,))
                connection.execute("INSERT INTO exclusive_claims VALUES (%s,%s)",(a,rel))
        self.assertEqual(service().relationship(a,rel)["status"],"active_cards")
        self.assertEqual(self.count("exclusive_claims"),0)

    def test_deletion_persists_private_data_erasure_and_session_revocation(self):
        a,b,rel,at,_=self.pair()
        self.app.report(b,{"target_id":a,"category":"harassment"})
        self.app.delete_account(a,{"confirmation":"DELETE"})
        with self.assertRaises(DomainError):
            service().authenticate(at)
        with CONNECT() as connection:
            data=connection.execute("SELECT data FROM wainak_phase1_dev.accounts WHERE id=%s",(a,)).fetchone()[0]
        self.assertEqual(set(data),{"id","deleted","exclusive_relationship_id"})
        self.assertEqual(self.count("consents"),1)
        self.assertEqual(self.count("sessions"),1)
        self.assertEqual(self.count("reports"),0)
        self.assertEqual(service().relationship(b,rel)["status"],"ended")

    def test_plaintext_session_tokens_and_dialogue_content_not_in_database(self):
        a,b,rel,at,bt=self.pair()
        with CONNECT() as connection:
            hashes=[row[0] for row in connection.execute("SELECT token_hash FROM wainak_phase1_dev.sessions")]
            columns=[row[0] for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='wainak_phase1_dev'")]
        self.assertNotIn(at,hashes)
        self.assertNotIn(bt,hashes)
        self.assertTrue(all(len(value)==64 for value in hashes))
        for forbidden in ("conversation","message_body","image","audio","evidence_body","card_answer"):
            self.assertNotIn(forbidden,columns)

    def test_sql_metacharacter_profile_is_data_not_executable_sql(self):
        a,_=self.account()
        repository=PostgresRepository(CONNECT,enable_synthetic_persistence=True)
        with repository.transaction() as state:
            state.accounts[a]["alias"]="synthetic '; DROP TABLE accounts; -- \\ payload"
        self.assertIn("DROP TABLE",service().me(a)["alias"])
        self.assertEqual(self.count("accounts"),1)

    def test_migration_refuses_existing_schema_and_non_test_database(self):
        with self.assertRaises(RepositoryConfigurationError):
            apply_initial_migration(CONNECT,allow_new_disposable_database=True)
        with self.assertRaises(RepositoryConfigurationError):
            apply_initial_migration(CONNECT_WRONG_DATABASE,allow_new_disposable_database=True)
        repository=PostgresRepository(CONNECT_WRONG_DATABASE,enable_synthetic_persistence=True)
        with self.assertRaises(RepositoryConfigurationError):
            with repository.transaction():
                self.fail("Non-test database should never be loaded")


if __name__=="__main__":
    raise SystemExit("Run via run_postgres.py --run-disposable-postgres; never supply a live DSN.")
