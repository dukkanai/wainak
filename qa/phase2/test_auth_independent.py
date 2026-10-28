"""Independent auth adversarial cases. All credentials stay in fixture memory."""
import json
import secrets
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest import mock

from asgiref.sync import async_to_sync
from cryptography.fernet import Fernet
from django.conf import settings
from django.core import mail
from django.db import connection, connections, transaction
from django.test import Client, override_settings
from django.utils import timezone
from allauth.account.models import EmailAddress
from wainak.domain import POLICY_VERSION
from wainak_identity.mailbox import OUTBOX
from wainak_identity.models import User, DigestSession, RateBucket, MutationReceipt, DeletionReceipt
from wainak_identity.repository import service
from wainak_identity.sessions import SessionStore, digest_token, email_fingerprint
from wainak_identity import rate_limits

AUTH = "/_allauth/app/v1/"
RESTART_DATABASE = None


class IndependentIdentityTests(unittest.TestCase):
    def setUp(self):
        connections.close_all()
        User.objects.all().delete()
        DigestSession.objects.all().delete()
        RateBucket.objects.all().delete()
        DeletionReceipt.objects.all().delete()
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE wainak_phase1_dev.accounts CASCADE")
        OUTBOX.clear()
        if hasattr(mail, "outbox"):
            mail.outbox.clear()
        self.password = secrets.token_urlsafe(24) + "!7aZ"

    def tearDown(self):
        connections.close_all()
        OUTBOX.clear()
        if hasattr(mail, "outbox"):
            mail.outbox.clear()

    def call(self, method, path, data=None, token=None, **headers):
        # Fresh client: this is X-Session-Token native auth, never ambient cookies.
        kwargs = {"HTTP_HOST": "localhost", "REMOTE_ADDR": "127.0.0.1"}
        if token is not None:
            kwargs["HTTP_X_SESSION_TOKEN"] = token
        kwargs.update(headers)
        response = Client(raise_request_exception=False, enforce_csrf_checks=True).generic(
            method, path, data=json.dumps(data or {}).encode(),
            content_type="application/json", **kwargs)
        try:
            body = json.loads(response.content)
        except (ValueError, UnicodeError):
            self.fail("Expected safe JSON, not response content or a traceback")
        return response.status_code, body, response

    def expect_status(self, response, expected):
        # Never include response bodies, headers, credentials or mailbox operands.
        self.assertEqual(response[0], expected, "Unexpected HTTP status")

    def signup(self, email, *, password=None):
        response = self.call("POST", AUTH + "auth/signup", {
            "email": email, "password": password or self.password,
            "birth_date": "1995-01-01", "is_muslim": True,
            "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.expect_status(response, 401)
        token = response[1].get("meta", {}).get("session_token")
        messages = [m for m in OUTBOX if m["recipient"] == email and m.get("code")]
        self.assertTrue(isinstance(token, str) and bool(messages),
                        "Expected a private pending session and fake verification message")
        return token, messages[-1]["code"]

    def account(self, email):
        pending, code = self.signup(email)
        response = self.call("POST", AUTH + "auth/email/verify", {"key": code}, pending)
        self.expect_status(response, 200)
        token = response[1].get("meta", {}).get("session_token", pending)
        self.assertTrue(token != pending, "Login must rotate the pending session")
        response = self.call("GET", "/identity/v1/me", token=token)
        self.expect_status(response, 200)
        return token, response[1]

    def reset_link(self, email, *, issue_at=None):
        if issue_at is None:
            response = self.call("POST", AUTH + "auth/password/request", {"email": email})
        else:
            with mock.patch("django.contrib.auth.tokens.PasswordResetTokenGenerator._now", return_value=issue_at):
                response = self.call("POST", AUTH + "auth/password/request", {"email": email})
        self.expect_status(response, 200)
        messages = [m for m in OUTBOX if m["recipient"] == email and m.get("reset_url")]
        self.assertTrue(bool(messages), "Expected reset data only in the fake mailbox")
        return messages[-1]["reset_url"].split("/reset/", 1)[1]

    def matching_pair(self):
        a, ma = self.account("qa_a@example.invalid")
        b, mb = self.account("qa_b@example.invalid")
        for token, gender in ((a, "male"), (b, "female")):
            self.expect_status(self.call("PUT", "/v1/me/profile", {
                "gender": gender, "country": "SA", "marital_status": "single",
                "declared_wives": 0, "marriage_goal": "build_family",
                "discoverable": True}, token), 200)
            self.expect_status(self.call("PUT", "/v1/me/preferences", {
                "min_age": 18, "max_age": 60, "countries": [],
                "marital_statuses": ["single"]}, token), 200)
        return a, ma, b, mb

    def test_verify_code_is_session_bound_and_expired_code_cannot_authenticate(self):
        # Controlled, distinct synthetic codes make cross-session binding deterministic.
        with mock.patch("wainak_identity.adapters.AccountAdapter.generate_email_verification_code",
                        side_effect=["111111", "222222"]):
            a, ca = self.signup("qa_a@example.invalid")
            b, cb = self.signup("qa_b@example.invalid")
        rejected = self.call("POST", AUTH + "auth/email/verify", {"key": ca}, b)
        self.assertTrue(rejected[0] in (400, 401, 403, 409, 410), "Cross-session code must fail closed")
        self.assertEqual(EmailAddress.objects.filter(verified=True).count(), 0)
        current = time.time()
        with mock.patch("allauth.account.internal.flows.code_verification.time.time", return_value=current + 601):
            rejected = self.call("POST", AUTH + "auth/email/verify", {"key": cb}, b)
        self.assertTrue(rejected[0] in (400, 401, 403, 409, 410), "Expired code must not grant access")
        self.assertEqual(EmailAddress.objects.filter(verified=True).count(), 0)
        self.assertTrue(self.call("GET", "/v1/me", token=b)[0] in (401, 403))
        # A remains usable at the documented inclusive 600-second code boundary.
        issued_at = SessionStore(a).get("account_email_verification_code")["at"]
        with mock.patch("allauth.account.internal.flows.code_verification.time.time", return_value=issued_at + 600):
            self.expect_status(self.call("POST", AUTH + "auth/email/verify", {"key": ca}, a), 200)

    def test_reset_with_pending_token_invalidates_it_without_verifying_email(self):
        pending, verification = self.signup("qa_pending@example.invalid")
        key = self.reset_link("qa_pending@example.invalid")
        replacement = secrets.token_urlsafe(24) + "!7aZ"
        response = self.call("POST", AUTH + "auth/password/reset",
                             {"key": key, "password": replacement}, pending)
        self.expect_status(response, 401)
        self.assertFalse(EmailAddress.objects.get(email="qa_pending@example.invalid").verified)
        self.assertFalse(DigestSession.objects.filter(session_key=digest_token(pending)).exists())
        rejected = self.call("POST", AUTH + "auth/email/verify", {"key": verification}, pending)
        self.assertTrue(rejected[0] in (400, 401, 403, 409, 410))
        self.assertFalse(EmailAddress.objects.get(email="qa_pending@example.invalid").verified)
        self.expect_status(self.call("GET", "/identity/v1/me", token=pending), 401)

    def test_reset_of_b_does_not_log_out_unrelated_authenticated_actor_a(self):
        a, ma = self.account("qa_a@example.invalid")
        b, mb = self.account("qa_b@example.invalid")
        key = self.reset_link(mb["email"])
        replacement = secrets.token_urlsafe(24) + "!7aZ"
        response = self.call("POST", AUTH + "auth/password/reset",
                             {"key": key, "password": replacement}, a)
        self.expect_status(response, 200)  # Existing unrelated A remains authenticated.
        self.expect_status(self.call("GET", "/identity/v1/me", token=a), 200)
        self.expect_status(self.call("GET", "/identity/v1/me", token=b), 401)
        response = self.call("POST", AUTH + "auth/login", {"email": mb["email"], "password": replacement})
        self.expect_status(response, 200)
        self.assertTrue(response[1]["data"]["user"]["id"] == mb["id"])
        self.assertTrue(ma["id"] != mb["id"])

    def test_two_outstanding_reset_links_race_has_one_winner_and_revokes_sessions(self):
        token, me = self.account("qa_a@example.invalid")
        now = datetime.now()
        first = self.reset_link(me["email"], issue_at=now - timedelta(seconds=2))
        second = self.reset_link(me["email"], issue_at=now - timedelta(seconds=1))
        self.assertTrue(first != second, "Fixture must contain distinct reset links")
        replacements = [secrets.token_urlsafe(24) + "!7aZ" for _ in range(2)]
        barrier = threading.Barrier(2)
        def reset(index):
            try:
                barrier.wait(timeout=5)
                return self.call("POST", AUTH + "auth/password/reset",
                    {"key": (first, second)[index], "password": replacements[index]})[0]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reset, range(2)))
        self.assertEqual(sorted(results), [400, 401])
        user = User.objects.get(pk=me["id"])
        self.assertEqual(sum(user.check_password(p) for p in replacements), 1)
        self.expect_status(self.call("GET", "/identity/v1/me", token=token), 401)
        self.expect_status(self.call("POST", AUTH + "auth/password/reset",
            {"key": first, "password": self.password}), 400)
        self.expect_status(self.call("POST", AUTH + "auth/password/reset",
            {"key": second, "password": self.password}), 400)

    def test_expired_reset_and_wrong_purpose_do_not_change_password_or_verification(self):
        token, me = self.account("qa_a@example.invalid")
        expired = self.reset_link(me["email"], issue_at=datetime.now() - timedelta(seconds=602))
        self.expect_status(self.call("POST", AUTH + "auth/password/reset",
            {"key": expired, "password": secrets.token_urlsafe(24) + "!7aZ"}), 400)
        pending, verification = self.signup("qa_b@example.invalid")
        self.expect_status(self.call("POST", AUTH + "auth/password/reset",
            {"key": verification, "password": self.password}), 400)
        rejected = self.call("POST", AUTH + "auth/email/verify", {"key": expired}, pending)
        self.assertTrue(rejected[0] in (400, 401, 403, 409, 410))
        self.assertFalse(EmailAddress.objects.get(email="qa_b@example.invalid").verified)
        self.assertTrue(User.objects.get(pk=me["id"]).check_password(self.password))
        self.expect_status(self.call("GET", "/identity/v1/me", token=token), 200)
        issued_at = datetime.now().replace(microsecond=0)
        boundary_key = self.reset_link(me["email"], issue_at=issued_at)
        with mock.patch("django.contrib.auth.tokens.PasswordResetTokenGenerator._now",
                        return_value=issued_at + timedelta(seconds=600)):
            self.expect_status(self.call("POST", AUTH + "auth/password/reset",
                {"key": boundary_key, "password": secrets.token_urlsafe(24) + "!7aZ"}), 401)
        self.expect_status(self.call("GET", "/identity/v1/me", token=token), 401)

    def test_idle_read_refreshes_but_never_extends_absolute_session_cap(self):
        token, _ = self.account("qa_a@example.invalid")
        now = timezone.now()
        absolute = now + timedelta(seconds=100)
        DigestSession.objects.filter(session_key=digest_token(token)).update(
            created_at=absolute - timedelta(seconds=settings.WAINAK_SESSION_ABSOLUTE_SECONDS),
            last_seen_at=now - timedelta(seconds=1700), expire_date=now + timedelta(seconds=50))
        with mock.patch("django.utils.timezone.now", return_value=now):
            self.expect_status(self.call("GET", "/v1/relationships", token=token), 200)
        row = DigestSession.objects.get(session_key=digest_token(token))
        self.assertEqual(row.last_seen_at, now)
        self.assertLessEqual(row.expire_date, absolute)
        with mock.patch("django.utils.timezone.now", return_value=absolute - timedelta(seconds=1)):
            self.expect_status(self.call("GET", "/v1/relationships", token=token), 200)
        with mock.patch("django.utils.timezone.now", return_value=absolute):
            self.expect_status(self.call("GET", "/v1/relationships", token=token), 401)
        other, _ = self.account("qa_idle@example.invalid")
        idle_now = timezone.now()
        DigestSession.objects.filter(session_key=digest_token(other)).update(
            last_seen_at=idle_now - timedelta(seconds=settings.WAINAK_SESSION_IDLE_SECONDS),
            expire_date=idle_now + timedelta(seconds=100))
        with mock.patch("django.utils.timezone.now", return_value=idle_now):
            self.expect_status(self.call("GET", "/identity/v1/me", token=other), 401)

    def test_ciphertext_swap_wrong_key_and_digest_as_bearer_fail_closed(self):
        a, _ = self.account("qa_a@example.invalid")
        b, _ = self.account("qa_b@example.invalid")
        row_a = DigestSession.objects.get(session_key=digest_token(a))
        DigestSession.objects.filter(session_key=digest_token(b)).update(session_data=row_a.session_data)
        self.expect_status(self.call("GET", "/identity/v1/me", token=b), 401)
        self.expect_status(self.call("GET", "/identity/v1/me", token=a), 200)
        self.expect_status(self.call("GET", "/identity/v1/me", token=digest_token(a)), 401)
        with override_settings(WAINAK_SESSION_ENCRYPTION_KEY=Fernet.generate_key()):
            self.expect_status(self.call("GET", "/identity/v1/me", token=a), 401)

    def test_async_session_cycle_flush_and_manager_guards_do_not_store_raw_secrets(self):
        async def exercise():
            session = SessionStore()
            session["qa_fixture"] = "synthetic"
            await session.acreate()
            old = session.session_key
            loaded = await SessionStore(old).aload()
            self.assertTrue(loaded.get("qa_fixture") == "synthetic")
            await session.acycle_key()
            new = session.session_key
            self.assertTrue(new != old)
            self.assertFalse(await SessionStore().aexists(old))
            self.assertTrue(await SessionStore().aexists(new))
            await session.aflush()
            self.assertFalse(await SessionStore().aexists(new))
            return old, new
        old, new = async_to_sync(exercise)()
        serialized = json.dumps(list(DigestSession.objects.values("session_key", "session_data")))
        self.assertTrue(old not in serialized and new not in serialized)
        with self.assertRaises(RuntimeError):
            DigestSession.objects.encode({"fixture": "no raw storage"})
        with self.assertRaises(RuntimeError):
            DigestSession.objects.save(old, {"fixture": "no raw storage"}, timezone.now())

    def test_atomic_rate_counter_uses_distinct_connections_and_exact_limit(self):
        now = timezone.now()
        barrier = threading.Barrier(2)
        def worker(index):
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pid = cursor.fetchone()[0]
                barrier.wait(timeout=5)
                accepted = []
                for _ in range(4):
                    with transaction.atomic():
                        accepted.append(rate_limits.consume("qa_atomic", "fixture", "same_subject", 3, 60, now=now))
                return pid, sum(accepted)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertEqual(len({p for p, _ in results}), 2)
        self.assertEqual(sum(n for _, n in results), 3)
        key = rate_limits.subject_digest("qa_atomic", "fixture", "same_subject")
        self.assertEqual(RateBucket.objects.get(pk=key).count, 3)
        with transaction.atomic():
            self.assertFalse(rate_limits.consume("qa_atomic", "fixture", "same_subject", 3, 60, now=now))
            self.assertTrue(rate_limits.consume("qa_atomic", "fixture", "same_subject", 3, 60, now=now + timedelta(seconds=60)))
        self.assertEqual(RateBucket.objects.get(pk=key).count, 1)

    def test_forwarded_ip_and_email_case_do_not_bypass_login_limit(self):
        for index in range(6):
            email = " QA_UNKNOWN@example.invalid " if index % 2 else "qa_unknown@example.invalid"
            response = self.call("POST", AUTH + "auth/login",
                {"email": email, "password": self.password},
                HTTP_X_FORWARDED_FOR="198.51.100." + str(index + 1))
            if index < 5:
                self.assertTrue(response[0] in (400, 401), "Expected generic rejected login")
            else:
                self.expect_status(response, 429)
                self.assertTrue(response[2].get("Retry-After", "").isdigit())

    def test_reset_enumeration_and_duplicate_signup_do_not_replace_identity(self):
        _, me = self.account("qa_a@example.invalid")
        known = self.call("POST", AUTH + "auth/password/request", {"email": me["email"]})
        unknown = self.call("POST", AUTH + "auth/password/request", {"email": "qa_unknown@example.invalid"})
        self.expect_status(known, 200)
        self.expect_status(unknown, 200)
        self.assertTrue(known[1] == unknown[1], "Public reset response must not enumerate accounts")
        duplicate = self.call("POST", AUTH + "auth/signup", {
            "email": " QA_A@EXAMPLE.INVALID ", "password": secrets.token_urlsafe(24) + "!7aZ",
            "birth_date": "1995-01-01", "is_muslim": True,
            "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.expect_status(duplicate, 401)
        self.assertFalse(duplicate[1].get("meta", {}).get("is_authenticated"))
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(User.objects.get(pk=me["id"]).check_password(self.password))
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.accounts")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_report_idempotency_is_actor_scoped_and_survives_block(self):
        a, ma, b, mb = self.matching_pair()
        payload = {"target_id": mb["domain_id"], "category": "harassment"}
        headers = {"HTTP_IDEMPOTENCY_KEY": "qa_report_0001"}
        one = self.call("POST", "/v1/reports", payload, a, **headers)
        two = self.call("POST", "/v1/reports", payload, a, **headers)
        self.expect_status(one, 201)
        self.expect_status(two, 201)
        self.assertTrue(one[1]["id"] == two[1]["id"])
        self.assertEqual(MutationReceipt.objects.count(), 1)
        self.expect_status(self.call("POST", "/v1/reports",
            {**payload, "category": "impersonation"}, a, **headers), 409)
        self.expect_status(self.call("POST", "/v1/blocks", {"target_id": ma["domain_id"]}, b), 200)
        self.expect_status(self.call("POST", "/v1/reports", payload, a, **headers), 201)
        different = self.call("POST", "/v1/reports",
            {"target_id": ma["domain_id"], "category": "harassment"}, b, **headers)
        self.expect_status(different, 201)
        self.assertTrue(one[1]["id"] != different[1]["id"])
        self.assertEqual(MutationReceipt.objects.count(), 2)

    def test_third_actor_cannot_read_mutate_or_attribute_report_to_foreign_relationship(self):
        a, ma, b, mb = self.matching_pair()
        requested = self.call("POST", "/v1/relationships", {"candidate_id": mb["domain_id"]},
                              a, HTTP_IDEMPOTENCY_KEY="qa_relationship_0001")
        self.expect_status(requested, 201)
        identifier = requested[1]["id"]
        c, _ = self.account("qa_c@example.invalid")
        self.expect_status(self.call("PUT", "/v1/me/profile", {
            "gender": "female", "country": "SA", "marital_status": "single",
            "declared_wives": 0, "marriage_goal": "build_family", "discoverable": True}, c), 200)
        self.expect_status(self.call("PUT", "/v1/me/preferences", {
            "min_age": 18, "max_age": 60, "countries": [], "marital_statuses": ["single"]}, c), 200)
        self.expect_status(self.call("GET", "/v1/candidates/" + ma["domain_id"], token=c), 200)
        for method, suffix, data in [
            ("GET", "", {}), ("GET", "/cards", {}),
            ("POST", "/respond", {"decision": "accept"}),
            ("POST", "/cancel", {}),
            ("POST", "/end", {"confirm": True}),
            ("POST", "/exclusive/request", {"confirm": True}),
            ("POST", "/exclusive/respond", {"decision": "accept"}),
        ]:
            with self.subTest(method=method, suffix=suffix):
                self.expect_status(self.call(method, "/v1/relationships/" + identifier + suffix, data, c), 404)
        self.expect_status(self.call("POST", "/v1/reports", {
            "target_id": ma["domain_id"], "category": "harassment", "relationship_id": identifier},
            c, HTTP_IDEMPOTENCY_KEY="qa_foreign_report_0001"), 404)
        self.assertEqual(MutationReceipt.objects.count(), 0)

    def test_policy_rollover_and_missing_consent_block_matching_but_not_safety(self):
        a, ma, b, mb = self.matching_pair()
        self.expect_status(self.call("POST", "/v1/relationships", {"candidate_id": mb["domain_id"]},
            a, HTTP_IDEMPOTENCY_KEY="qa_consent_relationship"), 201)
        # Stored consent version is DB-constrained. Simulate a future code policy
        # instead of bypassing that constraint to manufacture an impossible row.
        with mock.patch("wainak_identity.repository.POLICY_VERSION", "future-policy-fixture"):
            self.expect_status(self.call("GET", "/v1/candidates", token=a), 403)
            self.expect_status(self.call("PUT", "/v1/me/preferences", {
                "min_age": 18, "max_age": 60, "countries": [], "marital_statuses": ["single"]}, a), 403)
            self.expect_status(self.call("POST", "/v1/blocks", {"target_id": mb["domain_id"]}, a), 200)
            self.expect_status(self.call("POST", "/v1/reports", {
                "target_id": mb["domain_id"], "category": "harassment"}, a,
                HTTP_IDEMPOTENCY_KEY="qa_stale_consent_safety"), 201)
        with transaction.atomic():
            with service().repository.transaction() as state:
                state.accounts[ma["domain_id"]].pop("consents", None)
        self.expect_status(self.call("GET", "/v1/candidates", token=a), 403)
        self.expect_status(self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, a), 200)

    def test_failure_after_domain_delete_rolls_back_identity_domain_and_session(self):
        token, me = self.account("qa_a@example.invalid")
        with mock.patch.object(DeletionReceipt.objects, "create",
                               side_effect=RuntimeError("Synthetic failure after domain deletion")):
            self.expect_status(self.call("DELETE", "/identity/v1/me",
                {"confirmation": "DELETE"}, token), 500)
        self.assertTrue(User.objects.filter(pk=me["id"]).exists())
        self.assertEqual(DeletionReceipt.objects.count(), 0)
        self.expect_status(self.call("GET", "/v1/me", token=token), 200)
        self.expect_status(self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token), 200)

    def test_delete_invalidates_reset_and_session_after_database_restart(self):
        token, me = self.account("qa_a@example.invalid")
        key = self.reset_link(me["email"])
        self.expect_status(self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token), 200)
        connections.close_all()
        self.assertTrue(callable(RESTART_DATABASE), "Owned restart callback is required")
        RESTART_DATABASE()
        connections.close_all()
        self.expect_status(self.call("GET", "/identity/v1/me", token=token), 401)
        self.expect_status(self.call("POST", AUTH + "auth/password/reset",
            {"key": key, "password": self.password}), 400)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(EmailAddress.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)
        self.assertEqual(DeletionReceipt.objects.count(), 1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT data FROM wainak_phase1_dev.accounts WHERE id=%s", [me["domain_id"]])
            tombstone = cursor.fetchone()[0]
        if isinstance(tombstone, str):
            tombstone = json.loads(tombstone)
        self.assertEqual(set(tombstone), {"id", "deleted", "exclusive_relationship_id"})

    def test_minor_stale_terms_and_real_email_create_no_identity_or_domain_account(self):
        base = {"email": "qa_a@example.invalid", "password": self.password,
                "birth_date": "1995-01-01", "is_muslim": True,
                "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION}
        minor = str(timezone.now().year - 17) + "-01-01"
        for changes in ({"birth_date": minor}, {"terms_version": "obsolete-fixture"},
                        {"is_muslim": False}, {"email": "qa@example.com"}):
            response = self.call("POST", AUTH + "auth/signup", {**base, **changes})
            self.assertTrue(response[0] in (400, 403), "Invalid eligibility/input must fail closed")
        self.assertEqual(User.objects.count(), 0)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.accounts")
            self.assertEqual(cursor.fetchone()[0], 0)


    def test_concurrent_case_variant_signups_create_one_identity_without_password_overwrite(self):
        passwords = [secrets.token_urlsafe(24) + "!7aZ" for _ in range(2)]
        barrier = threading.Barrier(2)
        def register(index):
            try:
                barrier.wait(timeout=5)
                return self.call("POST", AUTH + "auth/signup", {
                    "email": ("qa_race@example.invalid", " QA_RACE@EXAMPLE.INVALID ")[index],
                    "password": passwords[index], "birth_date": "1995-01-01",
                    "is_muslim": True, "terms_version": POLICY_VERSION,
                    "privacy_version": POLICY_VERSION})[0]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(register, range(2)))
        self.assertEqual(statuses, [401, 401])
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(sum(User.objects.get().check_password(p) for p in passwords), 1)
        self.assertEqual(EmailAddress.objects.filter(verified=True).count(), 0)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.accounts")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_delete_racing_reset_never_resurrects_a_deleted_identity(self):
        token, me = self.account("qa_race@example.invalid")
        reset = self.reset_link(me["email"])
        replacement = secrets.token_urlsafe(24) + "!7aZ"
        barrier = threading.Barrier(2)
        def operation(index):
            try:
                barrier.wait(timeout=5)
                if index == 0:
                    return self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)[0]
                return self.call("POST", AUTH + "auth/password/reset",
                                 {"key": reset, "password": replacement})[0]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            deleted, changed = list(pool.map(operation, range(2)))
        self.assertTrue((deleted, changed) in {(200, 400), (401, 401)},
                        "Only one serializable delete/reset ordering is allowed")
        self.expect_status(self.call("GET", "/identity/v1/me", token=token), 401)
        if deleted == 200:
            self.assertEqual(User.objects.count(), 0)
            self.assertEqual(EmailAddress.objects.count(), 0)
            self.assertEqual(DigestSession.objects.count(), 0)
        else:
            self.assertEqual(User.objects.count(), 1)
            self.assertTrue(User.objects.get().check_password(replacement))
            self.assertEqual(DeletionReceipt.objects.count(), 0)

    def test_reregister_after_delete_gets_new_domain_without_old_relationship_rights(self):
        a, ma, b, mb = self.matching_pair()
        request = self.call("POST", "/v1/relationships", {"candidate_id": mb["domain_id"]},
                            a, HTTP_IDEMPOTENCY_KEY="qa_erasure_relationship")
        self.expect_status(request, 201)
        old_relationship = request[1]["id"]
        self.expect_status(self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, a), 200)
        new_token, new_me = self.account(ma["email"])
        self.assertTrue(new_me["id"] != ma["id"] and new_me["domain_id"] != ma["domain_id"])
        self.expect_status(self.call("GET", "/identity/v1/me", token=a), 401)
        listed = self.call("GET", "/v1/relationships", token=new_token)
        self.expect_status(listed, 200)
        self.assertEqual(listed[1]["items"], [])
        self.expect_status(self.call("GET", "/v1/relationships/" + old_relationship, token=new_token), 404)


    def test_default_framework_session_table_stays_empty_and_pending_secrets_are_encrypted(self):
        from django.contrib.sessions.models import Session
        from allauth.account.models import EmailConfirmation
        pending, code = self.signup("qa_storage@example.invalid")
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(EmailConfirmation.objects.count(), 0)
        self.assertFalse(any("usersessions" in app for app in settings.INSTALLED_APPS))
        stored = json.dumps(list(DigestSession.objects.values("session_key", "session_data")))
        self.assertTrue(pending not in stored and code not in stored and self.password not in stored,
                        "Bearer/challenge/password must not be stored in plaintext")
        self.assertTrue(User.objects.get().password.startswith("argon2$"))
        self.assertTrue(User.objects.get().check_password(self.password))
        verified = self.call("POST", AUTH + "auth/email/verify", {"key": code}, pending)
        self.expect_status(verified, 200)
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(EmailConfirmation.objects.count(), 0)

    def test_concurrent_report_replay_creates_one_receipt_and_purged_replay_stays_gone(self):
        a, ma, b, mb = self.matching_pair()
        payload = {"target_id": mb["domain_id"], "category": "harassment"}
        barrier = threading.Barrier(2)
        def send(index):
            try:
                barrier.wait(timeout=5)
                response = self.call("POST", "/v1/reports", payload, a,
                                     HTTP_IDEMPOTENCY_KEY="qa_parallel_report")
                return response[0], response[1].get("id")
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, range(2)))
        self.assertTrue(all(status == 201 for status, _ in results))
        self.assertTrue(results[0][1] is not None and results[0][1] == results[1][1])
        self.assertEqual(MutationReceipt.objects.count(), 1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.reports")
            self.assertEqual(cursor.fetchone()[0], 1)
        self.expect_status(self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, b), 200)
        self.expect_status(self.call("POST", "/v1/reports", payload, a,
                                    HTTP_IDEMPOTENCY_KEY="qa_parallel_report"), 410)
        self.assertEqual(MutationReceipt.objects.count(), 1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.reports")
            self.assertEqual(cursor.fetchone()[0], 0)
