"""Independent adversarial checks for the synthetic phase-one backend only.

Run against an archived exact candidate with PYTHONPATH=<snapshot>/backend.
No socket, database, mail, payment, credential files, or production code changes.
"""
import concurrent.futures
import io
import json
import threading
import unittest
from datetime import date
from wainek.api import DevelopmentApplication
from wainek.domain import DevelopmentService, DomainError, POLICY_VERSION


class IndependentBackendReview(unittest.TestCase):
    def setUp(self):
        self.s = DevelopmentService(today=lambda: date(2026, 10, 24))
        self.app = DevelopmentApplication(enable_development=True, service=self.s)
        self.seq = 0

    def api(self, method, path, data=None, token=None, key=None, extra=None):
        raw = json.dumps(data if data is not None else {}).encode()
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": "localhost",
               "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(raw)),
               "wsgi.input": io.BytesIO(raw)}
        if token is not None:
            env["HTTP_AUTHORIZATION"] = "Bearer " + token
        if key:
            env["HTTP_IDEMPOTENCY_KEY"] = key
        env.update(extra or {})
        captured = {}
        def start(status, headers):
            captured["status"] = int(status.split()[0])
            captured["headers"] = dict(headers)
        body = json.loads(b"".join(self.app(env, start)))
        return captured["status"], body, captured["headers"]

    def account(self, gender="male", status="single", wives=0):
        self.seq += 1
        result = self.s.register({"email": f"independent{self.seq}@example.invalid",
            "birth_date": "1994-01-10", "is_muslim": True,
            "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        actor, token = result["account"]["id"], result["access_token"]
        self.s.verify_email(actor, {"simulate_verified": True})
        self.s.update_profile(actor, {"gender": gender, "country": "SA",
            "marital_status": status, "declared_wives": wives,
            "marriage_goal": "build_family", "discoverable": True})
        self.s.update_preferences(actor, {"min_age": 18, "max_age": 99,
            "countries": [], "marital_statuses": ["single", "married", "divorced", "widowed"]})
        return actor, token

    def opened(self, a, b):
        rel = self.s.request(a, {"candidate_id": b}, f"openpair-{len(self.s.relationships)}")["id"]
        self.s.respond(b, rel, {"decision": "accept"})
        self.s.activate(a, rel, {"simulate_entitlement": True})
        return rel

    def test_api_age_and_current_consent_gate_cannot_be_skipped(self):
        base = {"email": "agecheck@example.invalid", "birth_date": "2008-10-25",
                "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION}
        for patch in ({}, {"birth_date": "2008-10-24", "is_muslim": False},
                      {"birth_date": "2008-10-24", "privacy_version": "old"},
                      {"birth_date": None}, {"birth_date": True}):
            data = base | patch
            self.assertIn(self.api("POST", "/v1/dev/accounts", data)[0], (400, 403))
            self.assertEqual(len(self.s.accounts), 0)
        self.assertEqual(self.api("POST", "/v1/dev/accounts", base | {"birth_date": "2008-10-24"})[0], 201)

    def test_third_party_every_relationship_action_and_report_attribution_denied(self):
        a, ta = self.account()
        b, tb = self.account("female")
        c, tc = self.account()
        rel = self.opened(a, b)
        probes = [
            ("GET", f"/v1/relationships/{rel}", None),
            ("GET", f"/v1/relationships/{rel}/cards", None),
            ("POST", f"/v1/relationships/{rel}/respond", {"decision": "accept"}),
            ("POST", f"/v1/relationships/{rel}/cancel", {}),
            ("POST", f"/v1/relationships/{rel}/end", {"confirm": True}),
            ("POST", f"/v1/relationships/{rel}/exclusive/request", {"confirm": True}),
            ("POST", f"/v1/relationships/{rel}/exclusive/respond", {"decision": "accept"}),
            ("POST", f"/v1/dev/relationships/{rel}/activate", {"simulate_entitlement": True}),
            ("POST", "/v1/reports", {"target_id": b, "category": "harassment", "relationship_id": rel}),
        ]
        for method, path, body in probes:
            with self.subTest(method=method, action=path.rsplit("/", 1)[-1]):
                status, result, _ = self.api(method, path, body, tc)
                self.assertEqual(status, 404)
                self.assertEqual(result["error"]["code"], "not_found")
        self.assertEqual(self.api("GET", "/v1/relationships", token=tc)[1], {"items": [], "next_cursor": None})
        self.assertEqual(self.s.relationship(a, rel)["status"], "active_cards")

    def test_candidate_and_relationship_responses_are_private_allowlists(self):
        a, ta = self.account()
        b, tb = self.account("female")
        self.s.answer(b, {"question_id": "family_plan", "option_id": "children"})
        rel = self.opened(a, b)
        candidate = self.api("GET", f"/v1/relationships/{rel}", token=ta)[1]["peer"]
        self.assertEqual(set(candidate), {"id", "alias", "age", "country", "marital_status",
                                         "marriage_goal", "rating", "synthetic"})
        blob = json.dumps(candidate)
        for private in ("email", "birth_date", "assessment_answers", "declared_wives", "access_token", "health"):
            self.assertNotIn(private, blob)
        for field in ("can_send_text", "can_send_media", "can_disclose_identity"):
            self.assertFalse(self.s.relationship(a, rel)["permissions"][field])

    def test_replay_returns_current_block_not_stale_purchase_right(self):
        a, ta = self.account()
        b, tb = self.account("female")
        status, result, _ = self.api("POST", "/v1/relationships", {"candidate_id": b}, ta, "repeat-key-1")
        self.assertEqual(status, 201)
        rel = result["id"]
        self.s.respond(b, rel, {"decision": "accept"})
        self.s.activate(a, rel, {"simulate_entitlement": True})
        self.s.block(b, {"target_id": a})
        status, replay, _ = self.api("POST", "/v1/relationships", {"candidate_id": b}, ta, "repeat-key-1")
        self.assertEqual(status, 201)
        self.assertEqual(replay["status"], "blocked")
        self.assertIsNone(replay["peer"])
        self.assertFalse(any(replay["permissions"].values()))
        self.assertEqual(self.api("POST", f"/v1/dev/relationships/{rel}/activate",
                                 {"simulate_entitlement": True}, ta)[0], 409)

    def test_key_conflict_and_actor_scope_do_not_expose_other_relationship(self):
        a, ta = self.account()
        b, tb = self.account("female")
        c, tc = self.account()
        d, td = self.account("female")
        r1 = self.api("POST", "/v1/relationships", {"candidate_id": b}, ta, "shared-key-1")[1]["id"]
        r2 = self.api("POST", "/v1/relationships", {"candidate_id": d}, tc, "shared-key-1")[1]["id"]
        self.assertNotEqual(r1, r2)
        self.assertEqual(self.api("POST", "/v1/relationships", {"candidate_id": d}, ta, "shared-key-1")[0], 409)
        self.assertEqual(self.api("GET", f"/v1/relationships/{r1}", token=tc)[0], 404)

    def test_block_wins_activation_race_in_40_isolated_trials(self):
        for trial in range(40):
            a, ta = self.account()
            b, tb = self.account("female")
            rel = self.s.request(a, {"candidate_id": b}, f"race-key-{trial}")["id"]
            self.s.respond(b, rel, {"decision": "accept"})
            barrier = threading.Barrier(2)
            def activate():
                barrier.wait()
                try:
                    self.s.activate(a, rel, {"simulate_entitlement": True})
                except DomainError as exc:
                    self.assertEqual(exc.status, 409)
            def block():
                barrier.wait()
                self.s.block(b, {"target_id": a})
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(activate), pool.submit(block)]
                for future in futures:
                    future.result(timeout=3)
            result = self.s.relationship(a, rel)
            self.assertEqual(result["status"], "blocked")
            self.assertFalse(any(result["permissions"].values()))

    def test_opposite_direction_request_race_creates_only_one_pair(self):
        a, ta = self.account()
        b, tb = self.account("female")
        barrier = threading.Barrier(2)
        def attempt(actor, target):
            barrier.wait()
            try:
                return self.s.request(actor, {"candidate_id": target}, "opposite-key")["id"]
            except DomainError as exc:
                self.assertEqual(exc.code, "relationship_exists")
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, a, b), pool.submit(attempt, b, a)]
            results = [f.result(timeout=3) for f in futures]
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.s.relationships), 1)

    def test_delete_revokes_existing_token_and_peer_gets_no_private_data(self):
        a, ta = self.account()
        b, tb = self.account("female")
        rel = self.opened(a, b)
        self.assertEqual(self.api("DELETE", "/v1/me", {"confirmation": "DELETE"}, tb)[0], 200)
        self.assertEqual(self.api("GET", "/v1/me", token=tb)[0], 401)
        self.assertEqual(self.api("POST", "/v1/dev/verify-email", {"simulate_verified": True}, tb)[0], 401)
        peer = self.api("GET", f"/v1/relationships/{rel}", token=ta)[1]
        self.assertEqual(peer["status"], "ended")
        self.assertIsNone(peer["peer"])
        self.assertFalse(any(peer["permissions"].values()))

    def test_messaging_upload_and_sensitive_fields_fail_closed(self):
        a, ta = self.account()
        b, tb = self.account("female")
        rel = self.opened(a, b)
        for action in ("messages", "photos", "identity", "evidence", "answers"):
            self.assertEqual(self.api("POST", f"/v1/relationships/{rel}/{action}", {"text": "synthetic"}, ta)[0], 404)
        for field in ("text", "evidence", "messages", "health"):
            result = self.api("POST", "/v1/reports", {"target_id": b, "category": "harassment", field: "synthetic"}, ta)
            self.assertEqual(result[0], 400)
        self.assertEqual(self.s.reports, {})

    def test_simulated_cards_dont_claim_implemented_transport(self):
        a, ta = self.account()
        b, tb = self.account("female")
        rel = self.opened(a, b)
        result = self.api("GET", f"/v1/relationships/{rel}/cards", token=ta)[1]
        self.assertEqual(result["answers_transport"], "not_implemented")
        self.assertFalse(result["server_stores_dialogue_answers"])
        self.assertTrue(all(card["free"] for card in result["items"]))

    def test_known_candidate_can_report_even_after_target_blocks_them_first(self):
        # A candidate cannot evade B's safety complaint by blocking B before a request exists.
        a, ta = self.account()
        b, tb = self.account("female")
        known = self.api("GET", "/v1/candidates", token=tb)[1]["items"]
        self.assertIn(a, [item["id"] for item in known])
        self.assertEqual(self.api("POST", "/v1/blocks", {"target_id": b}, ta)[0], 200)
        status, result, _ = self.api("POST", "/v1/reports", {"target_id": a, "category": "harassment"}, tb)
        self.assertEqual(status, 201, "Known target's block must not disable the other person's reporting route")
        self.assertFalse(result["evidence_uploaded"])

    def test_dev_headers_and_no_cross_origin_bypass(self):
        a, ta = self.account()
        status, result, headers = self.api("GET", "/v1/me", token=ta)
        self.assertEqual(status, 200)
        self.assertEqual(result["mode"], "synthetic_development_only")
        self.assertEqual(headers["Cache-Control"], "no-store")
        for origin in ("null", "http://localhost", "https://example.invalid"):
            self.assertEqual(self.api("GET", "/v1/me", token=ta, extra={"HTTP_ORIGIN": origin})[0], 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
