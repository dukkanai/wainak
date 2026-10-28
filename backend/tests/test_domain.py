import concurrent.futures
import json
import threading
import unittest
from datetime import date

from wainak.domain import DevelopmentService, DomainError, POLICY_VERSION


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.service = DevelopmentService(today=lambda: date(2026, 10, 24))
        self.counter = 0

    def create(self, gender="male", marital="single", wives=0, born="1996-01-01", ready=True):
        self.counter += 1
        value = self.service.register({"email": f"test-{self.counter}@example.invalid", "birth_date": born,
                                       "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        actor = value["account"]["id"]
        if ready:
            self.service.verify_email(actor, {"simulate_verified": True})
            self.service.update_profile(actor, {"gender": gender, "country": "SA", "marital_status": marital,
                                                "declared_wives": wives, "marriage_goal": "build_family", "discoverable": True})
            self.service.update_preferences(actor, {"min_age": 18, "max_age": 80, "countries": [],
                                                    "marital_statuses": ["single", "married", "divorced", "widowed"]})
        return actor, value["access_token"]

    def pair(self, activate=True):
        a, _ = self.create()
        b, _ = self.create("female")
        rel = self.service.request(a, {"candidate_id": b}, "request-001")["id"]
        self.service.respond(b, rel, {"decision": "accept"})
        if activate:
            self.service.activate(a, rel, {"simulate_entitlement": True})
        return a, b, rel

    def denied(self, code, fn, *args):
        with self.assertRaises(DomainError) as result:
            fn(*args)
        self.assertEqual(result.exception.code, code)

    def test_exact_18th_birthday_allowed_but_one_day_younger_denied(self):
        self.create(born="2008-10-24")
        self.denied("not_eligible", self.create, "male", "single", 0, "2008-10-25")

    def test_future_invalid_and_unknown_birthdate_denied(self):
        for value in ("2028-01-01", "not-a-date", "2000-02-30", None, "20081024"):
            with self.subTest(value=value), self.assertRaises(DomainError):
                self.create(born=value)

    def test_real_email_and_missing_current_consent_denied(self):
        base = {"email": "test@example.com", "birth_date": "1990-01-01", "is_muslim": True,
                "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION}
        self.denied("synthetic_email_required", self.service.register, base)
        base.update(email="test@example.invalid", terms_version="old")
        self.denied("consent_required", self.service.register, base)
        base.update(terms_version=POLICY_VERSION, is_muslim=1)
        self.denied("not_eligible", self.service.register, base)

    def test_unverified_incomplete_and_opted_out_accounts_hidden(self):
        a, _ = self.create()
        b, _ = self.create("female", ready=False)
        self.assertEqual(self.service.candidates(a)["items"], [])
        self.denied("not_found", self.service.request, a, {"candidate_id": b}, "request-001")
        c, _ = self.create("female")
        profile = self.service.me(c)["profile"]
        profile["discoverable"] = False
        self.service.update_profile(c, profile)
        self.assertEqual(self.service.candidates(a)["items"], [])

    def test_mutual_hard_preferences_filter_both_directions(self):
        a, _ = self.create()
        b, _ = self.create("female")
        prefs = self.service.me(b)["preferences"]
        prefs["countries"] = ["GB"]
        self.service.update_preferences(b, prefs)
        self.assertEqual(self.service.candidates(a)["items"], [])
        self.assertEqual(self.service.candidates(b)["items"], [])
        self.denied("not_found", self.service.candidate, a, b)

    def test_public_projection_never_includes_private_fields(self):
        a, _ = self.create()
        b, _ = self.create("female")
        candidate = self.service.candidate(a, b)
        self.assertEqual(set(candidate), {"id", "alias", "age", "country", "marital_status", "marriage_goal", "rating", "synthetic"})
        self.assertEqual(candidate["rating"], {"state": "insufficient_data"})
        payload = json.dumps(candidate)
        for forbidden in ("@", "birth_date", "declared_wives", "assessment_answers", "preferences", "health"):
            self.assertNotIn(forbidden, payload)

    def test_health_and_contact_fields_rejected_instead_of_silently_stored(self):
        a, _ = self.create()
        for field in ("health", "phone", "real_name", "photo", "identity_verified"):
            data = self.service.me(a)["profile"]
            data[field] = "private"
            self.denied("invalid_input", self.service.update_profile, a, data)

    def test_married_female_and_four_wives_ineligible_even_without_links(self):
        a, _ = self.create("male", "married", 4)
        b, _ = self.create("female")
        c, _ = self.create("female", "married")
        d, _ = self.create()
        self.assertEqual(self.service.candidates(a)["items"], [])
        self.denied("not_found", self.service.request, b, {"candidate_id": a}, "request-001")
        self.denied("not_found", self.service.request, d, {"candidate_id": c}, "request-002")

    def test_declared_wives_not_link_count_and_not_public(self):
        a, _ = self.create("male", "married", 3)
        b, _ = self.create("female")
        self.assertEqual(self.service.candidate(b, a)["marital_status"], "married")
        self.assertNotIn("declared_wives", self.service.candidate(b, a))
        data = self.service.me(a)["profile"]
        data["declared_wives"] = True
        self.denied("invalid_input", self.service.update_profile, a, data)

    def test_assessment_adapts_and_clears_stale_branch_on_revision(self):
        a, _ = self.create()
        state = self.service.answer(a, {"question_id": "family_plan", "option_id": "children"})
        self.assertEqual(state["next_question"]["id"], "parenting")
        self.service.answer(a, {"question_id": "parenting", "option_id": "shared_planning"})
        state = self.service.answer(a, {"question_id": "communication", "option_id": "listen_first"})
        self.assertTrue(state["complete"])
        state = self.service.answer(a, {"question_id": "family_plan", "option_id": "prefer_not_to_say"})
        self.assertEqual(state["answers"], {"family_plan": "prefer_not_to_say"})
        self.assertEqual(state["next_question"]["id"], "life_priorities")

    def test_assessment_cannot_skip_or_submit_free_text_or_leak_to_peer(self):
        a, b, rel = self.pair()
        self.denied("question_not_current", self.service.answer, a, {"question_id": "communication", "option_id": "listen_first"})
        self.denied("invalid_input", self.service.answer, a, {"question_id": "family_plan", "option_id": "my text"})
        self.service.answer(a, {"question_id": "family_plan", "option_id": "children"})
        self.assertEqual(self.service.assessment(b)["answers"], {})
        self.assertNotIn("assessment", json.dumps(self.service.relationship(b, rel)))

    def test_idempotency_returns_one_current_relationship_and_rejects_payload_change(self):
        a, _ = self.create()
        b, _ = self.create("female")
        c, _ = self.create("female")
        first = self.service.request(a, {"candidate_id": b}, "request-001")
        self.assertEqual(first, self.service.request(a, {"candidate_id": b}, "request-001"))
        self.denied("idempotency_conflict", self.service.request, a, {"candidate_id": c}, "request-001")
        self.service.block(b, {"target_id": a})
        replay = self.service.request(a, {"candidate_id": b}, "request-001")
        self.assertEqual(replay["status"], "blocked")
        self.assertFalse(replay["permissions"]["can_send_cards"])

    def test_idempotency_key_scoped_per_actor(self):
        a, _ = self.create()
        b, _ = self.create("female")
        c, _ = self.create()
        d, _ = self.create("female")
        one = self.service.request(a, {"candidate_id": b}, "same-key")
        two = self.service.request(c, {"candidate_id": d}, "same-key")
        self.assertNotEqual(one["id"], two["id"])

    def test_self_request_and_self_acceptance_denied(self):
        a, _ = self.create()
        b, _ = self.create("female")
        self.denied("not_found", self.service.request, a, {"candidate_id": a}, "request-001")
        rel = self.service.request(a, {"candidate_id": b}, "request-002")["id"]
        self.denied("recipient_required", self.service.respond, a, rel, {"decision": "accept"})
        self.denied("invalid_transition", self.service.activate, a, rel, {"simulate_entitlement": True})

    def test_mutual_acceptance_still_requires_separate_dev_activation(self):
        a, b, rel = self.pair(activate=False)
        self.assertEqual(self.service.relationship(a, rel)["status"], "accepted_pending_activation")
        self.assertFalse(self.service.relationship(a, rel)["permissions"]["can_send_cards"])
        self.denied("initiator_required", self.service.activate, b, rel, {"simulate_entitlement": True})
        self.assertTrue(self.service.activate(a, rel, {"simulate_entitlement": True})["permissions"]["can_send_cards"])

    def test_third_party_cannot_read_respond_activate_end_or_view_cards(self):
        a, b, rel = self.pair()
        c, _ = self.create()
        for fn, args in ((self.service.relationship, (c, rel)), (self.service.respond, (c, rel, {"decision": "accept"})),
                         (self.service.activate, (c, rel, {"simulate_entitlement": True})),
                         (self.service.end, (c, rel, {"confirm": True})), (self.service.content, (c, rel))):
            self.denied("not_found", fn, *args)

    def test_late_activation_cannot_override_block_end_or_changed_eligibility(self):
        for transition in ("block", "end", "four_wives"):
            with self.subTest(transition=transition):
                a, b, rel = self.pair(activate=False)
                if transition == "block":
                    self.service.block(b, {"target_id": a})
                elif transition == "end":
                    self.service.end(b, rel, {"confirm": True})
                else:
                    profile = self.service.me(a)["profile"]
                    profile.update(marital_status="married", declared_wives=4)
                    self.service.update_profile(a, profile)
                with self.assertRaises(DomainError):
                    self.service.activate(a, rel, {"simulate_entitlement": True})

    def test_cancel_and_decline_do_not_reopen_on_repeated_request(self):
        a, _ = self.create()
        b, _ = self.create("female")
        rel = self.service.request(a, {"candidate_id": b}, "request-001")["id"]
        self.service.cancel(a, rel, {})
        self.denied("invalid_transition", self.service.respond, b, rel, {"decision": "accept"})
        self.denied("relationship_exists", self.service.request, a, {"candidate_id": b}, "request-002")

    def test_exclusivity_mutual_and_never_unlocks_photo_identity_or_text(self):
        a, b, rel = self.pair()
        self.service.request_exclusive(a, rel, {"confirm": True})
        self.denied("recipient_required", self.service.respond_exclusive, a, rel, {"decision": "accept"})
        result = self.service.respond_exclusive(b, rel, {"decision": "accept"})
        self.assertEqual(result["status"], "exclusive_cards")
        self.assertEqual(result["permissions"], {"can_send_cards": True, "can_send_text": False,
                                                "can_send_media": False, "can_disclose_identity": False})
        self.assertEqual(self.service.candidates(a)["items"], [])

    def test_simultaneous_exclusivity_has_one_winner_and_freezes_other_relation(self):
        a, b, first = self.pair()
        c, _ = self.create("female")
        second = self.service.request(a, {"candidate_id": c}, "request-002")["id"]
        self.service.respond(c, second, {"decision": "accept"})
        self.service.activate(a, second, {"simulate_entitlement": True})
        self.service.request_exclusive(a, first, {"confirm": True})
        self.service.request_exclusive(a, second, {"confirm": True})
        barrier = threading.Barrier(2)
        def accept(actor, rel):
            barrier.wait()
            try:
                self.service.respond_exclusive(actor, rel, {"decision": "accept"})
                return True
            except DomainError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(accept, b, first), executor.submit(accept, c, second)]
            self.assertEqual(sum(f.result() for f in futures), 1)
        statuses = [self.service.relationship(a, rel)["status"] for rel in (first, second)]
        self.assertEqual(set(statuses), {"exclusive_cards", "frozen"})

    def test_simultaneous_duplicate_requests_create_one_pair(self):
        a, _ = self.create()
        b, _ = self.create("female")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            values = list(executor.map(lambda _: self.service.request(a, {"candidate_id": b}, "same-key"), range(20)))
        self.assertEqual(len({v["id"] for v in values}), 1)
        self.assertEqual(len(self.service.relationships), 1)

    def test_block_revokes_cards_exclusivity_and_keeps_marital_declaration(self):
        a, b, rel = self.pair()
        profile = self.service.me(a)["profile"]
        profile.update(marital_status="married", declared_wives=3)
        self.service.update_profile(a, profile)
        self.service.request_exclusive(a, rel, {"confirm": True})
        self.service.respond_exclusive(b, rel, {"decision": "accept"})
        self.service.block(b, {"target_id": a})
        self.assertEqual(self.service.me(a)["profile"]["declared_wives"], 3)
        self.assertIsNone(self.service.accounts[a]["exclusive_relationship_id"])
        self.denied("relationship_unavailable", self.service.content, a, rel)
        self.assertIsNone(self.service.relationship(a, rel)["peer"])

    def test_block_candidate_then_report_without_payment_or_relationship(self):
        a, _ = self.create()
        b, _ = self.create("female")
        self.service.block(a, {"target_id": b})
        self.service.block(a, {"target_id": b})
        result = self.service.report(a, {"target_id": b, "category": "child_safety"})
        self.assertFalse(result["evidence_uploaded"])
        self.assertTrue(self.service.me(b)["eligible_for_discovery"])

    def test_report_rejects_content_and_cross_relationship_attribution(self):
        a, b, rel = self.pair()
        c, _ = self.create("female")
        self.denied("invalid_input", self.service.report, a, {"target_id": b, "category": "harassment", "conversation": "sensitive"})
        self.denied("not_found", self.service.report, a, {"target_id": c, "category": "harassment", "relationship_id": rel})
        self.assertEqual(self.service.reports, {})

    def test_target_cannot_prevent_known_candidate_reporting_by_blocking_first(self):
        a, _ = self.create()
        b, _ = self.create("female")
        self.assertEqual(self.service.candidate(b, a)["id"], a)
        self.service.block(a, {"target_id": b})
        report = self.service.report(b, {"target_id": a, "category": "harassment"})
        self.assertEqual(report["status"], "recorded_development_only")
        self.denied("not_found", self.service.candidate, b, a)
        self.assertEqual(self.service.candidates(b)["items"], [])
        self.denied("not_found", self.service.request, b, {"candidate_id": a}, "request-001")

    def test_deletion_revokes_session_erases_private_data_and_disables_peer(self):
        a, token = self.create()
        b, _ = self.create("female")
        rel = self.service.request(a, {"candidate_id": b}, "request-001")["id"]
        self.service.respond(b, rel, {"decision": "accept"})
        self.denied("confirmation_required", self.service.delete_account, a, {"confirmation": "yes"})
        self.service.delete_account(a, {"confirmation": "DELETE"})
        self.denied("unauthenticated", self.service.authenticate, token)
        self.assertEqual(set(self.service.accounts[a]), {"id", "deleted", "exclusive_relationship_id"})
        self.assertIsNone(self.service.relationship(b, rel)["peer"])
        self.assertEqual(self.service.relationship(b, rel)["status"], "ended")
        self.assertEqual(self.service.candidates(b)["items"], [])

    def test_returned_objects_cannot_mutate_server_state(self):
        a, _ = self.create()
        view = self.service.me(a)
        view["profile"]["declared_wives"] = 99
        view["preferences"]["countries"].append("GB")
        self.assertEqual(self.service.me(a)["profile"]["declared_wives"], 0)
        self.assertEqual(self.service.me(a)["preferences"]["countries"], [])

    def test_no_plaintext_session_tokens_stored(self):
        a, token = self.create()
        self.assertNotIn(token, json.dumps(self.service.accounts))
        self.assertNotIn(token, self.service.sessions)
        self.assertEqual(self.service.authenticate(token), a)


if __name__ == "__main__":
    unittest.main()
