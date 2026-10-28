"""Synthetic-only auth assertions: never print credentials, codes or email bodies."""
import json
import re
import secrets
import unittest
from datetime import timedelta
from unittest import mock
from django.conf import settings
from django.db import connection, connections, transaction
from django.test import Client, override_settings
from django.utils import timezone
from allauth.account.models import EmailAddress
from wainak.domain import POLICY_VERSION
from wainak_identity.mailbox import OUTBOX
from wainak_identity.models import User, DigestSession, RateBucket, MutationReceipt, DeletionReceipt
from wainak_identity.repository import service
from wainak_identity.sessions import SessionStore, digest_token

CONNECT = RESTART_DATABASE = FIXTURE_KEYS = None
AUTH = "/_allauth/app/v1/"


class IdentityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from django.core.management import call_command
        connections.close_all()
        call_command("migrate", interactive=False, verbosity=0)
        call_command("check", verbosity=0)

    def setUp(self):
        connections.close_all()
        User.objects.all().delete()
        DigestSession.objects.all().delete()
        RateBucket.objects.all().delete()
        DeletionReceipt.objects.all().delete()
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE wainak_phase1_dev.accounts CASCADE")
        OUTBOX.clear()
        self.client = Client(raise_request_exception=False)
        self.password = secrets.token_urlsafe(24) + "!7aZ"

    def call(self, method, path, data=None, token=None, client=None, **headers):
        options = {"HTTP_HOST": "localhost", "REMOTE_ADDR": "127.0.0.1"}
        if token:
            options["HTTP_X_SESSION_TOKEN"] = token
        options.update(headers)
        response = (client or self.client).generic(method, path, data=json.dumps(data or {}).encode(),
                            content_type="application/json", **options)
        try:
            body = json.loads(response.content)
        except ValueError:
            self.fail("Expected bounded JSON response, not content or traceback")
        return response.status_code, body

    def status(self, actual, expected, body=None):
        # Only safe error CODES are included, never entire response/token content.
        codes = [x.get("code") for x in (body or {}).get("errors", [])]
        if isinstance((body or {}).get("error"), dict):
            codes.append(body["error"].get("code"))
        self.assertEqual(actual, expected, "Unexpected HTTP status; safe error codes=" + repr(codes))

    def signup(self, email="alpha@example.invalid", *, password=None, extra=None):
        data = {"email": email, "password": password or self.password, "birth_date": "1995-01-01",
                "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION}
        data.update(extra or {})
        code, body = self.call("POST", AUTH+"auth/signup", data)
        self.status(code, 401, body)
        token = body.get("meta", {}).get("session_token")
        self.assertTrue(isinstance(token, str), "Signup must create a pending authentication session")
        messages = [m for m in OUTBOX if m["recipient"] == email.lower() and m.get("code")]
        self.assertTrue(bool(messages), "Verification message must exist only in the fake mailbox")
        return token, messages[-1]["code"]

    def account(self, email="alpha@example.invalid", *, password=None):
        pending, verification = self.signup(email, password=password)
        code, body = self.call("POST", AUTH+"auth/email/verify", {"key": verification}, pending)
        self.status(code, 200, body)
        token = body.get("meta", {}).get("session_token", pending)
        code, me = self.call("GET", "/identity/v1/me", token=token)
        self.status(code, 200, me)
        return token, me

    def reset_link(self, email):
        code, body = self.call("POST", AUTH+"auth/password/request", {"email": email})
        self.status(code, 200, body)
        links = [m["reset_url"] for m in OUTBOX if m["recipient"] == email.lower() and m.get("reset_url")]
        self.assertTrue(bool(links), "Reset link must exist in the in-memory fake mailbox")
        return links[-1].split("/reset/", 1)[1]

    def test_signup_verify_domain_bridge_logout_and_old_token_rejected(self):
        pending, verification = self.signup()
        code, body = self.call("GET", "/v1/me", token=pending)
        self.assertIn(code, (401, 403))
        code, body = self.call("POST", AUTH+"auth/email/verify", {"key": verification}, pending)
        self.status(code, 200, body)
        token = body.get("meta", {}).get("session_token", pending)
        self.assertTrue(token != pending, "Completing login must rotate the pending session")
        code, body = self.call("GET", "/v1/me", token=token)
        self.status(code, 200, body)
        self.assertTrue(body["dev_email_verified"])
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.sessions")
            self.assertEqual(cursor.fetchone()[0], 0)
        code, body = self.call("DELETE", AUTH+"auth/session", token=token)
        self.status(code, 401, body)
        code, _ = self.call("GET", "/v1/me", token=token)
        self.status(code, 401)

    def test_hash_encrypted_payload_no_raw_session_or_verification_code(self):
        pending, verification = self.signup()
        rows = list(DigestSession.objects.values("session_key", "session_data"))
        serialized = json.dumps(rows)
        self.assertTrue(pending not in serialized, "Raw session secret must not be persisted")
        self.assertTrue(verification not in serialized, "Verification secret must not be plaintext in DB")
        self.assertTrue(all(len(r["session_key"]) == 64 for r in rows))
        code, _ = self.call("GET", "/identity/v1/me", token=digest_token(pending))
        self.status(code, 401)

    def test_password_reset_revokes_sessions_and_old_link_replay(self):
        token, me = self.account()
        key = self.reset_link(me["email"])
        replacement = secrets.token_urlsafe(24) + "!7aZ"
        code, body = self.call("POST", AUTH+"auth/password/reset", {"key": key, "password": replacement})
        self.status(code, 401, body)  # Success without automatically logging in.
        self.assertTrue(EmailAddress.objects.get(user_id=me["id"]).verified)
        code, _ = self.call("GET", "/identity/v1/me", token=token)
        self.status(code, 401)
        code, _ = self.call("POST", AUTH+"auth/password/reset", {"key": key, "password": self.password})
        self.status(code, 400)
        code, body = self.call("POST", AUTH+"auth/login", {"email": me["email"], "password": replacement})
        self.status(code, 200, body)

    def test_deleted_user_and_private_domain_data_are_physically_erased(self):
        token, me = self.account()
        code, body = self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)
        self.status(code, 200, body)
        self.assertTrue(body["identity_erased"])
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(EmailAddress.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)
        self.assertEqual(DeletionReceipt.objects.count(), 1)
        with connection.cursor() as cursor:
            cursor.execute("SELECT data FROM wainak_phase1_dev.accounts WHERE id=%s", [me["domain_id"]])
            tombstone = cursor.fetchone()[0]
            if isinstance(tombstone, str): tombstone = json.loads(tombstone)
        self.assertEqual(set(tombstone), {"id", "deleted", "exclusive_relationship_id"})
        code, _ = self.call("GET", "/v1/me", token=token)
        self.status(code, 401)

    def test_auth_domain_registration_failure_rolls_back_one_transaction(self):
        from wainak_identity.models import User as UserModel
        original = UserModel.save
        def failing_save(obj, *args, **kwargs):
            if kwargs.get("update_fields") == ["domain_id"]:
                raise RuntimeError("Synthetic injected failure after domain creation")
            return original(obj, *args, **kwargs)
        with mock.patch.object(UserModel, "save", failing_save):
            code, _ = self.call("POST", AUTH+"auth/signup", {"email": "alpha@example.invalid", "password": self.password,
                "birth_date": "1995-01-01", "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.status(code, 500)
        self.assertEqual(User.objects.count(), 0)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.accounts")
            self.assertEqual(cursor.fetchone()[0], 0)
        self.assertEqual(len(OUTBOX), 0)

    def login(self, email, password=None, token=None):
        code, body = self.call("POST", AUTH+"auth/login", {"email": email, "password": password or self.password}, token)
        self.status(code, 200, body)
        result = body.get("meta", {}).get("session_token", token)
        self.assertTrue(isinstance(result, str), "Authenticated session token is required")
        return result

    def ready_account(self, email, gender):
        token, me = self.account(email)
        profile = {"gender": gender, "country": "SA", "marital_status": "single", "declared_wives": 0,
                   "marriage_goal": "build_family", "discoverable": True}
        code, body = self.call("PUT", "/v1/me/profile", profile, token)
        self.status(code, 200, body)
        code, body = self.call("PUT", "/v1/me/preferences", {"min_age": 18, "max_age": 80,
                               "countries": [], "marital_statuses": ["single", "married"]}, token)
        self.status(code, 200, body)
        return token, me

    def test_reset_with_current_pending_token_purges_it_without_verifying_email(self):
        pending, verification = self.signup()
        key = self.reset_link("alpha@example.invalid")
        replacement = secrets.token_urlsafe(24)+"!7aZ"
        code, body = self.call("POST", AUTH+"auth/password/reset", {"key": key, "password": replacement}, pending)
        self.status(code, 401, body)
        self.assertFalse(EmailAddress.objects.get().verified)
        self.assertFalse(DigestSession.objects.filter(session_key=digest_token(pending)).exists())
        code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": verification}, pending)
        self.assertIn(code, (400, 401, 409, 410))
        self.assertFalse(EmailAddress.objects.get().verified)

    def test_two_outstanding_reset_links_are_invalidated_by_one_reset(self):
        from datetime import datetime
        token, me = self.account()
        first = self.reset_link(me["email"])
        with mock.patch("django.contrib.auth.tokens.PasswordResetTokenGenerator._now", return_value=datetime.now()+timedelta(seconds=2)):
            second = self.reset_link(me["email"])
        self.assertTrue(first != second, "Fixture requires two independent outstanding links")
        code, body = self.call("POST", AUTH+"auth/password/reset", {"key": first, "password": secrets.token_urlsafe(24)+"!7aZ"})
        self.status(code, 401, body)
        for key in (first, second):
            code, _ = self.call("POST", AUTH+"auth/password/reset", {"key": key, "password": self.password})
            self.status(code, 400)
        code, _ = self.call("GET", "/identity/v1/me", token=token)
        self.status(code, 401)

    def test_reset_preserves_an_unrelated_authenticated_actor(self):
        a, ma = self.account()
        b, mb = self.account("beta@example.invalid")
        key = self.reset_link(ma["email"])
        code, _ = self.call("POST", AUTH+"auth/password/reset", {"key": key, "password": secrets.token_urlsafe(24)+"!7aZ"}, b)
        # allauth may reject a reset in an authenticated context; either rejection
        # or successful reset must NEVER revoke the unrelated actor's session.
        self.assertIn(code, (200, 400, 401, 409))
        code, body = self.call("GET", "/identity/v1/me", token=b)
        self.status(code, 200, body)
        self.assertEqual(body["id"], mb["id"])

    def test_delete_failure_after_domain_erasure_rolls_back_both_halves(self):
        token, me = self.account()
        with mock.patch.object(User, "delete", side_effect=RuntimeError("Synthetic deletion failure")):
            code, body = self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)
        self.status(code, 500, body)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(DeletionReceipt.objects.count(), 0)
        code, body = self.call("GET", "/v1/me", token=token)
        self.status(code, 200, body)
        self.assertEqual(body["id"], me["domain_id"])
        self.assertTrue(bool(body.get("email")))

    def test_digest_manager_and_generic_serializers_refuse_raw_shortcuts(self):
        store = SessionStore()
        with self.assertRaises(RuntimeError):
            DigestSession.objects.save("not-a-real-session-token", {"marker": True}, timezone.now())
        with self.assertRaises(RuntimeError):
            DigestSession.objects.encode({"marker": True})
        with self.assertRaises(RuntimeError):
            store.encode({"marker": True})
        with self.assertRaises(RuntimeError):
            store.decode("not-a-ciphertext")
        store["marker"] = True
        store.save()
        first = store.session_key
        self.assertTrue(store.exists(first))
        self.assertTrue(SessionStore(first).get("marker"))
        self.assertFalse(store.exists(digest_token(first)))
        store.cycle_key()
        second = store.session_key
        self.assertTrue(first != second)
        self.assertFalse(store.exists(first))
        self.assertTrue(store.exists(second))
        store.delete("")
        self.assertTrue(store.exists(second), "Explicit empty key must not delete the current session")
        store.flush()
        self.assertFalse(store.exists(second))

    def test_session_ciphertext_tamper_wrong_key_and_cross_row_swap_fail_closed(self):
        from cryptography.fernet import Fernet
        a, _ = self.account()
        b, _ = self.account("beta@example.invalid")
        ra = DigestSession.objects.get(session_key=digest_token(a))
        rb = DigestSession.objects.get(session_key=digest_token(b))
        original_a, original_b = ra.session_data, rb.session_data
        DigestSession.objects.filter(pk=ra.pk).update(session_data=original_b)
        code, _ = self.call("GET", "/identity/v1/me", token=a)
        self.status(code, 401)
        DigestSession.objects.filter(pk=ra.pk).update(session_data=original_a[:-8]+"tampered")
        code, _ = self.call("GET", "/identity/v1/me", token=a)
        self.status(code, 401)
        DigestSession.objects.filter(pk=ra.pk).update(session_data=original_a)
        with override_settings(WAINAK_SESSION_ENCRYPTION_KEY=Fernet.generate_key()):
            code, _ = self.call("GET", "/identity/v1/me", token=a)
            self.status(code, 401)
        code, _ = self.call("GET", "/identity/v1/me", token=a)
        self.status(code, 200)

    def test_read_activity_touches_idle_but_not_absolute_expiry(self):
        token, _ = self.account()
        now = timezone.now()
        row = DigestSession.objects.get(session_key=digest_token(token))
        original_created = row.created_at
        DigestSession.objects.filter(pk=row.pk).update(last_seen_at=now-timedelta(seconds=1799))
        code, _ = self.call("GET", "/identity/v1/me", token=token)
        self.status(code, 200)
        row.refresh_from_db()
        self.assertTrue(row.last_seen_at >= now)
        self.assertEqual(row.created_at, original_created)
        # Exactly the absolute boundary is expired, even with recent activity.
        DigestSession.objects.filter(pk=row.pk).update(created_at=now-timedelta(seconds=86400),
                                                       last_seen_at=now, expire_date=now+timedelta(seconds=1800))
        with mock.patch("wainak_identity.sessions.timezone.now", return_value=now):
            code, _ = self.call("GET", "/identity/v1/me", token=token)
        self.status(code, 401)

    def test_stale_reauthentication_rejected_then_password_reauth_allows_delete(self):
        token, _ = self.account()
        session = SessionStore(token)
        session["recent_auth_at"] = timezone.now().timestamp()-300
        session.save()
        code, body = self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)
        self.status(code, 403, body)
        code, body = self.call("POST", "/identity/v1/reauthenticate", {"password": self.password}, token)
        self.status(code, 200, body)
        code, body = self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)
        self.status(code, 200, body)

    def test_atomic_rate_buckets_across_independent_connections_and_expiry(self):
        from concurrent.futures import ThreadPoolExecutor
        from wainak_identity.rate_limits import consume
        def attempt(_):
            try:
                return consume("race", "fixture", "same-subject", 5, 60)
            finally:
                connections.close_all()
        connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(16)))
        self.assertEqual(sum(results), 5)
        self.assertEqual(RateBucket.objects.get().count, 5)
        deadline = RateBucket.objects.get().expires_at
        self.assertTrue(consume("race", "fixture", "same-subject", 5, 60, now=deadline))
        self.assertEqual(RateBucket.objects.get().count, 1)

    def test_report_key_payload_actor_scope_and_post_block_replay(self):
        a, ma = self.ready_account("alpha@example.invalid", "male")
        b, mb = self.ready_account("beta@example.invalid", "female")
        data = {"target_id": mb["domain_id"], "category": "harassment"}
        code, first = self.call("POST", "/v1/reports", data, a, HTTP_IDEMPOTENCY_KEY="report-key-001")
        self.status(code, 201, first)
        code, repeated = self.call("POST", "/v1/reports", data, a, HTTP_IDEMPOTENCY_KEY="report-key-001")
        self.status(code, 201, repeated)
        self.assertEqual(first["id"], repeated["id"])
        code, _ = self.call("POST", "/v1/reports", {**data, "category": "spam"}, a, HTTP_IDEMPOTENCY_KEY="report-key-001")
        self.status(code, 409)
        code, peer = self.call("POST", "/v1/reports", {"target_id": ma["domain_id"], "category": "harassment"}, b,
                               HTTP_IDEMPOTENCY_KEY="report-key-001")
        self.status(code, 201, peer)
        self.assertTrue(peer["id"] != first["id"])
        code, _ = self.call("POST", "/v1/blocks", {"target_id": ma["domain_id"]}, b)
        self.status(code, 200)
        code, repeated = self.call("POST", "/v1/reports", data, a, HTTP_IDEMPOTENCY_KEY="report-key-001")
        self.status(code, 201, repeated)
        self.assertEqual(first["id"], repeated["id"])
        self.assertEqual(MutationReceipt.objects.count(), 2)

    def test_current_policy_is_checked_after_persisted_consent_becomes_stale(self):
        a, ma = self.ready_account("alpha@example.invalid", "male")
        b, mb = self.ready_account("beta@example.invalid", "female")
        # Existing schema itself rejects arbitrary policy strings. A future
        # policy bump still must fail closed for accounts carrying the old one.
        with mock.patch("wainak_identity.repository.POLICY_VERSION", "future-fixture-policy"):
            code, body = self.call("GET", "/v1/candidates", token=a)
            self.status(code, 403, body)
        with transaction.atomic(), service().repository.transaction() as state:
            state.accounts[ma["domain_id"]].pop("consents")
        code, body = self.call("GET", "/v1/candidates", token=a)
        self.status(code, 403, body)
        self.assertEqual(body["error"]["code"], "consent_required")
        code, body = self.call("GET", "/v1/candidates", token=b)
        self.status(code, 200, body)
        self.assertEqual(body["items"], [])
        # Safety and erasure remain available despite stale terms.
        code, body = self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, a)
        self.status(code, 200, body)

    def test_session_and_delete_survive_database_and_fresh_http_process_restarts(self):
        import multiprocessing
        import urllib.request
        import urllib.error
        token, me = self.account()
        context = multiprocessing.get_context("fork")
        connections.close_all()

        def http(stage, method="GET", data=None):
            # No DSN/key/token in argv/env/output; only the port crosses this pipe.
            ready = context.Queue()
            stop = context.Event()
            process = context.Process(target=_serve_owned_http, args=(ready, stop))
            process.start()
            try:
                port = ready.get(timeout=10)
                self.assertTrue(isinstance(port, int) and 0 < port < 65536)
                request = urllib.request.Request(f"http://127.0.0.1:{port}/identity/v1/me", method=method,
                    data=json.dumps(data).encode() if data is not None else None,
                    headers={"X-Session-Token": token, "Content-Type": "application/json"})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    with opener.open(request, timeout=10) as response:
                        status, body = response.status, json.loads(response.read(16385))
                except urllib.error.HTTPError as response:
                    status, body = response.code, json.loads(response.read(16385))
                return status, body, process.pid
            finally:
                stop.set()
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()  # Only this exact owned test process.
                    process.join(timeout=5)
                if process.is_alive():
                    process.kill()  # Exact owned process only; guarantee cleanup on failure.
                    process.join(timeout=5)
                ready.close()
                ready.join_thread()
                self.assertFalse(process.is_alive(), "Owned temporary HTTP process must be stopped")

        code, body, first_pid = http("first")
        self.status(code, 200, body)
        self.assertEqual(body["id"], me["id"])
        connections.close_all()
        RESTART_DATABASE()
        code, body, second_pid = http("second", "DELETE", {"confirmation": "DELETE"})
        self.status(code, 200, body)
        self.assertTrue(body["identity_erased"])
        self.assertTrue(first_pid != second_pid)
        connections.close_all()
        RESTART_DATABASE()
        code, body, third_pid = http("third")
        self.status(code, 401, body)
        self.assertTrue(third_pid not in {first_pid, second_pid})
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)
        self.assertEqual(DeletionReceipt.objects.count(), 1)


    def test_verification_expiry_purpose_account_binding_and_replay(self):
        pending, verification = self.signup()
        other, other_code = self.signup("beta@example.invalid")
        code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": verification}, other)
        self.status(code, 400)
        self.assertFalse(EmailAddress.objects.get(email="beta@example.invalid").verified)
        code, _ = self.call("POST", AUTH+"auth/password/reset", {"key": verification, "password": self.password})
        self.status(code, 400)
        state = SessionStore(pending).get("account_email_verification_code")
        with mock.patch("allauth.account.internal.flows.code_verification.time.time", return_value=state["at"]+600.001):
            code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": verification}, pending)
        self.assertIn(code, (400, 401, 409, 410))
        self.assertFalse(EmailAddress.objects.get(email="alpha@example.invalid").verified)
        code, body = self.call("POST", AUTH+"auth/email/verify", {"key": other_code}, other)
        self.status(code, 200, body)
        code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": other_code}, other)
        self.assertIn(code, (400, 401, 409, 410))

    def test_verification_attempt_limit_and_resend_replace_previous_code(self):
        pending, verification = self.signup()
        bad = ("0" if verification[0] != "0" else "1")+verification[1:]
        for _ in range(5):
            code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": bad}, pending)
            self.assertIn(code, (400, 401, 409, 410))
        code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": verification}, pending)
        self.assertIn(code, (400, 401, 409, 410))
        self.assertFalse(EmailAddress.objects.get().verified)
        other, old = self.signup("beta@example.invalid")
        for _ in range(3):
            code, body = self.call("POST", AUTH+"auth/email/verify/resend", token=other)
            self.status(code, 200, body)
        code, _ = self.call("POST", AUTH+"auth/email/verify/resend", token=other)
        self.status(code, 409)
        messages = [m for m in OUTBOX if m["recipient"] == "beta@example.invalid" and m.get("code")]
        current = messages[-1]["code"]
        self.assertTrue(current != old, "Resend fixture must rotate the code")
        code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": old}, other)
        self.status(code, 400)
        code, body = self.call("POST", AUTH+"auth/email/verify", {"key": current}, other)
        self.status(code, 200, body)

    def test_reset_link_expires_after_framework_timeout(self):
        from datetime import datetime
        _, me = self.account()
        key = self.reset_link(me["email"])
        with mock.patch("django.contrib.auth.tokens.PasswordResetTokenGenerator._now", return_value=datetime.now()+timedelta(seconds=601)):
            code, body = self.call("POST", AUTH+"auth/password/reset", {"key": key, "password": secrets.token_urlsafe(24)+"!7aZ"})
        self.status(code, 400, body)
        self.assertTrue(User.objects.get().check_password(self.password))

    def test_duplicate_verified_signup_does_not_replace_password_or_domain(self):
        legitimate, me = self.account()
        attacker_password = secrets.token_urlsafe(24)+"!7aZ"
        code, body = self.call("POST", AUTH+"auth/signup", {"email": " ALPHA@EXAMPLE.INVALID ", "password": attacker_password,
            "birth_date": "1995-01-01", "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.status(code, 401, body)
        pending = body.get("meta", {}).get("session_token")
        self.assertTrue(isinstance(pending, str))
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(User.objects.get().check_password(self.password))
        self.assertFalse(User.objects.get().check_password(attacker_password))
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.accounts")
            self.assertEqual(cursor.fetchone()[0], 1)
        code, _ = self.call("GET", "/identity/v1/me", token=pending)
        self.status(code, 401)
        code, body = self.call("GET", "/identity/v1/me", token=legitimate)
        self.status(code, 200, body)
        self.assertEqual(body["id"], me["id"])

    def test_password_change_revokes_all_sessions_and_pending_challenges(self):
        token, me = self.account()
        second = self.login(me["email"])
        replacement = secrets.token_urlsafe(24)+"!7aZ"
        code, body = self.call("POST", AUTH+"account/password/change", {"current_password": self.password, "new_password": replacement}, token)
        self.status(code, 401, body)
        for old in (token, second):
            code, _ = self.call("GET", "/identity/v1/me", token=old)
            self.status(code, 401)
        self.assertEqual(DigestSession.objects.count(), 0)
        self.login(me["email"], password=replacement)

    def test_logout_all_invalidates_an_older_pending_login_challenge(self):
        first, first_code = self.signup()
        code, body = self.call("POST", AUTH+"auth/login", {"email": "alpha@example.invalid", "password": self.password})
        self.status(code, 401, body)
        second = body.get("meta", {}).get("session_token")
        messages = [m for m in OUTBOX if m["recipient"] == "alpha@example.invalid" and m.get("code")]
        second_code = messages[-1]["code"]
        code, body = self.call("POST", AUTH+"auth/email/verify", {"key": second_code}, second)
        self.status(code, 200, body)
        token = body.get("meta", {}).get("session_token", second)
        code, body = self.call("POST", "/identity/v1/logout-all", token=token)
        self.status(code, 200, body)
        self.assertEqual(DigestSession.objects.count(), 0)
        code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": first_code}, first)
        self.assertIn(code, (400, 401, 409, 410))
        self.assertEqual(DigestSession.objects.filter(user__isnull=False).count(), 0)

    def test_http_email_rate_limit_ignores_forwarded_address_and_expires_atomically(self):
        data = {"email": "missing@example.invalid", "password": self.password}
        for index in range(5):
            code, _ = self.call("POST", AUTH+"auth/login", data, HTTP_X_FORWARDED_FOR=f"192.0.2.{index}")
            self.status(code, 400)
        code, body = self.call("POST", AUTH+"auth/login", data, HTTP_X_FORWARDED_FOR="198.51.100.44")
        self.status(code, 429, body)
        self.assertEqual(body["error"]["code"], "rate_limited")
        from wainak_identity.rate_limits import subject_digest
        self.assertEqual(RateBucket.objects.get(pk=subject_digest(AUTH+"auth/login", "ip", "127.0.0.1")).count, 6)

    def test_eligibility_current_terms_and_native_transport_boundary(self):
        base = {"email": "alpha@example.invalid", "password": self.password, "birth_date": "2015-01-01",
                "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION}
        code, body = self.call("POST", AUTH+"auth/signup", base)
        self.status(code, 400, body)
        code, body = self.call("POST", AUTH+"auth/signup", {**base, "birth_date": "1995-01-01", "terms_version": "old"})
        self.status(code, 400, body)
        for ambiguous in (1, "true", "false", None):
            code, body = self.call("POST", AUTH+"auth/signup", {**base, "birth_date": "1995-01-01", "is_muslim": ambiguous})
            self.status(code, 400, body)
        self.assertEqual(User.objects.count(), 0)
        for path, headers in [("/identity/v1/health", {"HTTP_ORIGIN": "https://example.invalid"}),
                              ("/identity/v1/health", {"HTTP_COOKIE": "sessionid=not-real"}),
                              ("/identity/v1/health", {"HTTP_HOST": "example.invalid"})]:
            code, _ = self.call("GET", path, **headers)
            self.status(code, 403)
        code, _ = self.call("POST", "/v1/dev/accounts", base)
        self.status(code, 404)
        code, _ = self.call("POST", AUTH+"auth/password/request", {"email": "not-a-fixture@example.com"})
        self.status(code, 400)
        self.assertEqual(len(OUTBOX), 0)


    def test_unverified_email_collision_cannot_overwrite_or_inherit_account(self):
        legitimate, legitimate_code = self.signup()
        alternative = secrets.token_urlsafe(24)+"!7aZ"
        code, body = self.call("POST", AUTH+"auth/signup", {"email": "ALPHA@EXAMPLE.INVALID", "password": alternative,
            "birth_date": "1995-01-01", "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.status(code, 401, body)
        duplicate = body.get("meta", {}).get("session_token")
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(User.objects.get().check_password(self.password))
        self.assertFalse(User.objects.get().check_password(alternative))
        code, _ = self.call("POST", AUTH+"auth/email/verify", {"key": legitimate_code}, duplicate)
        self.assertIn(code, (400, 401, 409, 410))
        code, body = self.call("POST", AUTH+"auth/email/verify", {"key": legitimate_code}, legitimate)
        self.status(code, 200, body)
        code, _ = self.call("GET", "/identity/v1/me", token=duplicate)
        self.status(code, 401)

    def test_known_unknown_public_reset_and_signup_shapes_do_not_enumerate(self):
        import copy
        self.account()
        def public_shape(body):
            result = copy.deepcopy(body)
            result.get("meta", {}).pop("session_token", None)
            return result
        known_status, known = self.call("POST", AUTH+"auth/password/request", {"email": "alpha@example.invalid"})
        unknown_status, unknown = self.call("POST", AUTH+"auth/password/request", {"email": "missing@example.invalid"})
        self.assertEqual(known_status, unknown_status)
        self.assertTrue(public_shape(known) == public_shape(unknown), "Reset response must not enumerate accounts")
        base = {"password": self.password, "birth_date": "1995-01-01", "is_muslim": True,
                "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION}
        known_status, known = self.call("POST", AUTH+"auth/signup", {**base, "email": "alpha@example.invalid"})
        unknown_status, unknown = self.call("POST", AUTH+"auth/signup", {**base, "email": "missing@example.invalid"})
        self.assertEqual(known_status, unknown_status)
        self.assertTrue(public_shape(known) == public_shape(unknown), "Signup response must not enumerate accounts")

    def test_sessions_auth_hash_check_catches_out_of_band_password_change(self):
        token, _ = self.account()
        user = User.objects.get()
        user.set_password(secrets.token_urlsafe(24)+"!7aZ")
        user.save(update_fields=["password"])
        code, _ = self.call("GET", "/identity/v1/me", token=token)
        self.status(code, 401)
        self.assertFalse(DigestSession.objects.filter(session_key=digest_token(token)).exists())


    def test_async_session_paths_share_digest_encryption_and_revocation_semantics(self):
        from asgiref.sync import async_to_sync, sync_to_async
        async def exercise():
            store = SessionStore()
            await store.aset("marker", True)
            await store.asave()
            first = store.session_key
            first_exists = await store.aexists(first)
            loaded = await SessionStore(first).aload()
            await store.acycle_key()
            second = store.session_key
            old_exists = await store.aexists(first)
            second_exists = await store.aexists(second)
            await store.aflush()
            after_flush = await store.aexists(second)
            await sync_to_async(connections.close_all, thread_sensitive=True)()
            return first_exists, loaded.get("marker"), first != second, old_exists, second_exists, after_flush
        self.assertEqual(async_to_sync(exercise)(), (True, True, True, False, True, False))


    def test_fake_delivery_failure_after_commit_does_not_falsely_verify_or_login(self):
        with mock.patch("django.core.mail.message.EmailMultiAlternatives.send", side_effect=RuntimeError("Synthetic fake delivery failure")):
            code, body = self.call("POST", AUTH+"auth/signup", {"email": "alpha@example.invalid", "password": self.password,
                "birth_date": "1995-01-01", "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.status(code, 500, body)
        # This callback runs AFTER the shared commit: registration persists,
        # never an authenticated session or false verification claim.
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(EmailAddress.objects.get().verified)
        self.assertFalse(any("_auth_user_id" in row.get_decoded() for row in DigestSession.objects.all()))
        self.assertEqual(len(OUTBOX), 0)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM wainak_phase1_dev.accounts")
            self.assertEqual(cursor.fetchone()[0], 1)


def _serve_owned_http(ready, stop):
    """One private loopback WSGI fixture; no access/error log or admin route."""
    from django.core.wsgi import get_wsgi_application
    from wsgiref.simple_server import make_server, WSGIRequestHandler
    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *_):
            pass
    connections.close_all()
    try:
        with make_server("127.0.0.1", 0, get_wsgi_application(), handler_class=QuietHandler) as server:
            server.timeout = 0.2
            ready.put(server.server_port)
            while not stop.is_set():
                server.handle_request()
    finally:
        connections.close_all()
