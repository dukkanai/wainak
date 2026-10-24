"""Independent additive pending-delete/web cases. Fixture secrets stay in memory."""
import json
import re
import secrets
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest import mock

from django.db import connection, connections
from django.test import Client, override_settings
from django.utils import timezone
from allauth.account.models import EmailAddress
from wainak_identity.models import User, DigestSession, DeletionReceipt, RateBucket
from wainak_identity.deletion import expire_orphaned_staged_accounts
from wainak_identity.sessions import SessionStore, digest_token
import qa_identity_independent as baseline

AUTH = baseline.AUTH
PENDING = "/identity/v1/pending-account"
RESTART_DATABASE = None


class DeletionLifecycleTests(unittest.TestCase):
    # Reuse fixture plumbing, NOT inherited tests or their previous results.
    setUp = baseline.IndependentIdentityTests.setUp
    tearDown = baseline.IndependentIdentityTests.tearDown
    call = baseline.IndependentIdentityTests.call
    expect_status = baseline.IndependentIdentityTests.expect_status
    signup = baseline.IndependentIdentityTests.signup
    account = baseline.IndependentIdentityTests.account
    reset_link = baseline.IndependentIdentityTests.reset_link
    matching_pair = baseline.IndependentIdentityTests.matching_pair

    def test_pending_owner_can_delete_and_old_challenge_cannot_resurrect(self):
        pending, code = self.signup("qa_pending@example.invalid")
        response = self.call("DELETE", PENDING,
                             {"password": self.password, "confirmation": "DELETE"}, pending)
        self.expect_status(response, 200)
        self.assertTrue(response[1]["identity_erased"])
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(EmailAddress.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)
        self.assertEqual(DeletionReceipt.objects.count(), 1)
        rejected = self.call("POST", AUTH + "auth/email/verify", {"key": code}, pending)
        self.assertTrue(rejected[0] in (400, 401, 409, 410))
        self.assertEqual(User.objects.count(), 0)
        self.expect_status(self.call("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE"}, pending), 401)

    def test_fake_duplicate_pending_cannot_delete_the_existing_unverified_owner(self):
        owner, code = self.signup("qa_pending@example.invalid")
        duplicate = self.call("POST", AUTH + "auth/signup", {
            "email": " QA_PENDING@EXAMPLE.INVALID ", "password": secrets.token_urlsafe(24) + "!7aZ",
            "birth_date": "1995-01-01", "is_muslim": True,
            "terms_version": baseline.POLICY_VERSION, "privacy_version": baseline.POLICY_VERSION})
        self.expect_status(duplicate, 401)
        fake = duplicate[1].get("meta", {}).get("session_token")
        self.assertTrue(isinstance(fake, str))
        # Even the correct owner's password does not make a fake flow its session.
        self.expect_status(self.call("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE"}, fake), 401)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(DeletionReceipt.objects.count(), 0)
        self.expect_status(self.call("POST", AUTH + "auth/email/verify", {"key": code}, owner), 200)

    def test_pending_wrong_password_confirmation_and_expired_flow_fail_closed(self):
        pending, _ = self.signup("qa_pending@example.invalid")
        self.expect_status(self.call("DELETE", PENDING, {"password": self.password}, pending), 400)
        self.expect_status(self.call("DELETE", PENDING,
            {"password": secrets.token_urlsafe(24), "confirmation": "DELETE"}, pending), 403)
        state = SessionStore(pending).get("account_email_verification_code")
        future = state["at"] + 601
        with mock.patch("time.time", return_value=future), mock.patch(
            "django.utils.timezone.now",
            return_value=datetime.fromtimestamp(future, tz=datetime_timezone.utc)):
            self.expect_status(self.call("DELETE", PENDING,
                {"password": self.password, "confirmation": "DELETE"}, pending), 410)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(DeletionReceipt.objects.count(), 0)

    def test_pending_proof_is_not_retargetable_by_body_header_or_other_password(self):
        a, _ = self.signup("qa_a@example.invalid")
        other_password = secrets.token_urlsafe(24) + "!7aZ"
        b, _ = self.signup("qa_b@example.invalid", password=other_password)
        other = User.objects.get(email="qa_b@example.invalid")
        self.expect_status(self.call("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE", "email": other.email}, a), 400)
        self.expect_status(self.call("DELETE", PENDING,
            {"password": other_password, "confirmation": "DELETE"}, a,
            HTTP_X_USER_ID=str(other.pk)), 403)
        self.assertEqual(User.objects.count(), 2)
        self.expect_status(self.call("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE"}, a,
            HTTP_X_USER_ID=str(other.pk)), 200)
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(User.objects.filter(pk=other.pk).exists())
        self.assertTrue(SessionStore(b).get("account_email_verification_code") is not None)

    def test_verified_account_cannot_use_pending_route_or_wrong_purpose_proof(self):
        token, me = self.account("qa_verified@example.invalid")
        self.expect_status(self.call("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE"}, token), 401)
        pending, code = self.signup("qa_pending@example.invalid")
        reset = self.reset_link("qa_pending@example.invalid")
        for wrong in (code, reset, "x" * 32):
            with self.subTest(proof_kind="wrong-purpose-or-unknown"):
                self.expect_status(self.call("DELETE", PENDING,
                    {"password": self.password, "confirmation": "DELETE"}, wrong), 401)
        self.assertEqual(User.objects.count(), 2)
        self.assertTrue(User.objects.filter(pk=me["id"]).exists())
        self.assertEqual(DeletionReceipt.objects.count(), 0)

    def test_pending_verification_delete_race_has_only_one_ownership_transition(self):
        pending, code = self.signup("qa_pending@example.invalid")
        barrier = threading.Barrier(2)
        def action(index):
            try:
                barrier.wait(timeout=5)
                if index == 0:
                    response = self.call("POST", AUTH + "auth/email/verify", {"key": code}, pending)
                    return response[0], response[1].get("meta", {}).get("session_token")
                response = self.call("DELETE", PENDING,
                    {"password": self.password, "confirmation": "DELETE"}, pending)
                return response[0], None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            verified, deleted = list(pool.map(action, range(2)))
        if verified[0] == 200:
            self.assertEqual(deleted[0], 401)
            self.assertEqual(User.objects.count(), 1)
            self.assertTrue(EmailAddress.objects.get().verified)
            self.assertEqual(DeletionReceipt.objects.count(), 0)
            self.expect_status(self.call("GET", "/identity/v1/me", token=verified[1]), 200)
        else:
            self.assertTrue(verified[0] in (400, 401, 409, 410))
            self.assertEqual(deleted[0], 200)
            self.assertEqual(User.objects.count(), 0)
            self.assertEqual(DigestSession.objects.count(), 0)
            self.assertEqual(DeletionReceipt.objects.count(), 1)

    def test_pending_deletion_failure_rolls_back_both_identity_and_domain(self):
        pending, code = self.signup("qa_pending@example.invalid")
        with mock.patch.object(DeletionReceipt.objects, "create",
                               side_effect=RuntimeError("Synthetic deletion rollback probe")):
            self.expect_status(self.call("DELETE", PENDING,
                {"password": self.password, "confirmation": "DELETE"}, pending), 500)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(DeletionReceipt.objects.count(), 0)
        self.expect_status(self.call("POST", AUTH + "auth/email/verify", {"key": code}, pending), 200)

    def test_pending_erasure_and_revocation_survive_owned_database_restart(self):
        pending, code = self.signup("qa_pending@example.invalid")
        self.expect_status(self.call("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE"}, pending), 200)
        connections.close_all()
        self.assertTrue(callable(RESTART_DATABASE))
        RESTART_DATABASE()
        connections.close_all()
        self.expect_status(self.call("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE"}, pending), 401)
        rejected = self.call("POST", AUTH + "auth/email/verify", {"key": code}, pending)
        self.assertTrue(rejected[0] in (400, 401, 409, 410))
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)


    def snapshot(self):
        # Equality is asserted as a boolean, never by printing credentials/ciphertext.
        rows = [list(model.objects.order_by("pk").values()) for model in
                (User, EmailAddress, DigestSession, DeletionReceipt, RateBucket)]
        with connection.cursor() as cursor:
            cursor.execute("SELECT id,data FROM wainak_phase1_dev.accounts ORDER BY id")
            rows.append(cursor.fetchall())
        return rows

    def test_orphan_dry_run_is_read_only_and_boundary_apply_excludes_young_active_verified(self):
        orphan, _ = self.signup("qa_orphan@example.invalid")
        active, _ = self.signup("qa_active@example.invalid")
        self.account("qa_verified@example.invalid")
        young, _ = self.signup("qa_young@example.invalid")
        now = timezone.now()
        User.objects.exclude(email="qa_young@example.invalid").update(date_joined=now-timedelta(hours=24))
        User.objects.filter(email="qa_young@example.invalid").update(date_joined=now-timedelta(hours=24)+timedelta(seconds=1))
        DigestSession.objects.filter(session_key__in=[digest_token(orphan), digest_token(young)]).update(expire_date=now)
        RateBucket.objects.create(key="f"*64, count=1, expires_at=now)
        before = self.snapshot()
        with mock.patch("django.utils.timezone.now", return_value=now):
            dry = expire_orphaned_staged_accounts()
        self.assertTrue(before == self.snapshot(), "Dry run must not write or touch session timestamps")
        self.assertEqual(dry["eligible_orphaned_accounts"], 1)
        self.assertEqual(dry["purged_unverified_accounts"], 0)
        self.assertFalse(dry["production_retention_approved"])
        with mock.patch("django.utils.timezone.now", return_value=now):
            applied = expire_orphaned_staged_accounts(dry_run=False)
        self.assertEqual(applied["purged_unverified_accounts"], 1)
        self.assertEqual(User.objects.count(), 3)
        self.assertFalse(User.objects.filter(email="qa_orphan@example.invalid").exists())
        self.assertTrue(User.objects.filter(email="qa_active@example.invalid").exists())
        self.assertTrue(User.objects.filter(email="qa_verified@example.invalid").exists())
        self.assertTrue(User.objects.filter(email="qa_young@example.invalid").exists())
        self.assertFalse(RateBucket.objects.filter(pk="f"*64).exists())
        self.assertEqual(DeletionReceipt.objects.count(), 1)

    def test_fake_duplicate_signup_does_not_protect_an_orphan_as_owned_activity(self):
        self.signup("qa_orphan@example.invalid")
        now = timezone.now()
        User.objects.update(date_joined=now-timedelta(hours=25))
        DigestSession.objects.update(expire_date=now-timedelta(seconds=1))
        fake = self.call("POST", AUTH+"auth/signup", {
            "email": "qa_orphan@example.invalid", "password": self.password,
            "birth_date": "1995-01-01", "is_muslim": True,
            "terms_version": baseline.POLICY_VERSION, "privacy_version": baseline.POLICY_VERSION})
        self.expect_status(fake, 401)
        self.assertTrue(isinstance(fake[1].get("meta", {}).get("session_token"), str))
        dry = expire_orphaned_staged_accounts()
        self.assertEqual(dry["eligible_orphaned_accounts"], 1,
                         "Anti-enumeration fake flow must not prove ownership of a persisted account")
        applied = expire_orphaned_staged_accounts(dry_run=False)
        self.assertEqual(applied["purged_unverified_accounts"], 1)
        self.assertEqual(User.objects.count(), 0)

    def test_orphan_fault_rolls_back_domain_identity_and_counter_pruning(self):
        self.signup("qa_orphan@example.invalid")
        now = timezone.now()
        User.objects.update(date_joined=now-timedelta(hours=25))
        DigestSession.objects.update(expire_date=now-timedelta(seconds=1))
        RateBucket.objects.create(key="e"*64, count=1, expires_at=now-timedelta(seconds=1))
        before = self.snapshot()
        with mock.patch.object(User, "delete", side_effect=RuntimeError("Synthetic orphan rollback probe")):
            with self.assertRaises(RuntimeError):
                expire_orphaned_staged_accounts(dry_run=False)
        self.assertTrue(before == self.snapshot(), "All inspected rows must roll back together")

    def test_orphan_apply_racing_owned_login_has_serializable_ownership_result(self):
        self.signup("qa_orphan@example.invalid")
        now = timezone.now()
        User.objects.update(date_joined=now-timedelta(hours=25))
        DigestSession.objects.update(expire_date=now-timedelta(seconds=1))
        barrier = threading.Barrier(2)
        def act(index):
            try:
                barrier.wait(timeout=5)
                if index == 0:
                    return expire_orphaned_staged_accounts(dry_run=False)["purged_unverified_accounts"]
                return self.call("POST", AUTH+"auth/login",
                    {"email": "qa_orphan@example.invalid", "password": self.password})[0]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            purged, login_status = list(pool.map(act, range(2)))
        if purged == 1:
            self.assertEqual(User.objects.count(), 0)
            self.assertTrue(login_status in (400, 401))
        else:
            self.assertEqual(purged, 0)
            self.assertEqual(login_status, 401)
            self.assertEqual(User.objects.count(), 1)
            self.assertFalse(EmailAddress.objects.get().verified)

    def test_orphan_maintenance_rejects_non_sandbox_and_non_boolean_apply_flag(self):
        self.signup("qa_pending@example.invalid")
        before = self.snapshot()
        with override_settings(WAINAK_IDENTITY_SANDBOX=False), self.assertRaises(RuntimeError):
            expire_orphaned_staged_accounts(dry_run=False)
        with self.assertRaises(ValueError):
            expire_orphaned_staged_accounts(dry_run="false")
        self.assertTrue(before == self.snapshot())

    def open_web(self):
        self.web_client = Client(enforce_csrf_checks=True, raise_request_exception=False)
        response = self.web_client.get("/account-deletion", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.content.decode())
        self.assertTrue(bool(match), "Expected masked CSRF metadata")
        self.web_csrf = match[1]
        return response

    def web(self, method, path, data=None, token=None, *, csrf=True, origin="http://localhost",
            marker="1", client=None, **extra):
        headers = {"HTTP_HOST": "localhost", "REMOTE_ADDR": "127.0.0.1",
                   "HTTP_X_WAINAK_DELETION_WEB": marker}
        if origin is not None:
            headers["HTTP_ORIGIN"] = origin
        if csrf is not False:
            headers["HTTP_X_CSRFTOKEN"] = self.web_csrf if csrf is True else csrf
        if token is not None:
            headers["HTTP_X_SESSION_TOKEN"] = token
        headers.update(extra)
        response = (client or self.web_client).generic(method, path,
            data=json.dumps(data or {}).encode(), content_type="application/json", **headers)
        if response.get("X-CSRFToken"):
            self.web_csrf = response["X-CSRFToken"]
        try:
            body = json.loads(response.content)
        except (ValueError, UnicodeError):
            self.fail("Expected bounded JSON, never content/credentials in an assertion")
        return response.status_code, body, response

    def test_web_page_has_non_reused_csp_nonce_and_private_csrf_cookie(self):
        first = self.open_web()
        html = first.content.decode()
        csp = first["Content-Security-Policy"]
        nonce = re.search(r"script-src 'nonce-([^']+)'", csp)
        self.assertTrue(bool(nonce))
        self.assertTrue('nonce="'+nonce[1]+'"' in html)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(first["Cache-Control"], "no-store")
        self.assertEqual(first["Referrer-Policy"], "no-referrer")
        cookie = first.cookies["wainak_deletion_csrf"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        second = self.web_client.get("/account-deletion", HTTP_HOST="localhost")
        second_nonce = re.search(r"script-src 'nonce-([^']+)'", second["Content-Security-Policy"])
        self.assertTrue(bool(second_nonce) and second_nonce[1] != nonce[1])
        self.assertIn('role="status"', html)
        self.assertIn('lang="ar" dir="rtl"', html)
        self.assertEqual(User.objects.count(), 0)

    def test_web_csrf_gate_rejects_missing_wrong_foreign_and_cookieless_even_with_bearer(self):
        token, _ = self.account("qa_web@example.invalid")
        self.open_web()
        for options in ({"csrf": False}, {"csrf": "a"*64}, {"origin": None},
                        {"origin": "http://foreign.example.invalid"},
                        {"origin": "http://localhost:9"}, {"origin": "https://localhost"}):
            with self.subTest(case=tuple(options.keys())):
                self.expect_status(self.web("DELETE", "/identity/v1/me",
                    {"confirmation": "DELETE"}, token, **options), 403)
        empty = Client(enforce_csrf_checks=True, raise_request_exception=False)
        self.expect_status(self.web("DELETE", "/identity/v1/me",
            {"confirmation": "DELETE"}, token, client=empty), 403)
        # Positive valid bearer does not let the downstream csrf_exempt app opt out.
        self.expect_status(self.web("POST", AUTH+"auth/login",
            {"email": "qa_web@example.invalid", "password": self.password}, csrf=False), 403)
        self.assertEqual(User.objects.count(), 1)

    def test_web_login_rotates_csrf_then_reauth_and_delete_work_without_reload(self):
        original, _ = self.account("qa_web@example.invalid")
        self.open_web()
        stale = self.web_csrf
        old_cookie = self.web_client.cookies["wainak_deletion_csrf"].value
        login = self.web("POST", AUTH+"auth/login",
            {"email": "qa_web@example.invalid", "password": self.password})
        self.expect_status(login, 200)
        token = login[1]["meta"]["session_token"]
        self.assertTrue(old_cookie != self.web_client.cookies["wainak_deletion_csrf"].value)
        self.assertTrue(bool(login[2].get("X-CSRFToken")))
        self.expect_status(self.web("POST", "/identity/v1/reauthenticate",
            {"password": self.password}, token, csrf=stale), 403)
        self.expect_status(self.web("POST", "/identity/v1/reauthenticate",
            {"password": self.password}, token), 200)
        self.expect_status(self.web("DELETE", "/identity/v1/me",
            {"confirmation": "DELETE"}, token), 200)
        self.expect_status(self.call("GET", "/identity/v1/me", token=original), 401)
        self.assertEqual(User.objects.count(), 0)

    def test_web_pending_login_and_delete_require_owned_flow_not_email_only(self):
        self.signup("qa_web_pending@example.invalid")
        self.open_web()
        self.expect_status(self.web("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE"}), 401)
        login = self.web("POST", AUTH+"auth/login",
            {"email": "qa_web_pending@example.invalid", "password": self.password})
        self.expect_status(login, 401)
        token = login[1]["meta"]["session_token"]
        self.expect_status(self.web("DELETE", PENDING,
            {"password": self.password, "confirmation": "DELETE"}, token), 200)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(EmailAddress.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)

    def test_web_marker_cannot_expand_routes_or_enable_cookie_auth_and_native_rule_stays(self):
        token, _ = self.account("qa_web@example.invalid")
        profile = {"gender": "male", "country": "SA", "marital_status": "single",
                   "declared_wives": 0, "marriage_goal": "build_family", "discoverable": True}
        self.expect_status(self.call("PUT", "/v1/me/profile", profile, token), 200)
        self.open_web()
        self.expect_status(self.web("PUT", "/v1/me/profile", profile, token), 404)
        self.expect_status(self.web("POST", AUTH+"auth/signup", {
            "email": "qa_new@example.invalid", "password": self.password,
            "birth_date": "1995-01-01", "is_muslim": True,
            "terms_version": baseline.POLICY_VERSION, "privacy_version": baseline.POLICY_VERSION}), 404)
        self.expect_status(self.web("DELETE", "/identity/v1/me",
            {"confirmation": "DELETE"}, token, marker="true"), 403)
        self.expect_status(self.web("DELETE", "/identity/v1/me",
            {"confirmation": "DELETE"}, token, HTTP_AUTHORIZATION="Bearer synthetic-not-accepted"), 400)
        self.expect_status(self.web("DELETE", "/identity/v1/me?token=synthetic",
            {"confirmation": "DELETE"}, token), 400)
        self.expect_status(self.call("DELETE", "/identity/v1/me",
            {"confirmation": "DELETE"}, token, HTTP_ORIGIN="http://localhost"), 403)
        self.web_client.cookies["sessionid"] = "x"*32
        self.expect_status(self.web("DELETE", "/identity/v1/me",
            {"confirmation": "DELETE"}, token), 403)
        self.assertEqual(User.objects.count(), 1)

    def test_web_entry_preserves_atomic_email_rate_limit(self):
        self.open_web()
        for index in range(6):
            response = self.web("POST", AUTH+"auth/login",
                {"email": "qa_unknown@example.invalid", "password": self.password})
            if index < 5:
                self.assertTrue(response[0] in (400, 401))
            else:
                self.expect_status(response, 429)
                self.assertTrue(response[2].get("Retry-After", "").isdigit())

    def test_live_loopback_web_cookie_csrf_login_reauth_delete_round_trip(self):
        import http.cookiejar
        import multiprocessing
        import urllib.error
        import urllib.request
        import identity_integration
        self.account("qa_live_web@example.invalid")
        connections.close_all()
        context = multiprocessing.get_context("fork")
        ready, stop = context.Queue(), context.Event()
        process = context.Process(target=identity_integration._serve_owned_http, args=(ready, stop))
        try:
            process.start()
            port = ready.get(timeout=10)
            self.assertTrue(isinstance(port, int) and 0 < port < 65536)
            origin = "http://127.0.0.1:"+str(port)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with opener.open(origin+"/account-deletion", timeout=10) as response:
                self.assertEqual(response.status, 200)
                html = response.read(65536).decode()
            match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
            self.assertTrue(bool(match))
            csrf = match[1]
            def request(method, path, data, token=None):
                nonlocal csrf
                headers = {"Content-Type": "application/json", "Origin": origin,
                           "X-Wainak-Deletion-Web": "1", "X-CSRFToken": csrf}
                if token:
                    headers["X-Session-Token"] = token
                req = urllib.request.Request(origin+path, method=method,
                    data=json.dumps(data).encode(), headers=headers)
                try:
                    with opener.open(req, timeout=10) as response:
                        status, raw, refreshed = response.status, response.read(16385), response.headers.get("X-CSRFToken")
                except urllib.error.HTTPError as response:
                    status, raw, refreshed = response.code, response.read(16385), response.headers.get("X-CSRFToken")
                if refreshed:
                    csrf = refreshed
                return status, json.loads(raw)
            status, body = request("POST", AUTH+"auth/login",
                {"email": "qa_live_web@example.invalid", "password": self.password})
            self.assertEqual(status, 200)
            token = body["meta"]["session_token"]
            status, _ = request("POST", "/identity/v1/reauthenticate", {"password": self.password}, token)
            self.assertEqual(status, 200)
            status, body = request("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)
            self.assertEqual(status, 200)
            self.assertTrue(body["identity_erased"])
        finally:
            stop.set()
            if process.pid is not None:
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
            alive = process.pid is not None and process.is_alive()
            try:
                ready.close()
                ready.join_thread()
            finally:
                connections.close_all()
            self.assertFalse(alive, "Owned loopback fixture must be stopped")
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)


    def test_orphan_keyset_advances_past_a_full_owned_active_batch(self):
        for email in ("qa_batch_a@example.invalid", "qa_batch_b@example.invalid", "qa_batch_c@example.invalid"):
            self.signup(email)
        users = list(User.objects.order_by("pk"))
        now = timezone.now()
        User.objects.update(date_joined=now-timedelta(hours=25))
        orphan = users[-1]
        DigestSession.objects.filter(user=orphan).update(expire_date=now)
        # Small injected batch exercises the identical keyset algorithm without
        # manufacturing100 account/password fixtures or claiming capacity testing.
        with mock.patch("wainak_identity.deletion.DEV_ORPHAN_BATCH_SIZE", 2), mock.patch(
            "django.utils.timezone.now", return_value=now):
            first = expire_orphaned_staged_accounts(dry_run=False)
            self.assertEqual(first["scanned_candidates"], 2)
            self.assertEqual(first["purged_unverified_accounts"], 0)
            self.assertTrue(first["next_after_id"] is not None)
            second = expire_orphaned_staged_accounts(dry_run=False, after_id=first["next_after_id"])
        self.assertEqual(second["scanned_candidates"], 1)
        self.assertEqual(second["purged_unverified_accounts"], 1)
        self.assertIsNone(second["next_after_id"])
        self.assertFalse(User.objects.filter(pk=orphan.pk).exists())
        self.assertEqual(User.objects.count(), 2)
