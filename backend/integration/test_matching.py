"""Authenticated matching only. No dialogue payload or entitlement fixture endpoint."""
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from django.db import connection, connections, transaction
from django.test import Client
from allauth.account.models import EmailAddress
import identity_integration as baseline
from wainak_identity.models import User
from wainak_identity.repository import service, IdentityDomainService, SharedDomainRepository


class AuthMatchingTests(unittest.TestCase):
    setUp = baseline.IdentityIntegrationTests.setUp
    call = baseline.IdentityIntegrationTests.call
    status = baseline.IdentityIntegrationTests.status
    signup = baseline.IdentityIntegrationTests.signup
    account = baseline.IdentityIntegrationTests.account
    ready_account = baseline.IdentityIntegrationTests.ready_account
    login = baseline.IdentityIntegrationTests.login

    def pair(self):
        a, ma = self.ready_account("alpha@example.invalid", "male")
        b, mb = self.ready_account("beta@example.invalid", "female")
        status, rel = self.call("POST", "/v1/relationships", {"candidate_id": mb["domain_id"]}, a,
                                HTTP_IDEMPOTENCY_KEY="matching-intent-001")
        self.status(status, 201, rel)
        return a, ma, b, mb, rel

    def mutate_account(self, identifier, change):
        with transaction.atomic(), service().repository.transaction() as state:
            change(state.accounts[identifier])

    def detail(self, token, identifier):
        code, body = self.call("GET", "/v1/relationships/"+identifier, token=token)
        self.status(code, 200, body)
        return body

    def respond(self, token, rel, decision="accept", **kwargs):
        return self.call("POST", "/v1/relationships/"+rel["id"]+"/respond", {"decision": decision}, token, **kwargs)

    def test_incoming_outgoing_hints_roles_and_third_party_are_current(self):
        a, ma, b, mb, rel = self.pair()
        self.assertEqual(rel["direction"], "outgoing")
        self.assertEqual(rel["available_actions"], ["cancel", "block", "report"])
        incoming = self.detail(b, rel["id"])
        self.assertEqual(incoming["direction"], "incoming")
        self.assertEqual(incoming["available_actions"], ["accept", "decline", "block", "report"])
        code, _ = self.respond(a, rel)
        self.status(code, 403)
        c, _ = self.ready_account("gamma@example.invalid", "female")
        code, _ = self.call("GET", "/v1/relationships/"+rel["id"], token=c)
        self.status(code, 404)
        code, _ = self.respond(c, rel)
        self.status(code, 404)
        for token, expected in ((a, "outgoing"), (b, "incoming")):
            code, body = self.call("GET", "/v1/relationships", token=token)
            self.status(code, 200, body)
            self.assertEqual(body["items"][0]["direction"], expected)

    def test_accept_stops_at_locked_entitlement_and_cannot_enable_communication(self):
        a, ma, b, mb, rel = self.pair()
        code, accepted = self.respond(b, rel)
        self.status(code, 200, accepted)
        self.assertEqual(accepted["status"], "accepted_pending_activation")
        self.assertEqual(accepted["available_actions"], ["end", "block", "report"])
        self.assertFalse(any(accepted["permissions"].values()))
        for path in ("/v1/relationships/"+rel["id"]+"/activate", "/v1/dev/relationships/"+rel["id"]+"/activate"):
            code, _ = self.call("POST", path, {"simulate_entitlement": True}, a)
            self.status(code, 404)
        code, _ = self.call("GET", "/v1/relationships/"+rel["id"]+"/cards", token=a)
        self.status(code, 409)
        code, replay = self.respond(b, rel)
        self.status(code, 200, replay)
        self.assertEqual(replay["available_actions"], accepted["available_actions"])

    def test_stale_recipient_can_decline_but_not_accept_or_smuggle_fields(self):
        a, ma, b, mb, rel = self.pair()
        self.mutate_account(mb["domain_id"], lambda account: account.pop("consents"))
        incoming = self.detail(b, rel["id"])
        self.assertEqual(incoming["available_actions"], ["decline", "block", "report"])
        code, body = self.respond(b, rel)
        self.status(code, 403, body)
        self.assertEqual(body["error"]["code"], "consent_required")
        path = "/v1/relationships/"+rel["id"]+"/respond"
        for payload in ({"decision": "decline", "actor_id": mb["domain_id"]},
                        {"decision": "accept", "decline": True}, {"decision": ["decline"]}):
            code, _ = self.call("POST", path, payload, b)
            self.assertIn(code, (400, 403))
        code, body = self.respond(b, rel, "decline")
        self.status(code, 200, body)
        self.assertEqual(body["status"], "declined")
        self.assertEqual(body["available_actions"], ["block", "report"])

    def test_stale_peer_is_hidden_and_positive_transition_rechecks_both_parties(self):
        a, ma, b, mb, rel = self.pair()
        self.mutate_account(ma["domain_id"], lambda account: account.pop("consents"))
        incoming = self.detail(b, rel["id"])
        self.assertIsNone(incoming["peer"])
        self.assertEqual(incoming["available_actions"], ["decline", "block", "report"])
        code, _ = self.respond(b, rel)
        self.status(code, 409)
        code, body = self.call("GET", "/v1/candidates", token=b)
        self.status(code, 200, body)
        self.assertEqual(body["items"], [])

    def test_authoritative_verification_revocation_overrides_domain_mirror(self):
        a, ma, b, mb, rel = self.pair()
        EmailAddress.objects.filter(user_id=ma["id"]).update(verified=False)
        with transaction.atomic(), service().repository.transaction() as state:
            self.assertTrue(state.accounts[ma["domain_id"]]["dev_email_verified"])
        incoming = self.detail(b, rel["id"])
        self.assertIsNone(incoming["peer"])
        self.assertNotIn("accept", incoming["available_actions"])
        code, _ = self.respond(b, rel)
        self.status(code, 409)
        code, body = self.call("GET", "/v1/candidates", token=b)
        self.status(code, 200, body)
        self.assertEqual(body["items"], [])
        # New request observes restoration; there is no cross-request eligibility cache.
        EmailAddress.objects.filter(user_id=ma["id"]).update(verified=True)
        self.assertIn("accept", self.detail(b, rel["id"])["available_actions"])

    def test_inactive_peer_is_not_projected_or_accepted(self):
        a, ma, b, mb, rel = self.pair()
        User.objects.filter(pk=ma["id"]).update(is_active=False)
        self.assertIsNone(self.detail(b, rel["id"])["peer"])
        code, _ = self.respond(b, rel)
        self.status(code, 409)
        code, _ = self.call("GET", "/v1/me", token=a)
        self.status(code, 401)

    def test_underage_peer_is_redacted_without_reason_and_decline_remains(self):
        a, ma, b, mb, rel = self.pair()
        self.mutate_account(ma["domain_id"], lambda account: account.update(birth_date=f"{date.today().year-17}-12-31"))
        incoming = self.detail(b, rel["id"])
        self.assertIsNone(incoming["peer"])
        self.assertEqual(incoming["available_actions"], ["decline", "block", "report"])
        self.assertNotIn("reason", incoming)
        code, _ = self.respond(b, rel)
        self.status(code, 409)
        code, body = self.respond(b, rel, "decline")
        self.status(code, 200, body)

    def test_target_first_block_hides_profile_but_report_is_still_executable(self):
        a, ma, b, mb, rel = self.pair()
        code, _ = self.call("POST", "/v1/blocks", {"target_id": mb["domain_id"]}, a)
        self.status(code, 200)
        blocked = self.detail(b, rel["id"])
        self.assertIsNone(blocked["peer"])
        self.assertEqual(blocked["available_actions"], ["block", "report"])
        code, _ = self.respond(b, rel)
        self.status(code, 409)
        code, report = self.call("POST", "/v1/reports", {"target_id": blocked["initiator_id"],
            "relationship_id": rel["id"], "category": "harassment"}, b, HTTP_IDEMPOTENCY_KEY="matching-report-001")
        self.status(code, 201, report)
        self.assertFalse(report["evidence_uploaded"])
        code, replay = self.call("POST", "/v1/relationships", {"candidate_id": mb["domain_id"]}, a,
                                 HTTP_IDEMPOTENCY_KEY="matching-intent-001")
        self.status(code, 201, replay)
        self.assertEqual(replay["status"], "blocked")
        self.assertEqual(replay["available_actions"], ["block", "report"])

    def test_deleted_peer_has_no_projection_or_actions_and_cannot_resurrect(self):
        a, ma, b, mb, rel = self.pair()
        code, _ = self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, b)
        self.status(code, 200)
        ended = self.detail(a, rel["id"])
        self.assertEqual(ended["status"], "ended")
        self.assertIsNone(ended["peer"])
        self.assertEqual(ended["available_actions"], [])
        code, _ = self.respond(b, rel)
        self.status(code, 401)
        code, replay = self.call("POST", "/v1/relationships", {"candidate_id": mb["domain_id"]}, a,
                                 HTTP_IDEMPOTENCY_KEY="matching-intent-001")
        self.status(code, 201, replay)
        self.assertEqual(replay["available_actions"], [])

    def test_request_idempotency_race_and_payload_conflict(self):
        a, ma = self.ready_account("alpha@example.invalid", "male")
        b, mb = self.ready_account("beta@example.invalid", "female")
        barrier = threading.Barrier(2)
        def request(_):
            try:
                barrier.wait(timeout=5)
                return self.call("POST", "/v1/relationships", {"candidate_id": mb["domain_id"]}, a,
                    client=Client(raise_request_exception=False), HTTP_IDEMPOTENCY_KEY="matching-race-001")
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(request, range(2)))
        self.assertTrue(all(code == 201 for code, _ in responses))
        self.assertEqual(responses[0][1]["id"], responses[1][1]["id"])
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.relationships")
            self.assertEqual(cursor.fetchone()[0], 1)
        code, _ = self.call("POST", "/v1/relationships", {"candidate_id": ma["domain_id"]}, a,
                            HTTP_IDEMPOTENCY_KEY="matching-race-001")
        self.status(code, 409)

    def test_accept_cancel_race_has_one_terminal_transition(self):
        a, ma, b, mb, rel = self.pair()
        barrier = threading.Barrier(2)
        def action(cancel):
            try:
                barrier.wait(timeout=5)
                client = Client(raise_request_exception=False)
                if cancel:
                    return self.call("POST", "/v1/relationships/"+rel["id"]+"/cancel", {}, a, client=client)[0]
                return self.respond(b, rel, client=client)[0]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(action, (True, False)))
        self.assertEqual(sorted(statuses), [200, 409])
        final = self.detail(a, rel["id"])
        self.assertIn(final["status"], ("cancelled", "accepted_pending_activation"))
        self.assertFalse(any(final["permissions"].values()))

    def test_reciprocal_preferences_and_discovery_changes_invalidate_accept(self):
        a, ma, b, mb, rel = self.pair()
        code, _ = self.call("PUT", "/v1/me/preferences", {"min_age": 18, "max_age": 19,
                            "countries": [], "marital_statuses": ["single"]}, a)
        self.status(code, 200)
        self.assertNotIn("accept", self.detail(b, rel["id"])["available_actions"])
        code, _ = self.respond(b, rel)
        self.status(code, 409)
        self.assertIsNotNone(self.detail(b, rel["id"])["peer"], "Temporary preference mismatch is not a new disclosure reset")

    def test_global_revoke_rejects_cached_matching_session(self):
        a, ma, b, mb, rel = self.pair()
        second = self.login(mb["email"])
        code, _ = self.call("POST", "/identity/v1/logout-all", {}, b)
        self.status(code, 200)
        code, _ = self.respond(second, rel)
        self.status(code, 401)
        code, _ = self.call("GET", "/v1/relationships", token=second)
        self.status(code, 401)

    def test_request_and_accept_survive_database_restart_with_hints_recomputed(self):
        a, ma, b, mb, rel = self.pair()
        connections.close_all()
        baseline.RESTART_DATABASE()
        incoming = self.detail(b, rel["id"])
        self.assertEqual(incoming["available_actions"], ["accept", "decline", "block", "report"])
        code, _ = self.respond(b, rel)
        self.status(code, 200)
        connections.close_all()
        baseline.RESTART_DATABASE()
        self.assertEqual(self.detail(a, rel["id"])["available_actions"], ["end", "block", "report"])

    def test_no_dialogue_content_endpoint_or_persistence_and_matching_answers_are_private(self):
        a, ma, b, mb, rel = self.pair()
        code, _ = self.call("POST", "/v1/me/assessment/answers", {"question_id": "family_plan", "option_id": "children"}, a)
        self.status(code, 200)
        code, candidates = self.call("GET", "/v1/candidates", token=b)
        self.status(code, 200, candidates)
        self.assertEqual(set(candidates["items"][0]), {"id", "alias", "age", "country", "marital_status", "marriage_goal", "rating", "synthetic"})
        marker = "forbidden-dialogue-payload-fixture"
        for path in ("/v1/messages", "/v1/outbox", "/v1/relationships/"+rel["id"]+"/cards",
                     "/v1/relationships/"+rel["id"]+"/answers"):
            code, _ = self.call("POST", path, {"card_id": "dialogue-001", "answer": marker}, a)
            self.status(code, 404)
        code, _ = self.call("POST", "/v1/reports", {"target_id": mb["domain_id"], "category": "harassment",
            "evidence": marker}, a, HTTP_IDEMPOTENCY_KEY="matching-content-reject")
        self.status(code, 400)
        with transaction.atomic(), service().repository.transaction() as state:
            self.assertTrue(marker not in repr(state), "Rejected dialogue must not enter domain persistence")
            self.assertTrue("direction" not in repr(state) and "available_actions" not in repr(state), "Projection hints are not persisted")

    def test_pending_verification_never_enters_matching_or_supplies_actor_authority(self):
        pending, _ = self.signup()
        for method, path, data in (("GET", "/v1/candidates", {}), ("GET", "/v1/relationships", {}),
                                   ("POST", "/v1/relationships", {"candidate_id": "usr_"+"0"*32})):
            code, _ = self.call(method, path, data, pending, HTTP_IDEMPOTENCY_KEY="matching-pending-001")
            self.status(code, 401)

    def test_direct_identity_service_without_authoritative_snapshot_fails_closed(self):
        a, ma, b, mb, rel = self.pair()
        with transaction.atomic():
            unsourced = IdentityDomainService(repository=SharedDomainRepository())
            self.assertEqual(unsourced.candidates(ma["domain_id"])["items"], [])
            view = unsourced.relationship(mb["domain_id"], rel["id"])
            self.assertIsNone(view["peer"])
            self.assertNotIn("accept", view["available_actions"])
