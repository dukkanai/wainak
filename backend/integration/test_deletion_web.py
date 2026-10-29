"""Synthetic deletion addition: ownership, orphan maintenance and real CSRF."""
import json
import re
import unittest
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.db import connection, connections
from django.test import Client, override_settings
from django.utils import timezone
from allauth.account.models import EmailAddress
import identity_integration as baseline
from identity_integration import AUTH
from wainek_identity.deletion import expire_orphaned_staged_accounts
from wainek_identity.models import User, DigestSession, DeletionReceipt, RateBucket
from wainek_identity.sessions import digest_token


class DeletionWebTests(unittest.TestCase):
    setUp = baseline.IdentityIntegrationTests.setUp
    call = baseline.IdentityIntegrationTests.call
    status = baseline.IdentityIntegrationTests.status
    signup = baseline.IdentityIntegrationTests.signup
    account = baseline.IdentityIntegrationTests.account
    login = baseline.IdentityIntegrationTests.login

    def pending_delete(self, token, password=None, **headers):
        return self.call("DELETE", "/identity/v1/pending-account",
                         {"password": password or self.password, "confirmation": "DELETE"}, token, **headers)

    def test_owned_pending_delete_erases_without_verifying_and_old_code_cannot_resurrect(self):
        pending, code = self.signup()
        status, body = self.pending_delete(pending)
        self.status(status, 200, body)
        self.assertTrue(body["identity_erased"])
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(EmailAddress.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)
        status, _ = self.call("POST", AUTH+"auth/email/verify", {"key": code}, pending)
        self.assertIn(status, (400, 401, 409, 410))
        self.assertEqual(User.objects.count(), 0)

    def test_pending_delete_requires_password_current_flow_and_no_verified_fallback(self):
        pending, code = self.signup()
        status, _ = self.pending_delete(pending, password="wrong-fixture-password")
        self.status(status, 403)
        status, _ = self.pending_delete(None)
        self.status(status, 401)
        status, _ = self.pending_delete(digest_token(pending))
        self.status(status, 401)
        status, body = self.call("POST", AUTH+"auth/login", {"email": "alpha@example.invalid", "password": self.password})
        self.status(status, 401, body)
        other_pending = body["meta"]["session_token"]
        status, body = self.call("POST", AUTH+"auth/email/verify", {"key": code}, pending)
        self.status(status, 200, body)
        status, _ = self.pending_delete(other_pending)
        self.status(status, 401)
        self.assertEqual(User.objects.count(), 1)
        self.assertTrue(EmailAddress.objects.get().verified)

    def test_duplicate_pending_signup_cannot_delete_the_original_account(self):
        original, _ = self.signup()
        from wainek.domain import POLICY_VERSION
        status, body = self.call("POST", AUTH+"auth/signup", {
            "email": "alpha@example.invalid", "password": self.password, "birth_date": "1995-01-01",
            "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.status(status, 401, body)
        duplicate = body["meta"]["session_token"]
        status, _ = self.pending_delete(duplicate)
        self.status(status, 401)
        self.assertEqual(User.objects.count(), 1)
        status, _ = self.pending_delete(original)
        self.status(status, 200)

    def test_pending_delete_has_atomic_session_rate_limit(self):
        pending, _ = self.signup()
        for _ in range(10):
            status, _ = self.pending_delete(pending, password="wrong-fixture-password")
            self.status(status, 403)
        status, _ = self.pending_delete(pending)
        self.status(status, 429)
        self.assertEqual(User.objects.count(), 1)

    def test_verify_delete_race_has_one_winner_without_resurrection(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        pending, code = self.signup()
        barrier = threading.Barrier(2)
        def action(delete):
            try:
                barrier.wait(timeout=5)
                client = Client(raise_request_exception=False)
                if delete:
                    return self.pending_delete(pending, client=client)[0]
                return self.call("POST", AUTH+"auth/email/verify", {"key": code}, pending, client=client)[0]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            deleted, verified = list(pool.map(action, (True, False)))
        self.assertEqual(int(deleted == 200)+int(verified == 200), 1)
        if deleted == 200:
            self.assertEqual(User.objects.count(), 0)
            self.assertEqual(DigestSession.objects.count(), 0)
        else:
            self.assertEqual(User.objects.count(), 1)
            self.assertTrue(EmailAddress.objects.get().verified)

    def snapshot(self):
        # Compare booleans only: no password hash/ciphertext on assertion output.
        result = [list(model.objects.order_by("pk").values()) for model in
                  (User, EmailAddress, DigestSession, DeletionReceipt, RateBucket)]
        with connection.cursor() as cursor:
            cursor.execute("SELECT id,data FROM wainak_phase1_dev.accounts ORDER BY id")
            result.append(cursor.fetchall())
        return result

    def test_orphan_dry_run_preserves_rows_and_apply_excludes_verified_active_and_young(self):
        orphan, _ = self.signup()
        active, _ = self.signup("active@example.invalid")
        verified, _ = self.account("verified@example.invalid")
        young, _ = self.signup("young@example.invalid")
        now = timezone.now()
        User.objects.exclude(email="young@example.invalid").update(date_joined=now-timedelta(hours=24))
        DigestSession.objects.filter(session_key__in=[digest_token(orphan), digest_token(young)]).update(expire_date=now)
        before = self.snapshot()
        with mock.patch("wainek_identity.deletion.timezone.now", return_value=now):
            report = expire_orphaned_staged_accounts()
        self.assertEqual(report["eligible_orphaned_accounts"], 1)
        self.assertEqual(report["purged_unverified_accounts"], 0)
        self.assertTrue(before == self.snapshot(), "Dry run must not touch any inspected rows")
        with mock.patch("wainek_identity.deletion.timezone.now", return_value=now):
            report = expire_orphaned_staged_accounts(dry_run=False)
        self.assertEqual(report["purged_unverified_accounts"], 1)
        self.assertFalse(report["production_retention_approved"])
        self.assertFalse(User.objects.filter(email="alpha@example.invalid").exists())
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(DeletionReceipt.objects.count(), 1)

    def test_orphan_failure_rolls_back_identity_domain_and_expired_session_pruning(self):
        token, _ = self.signup()
        now = timezone.now()
        User.objects.update(date_joined=now-timedelta(hours=25))
        DigestSession.objects.update(expire_date=now-timedelta(seconds=1))
        before = self.snapshot()
        with mock.patch.object(User, "delete", side_effect=RuntimeError("Synthetic orphan failure")):
            with self.assertRaises(RuntimeError):
                expire_orphaned_staged_accounts(dry_run=False)
        self.assertTrue(before == self.snapshot(), "Failed cleanup must roll back every inspected row")
        with override_settings(WAINEK_IDENTITY_SANDBOX=False), self.assertRaises(RuntimeError):
            expire_orphaned_staged_accounts(dry_run=False)

    def open_web(self):
        self.web_client = Client(enforce_csrf_checks=True, raise_request_exception=False)
        response = self.web_client.get("/account-deletion", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        self.assertTrue(bool(match), "Page must expose a masked CSRF token, never an account bearer")
        self.web_csrf = match[1]
        return response, html

    def web(self, method, path, data=None, token=None, *, csrf=True, origin="http://localhost", marker="1"):
        headers = {"HTTP_HOST": "localhost", "REMOTE_ADDR": "127.0.0.1", "HTTP_X_WAINEK_DELETION_WEB": marker}
        if origin is not None:
            headers["HTTP_ORIGIN"] = origin
        if csrf is not False:
            headers["HTTP_X_CSRFTOKEN"] = self.web_csrf if csrf is True else csrf
        if token:
            headers["HTTP_X_SESSION_TOKEN"] = token
        response = self.web_client.generic(method, path, data=json.dumps(data or {}).encode(), content_type="application/json", **headers)
        if response.get("X-CSRFToken"):
            self.web_csrf = response["X-CSRFToken"]
        try:
            body = json.loads(response.content)
        except ValueError:
            self.fail("Web mutation must return bounded JSON, not HTML or credentials")
        return response.status_code, body

    def test_web_surface_accessibility_metadata_and_no_application_secret_storage(self):
        response, html = self.open_web()
        self.assertIn('lang="ar" dir="rtl"', html)
        self.assertIn('lang="en"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('method="post" action="/account-deletion"', html)
        self.assertIn('type="password"', html)
        self.assertIn("window.addEventListener('pagehide', clearSecrets)", html)
        for forbidden in ("localStorage", "sessionStorage", "document.cookie", "console."):
            self.assertNotIn(forbidden, html)
        cookie = response.cookies[settings.CSRF_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", response["Content-Security-Policy"])
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_web_mutations_require_actual_csrf_origin_and_allowlist_even_with_valid_bearer(self):
        token, _ = self.account()
        self.open_web()
        data = {"confirmation": "DELETE"}
        for extra in ({"csrf": False}, {"csrf": "a"*64}, {"origin": None}, {"origin": "https://example.invalid"}):
            status, body = self.web("DELETE", "/identity/v1/me", data, token, **extra)
            self.status(status, 403, body)
        # The downstream allauth app login is csrf_exempt: our sentinel is NOT.
        status, _ = self.web("POST", AUTH+"auth/login", {"email": "alpha@example.invalid", "password": self.password}, csrf=False)
        self.status(status, 403)
        status, _ = self.web("POST", AUTH+"auth/login", {"email": "alpha@example.invalid", "password": self.password}, marker="2")
        self.status(status, 403)
        status, _ = self.web("PUT", "/v1/me/profile", {}, token)
        self.status(status, 404)
        self.assertEqual(User.objects.count(), 1)

    def test_web_verified_delete_uses_login_csrf_rotation_password_reauth_and_current_session(self):
        original, _ = self.account()
        self.open_web()
        old_csrf = self.web_csrf
        old_cookie = self.web_client.cookies[settings.CSRF_COOKIE_NAME].value
        status, body = self.web("POST", AUTH+"auth/login", {"email": "alpha@example.invalid", "password": self.password})
        self.status(status, 200, body)
        token = body["meta"]["session_token"]
        self.assertTrue(old_cookie != self.web_client.cookies[settings.CSRF_COOKIE_NAME].value, "Login rotates CSRF cookie secret")
        status, _ = self.web("POST", "/identity/v1/reauthenticate", {"password": self.password}, token, csrf=old_csrf)
        self.status(status, 403)
        status, body = self.web("POST", "/identity/v1/reauthenticate", {"password": self.password}, token)
        self.status(status, 200, body)
        status, body = self.web("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)
        self.status(status, 200, body)
        self.assertTrue(body["identity_erased"])
        status, _ = self.call("GET", "/identity/v1/me", token=original)
        self.status(status, 401)

    def test_web_owned_pending_registration_can_be_erased_without_email_verification(self):
        self.signup()
        self.open_web()
        status, body = self.web("POST", AUTH+"auth/login", {"email": "alpha@example.invalid", "password": self.password})
        self.status(status, 401, body)
        token = body["meta"]["session_token"]
        status, body = self.web("DELETE", "/identity/v1/pending-account",
                               {"password": self.password, "confirmation": "DELETE"}, token)
        self.status(status, 200, body)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)

    def test_native_origin_cookie_rule_and_web_cookie_auth_remain_disabled(self):
        token, _ = self.account()
        self.open_web()
        status, _ = self.call("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token,
                              client=self.web_client, HTTP_ORIGIN="http://localhost")
        self.status(status, 403)
        status, _ = self.web("DELETE", "/identity/v1/me", {"confirmation": "DELETE"})
        self.status(status, 401)
        self.web_client.cookies["sessionid"] = token
        status, _ = self.web("DELETE", "/identity/v1/me", {"confirmation": "DELETE"}, token)
        self.status(status, 403)
        self.assertEqual(User.objects.count(), 1)

    def test_real_loopback_http_cookie_csrf_login_reauth_delete_without_browser_execution(self):
        import multiprocessing
        import urllib.request
        import urllib.error
        import http.cookiejar
        original, _ = self.account()
        context = multiprocessing.get_context("fork")
        ready, stop = context.Queue(), context.Event()
        connections.close_all()
        process = context.Process(target=baseline._serve_owned_http, args=(ready, stop))
        process.start()
        try:
            port = ready.get(timeout=10)
            self.assertTrue(isinstance(port, int) and 0 < port < 65536)
            origin = f"http://127.0.0.1:{port}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with opener.open(origin+"/account-deletion", timeout=10) as response:
                html = response.read(32768).decode()
            match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
            self.assertTrue(bool(match), "Actual HTTP page must supply masked CSRF")
            csrf = match[1]
            def mutation(path, method, data, token=None):
                nonlocal csrf
                headers = {"Origin": origin, "X-Wainek-Deletion-Web": "1", "X-CSRFToken": csrf,
                           "Content-Type": "application/json"}
                if token:
                    headers["X-Session-Token"] = token
                request = urllib.request.Request(origin+path, method=method, data=json.dumps(data).encode(), headers=headers)
                try:
                    response = opener.open(request, timeout=10)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    csrf = response.headers.get("X-CSRFToken", csrf)
                    return response.status, json.loads(response.read(16385))
            status, body = mutation(AUTH+"auth/login", "POST", {"email": "alpha@example.invalid", "password": self.password})
            self.status(status, 200, body)
            token = body["meta"]["session_token"]
            status, body = mutation("/identity/v1/reauthenticate", "POST", {"password": self.password}, token)
            self.status(status, 200, body)
            status, body = mutation("/identity/v1/me", "DELETE", {"confirmation": "DELETE"}, token)
            self.status(status, 200, body)
            self.assertTrue(body["identity_erased"])
            status, _ = self.call("GET", "/identity/v1/me", token=original)
            self.status(status, 401)
        finally:
            stop.set()
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
            ready.close()
            ready.join_thread()
            self.assertFalse(process.is_alive(), "Owned HTTP fixture process must be removed")
            connections.close_all()

    def test_fake_duplicate_pending_does_not_keep_an_old_orphan_alive(self):
        original, _ = self.signup()
        from wainek.domain import POLICY_VERSION
        status, body = self.call("POST", AUTH+"auth/signup", {
            "email": "alpha@example.invalid", "password": self.password, "birth_date": "1995-01-01",
            "is_muslim": True, "terms_version": POLICY_VERSION, "privacy_version": POLICY_VERSION})
        self.status(status, 401, body)
        duplicate = body["meta"]["session_token"]
        now = timezone.now()
        User.objects.update(date_joined=now-timedelta(hours=25))
        DigestSession.objects.filter(session_key=digest_token(original)).update(expire_date=now-timedelta(seconds=1))
        self.assertTrue(DigestSession.objects.filter(session_key=digest_token(duplicate), expire_date__gt=now).exists())
        report = expire_orphaned_staged_accounts()
        self.assertEqual(report["eligible_orphaned_accounts"], 1)
        report = expire_orphaned_staged_accounts(dry_run=False)
        self.assertEqual(report["purged_unverified_accounts"], 1)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(DigestSession.objects.count(), 0)

    def test_keyset_progress_reaches_orphan_after_a_full_active_batch(self):
        for email in ("first@example.invalid", "second@example.invalid", "third@example.invalid"):
            self.signup(email)
        now = timezone.now()
        User.objects.update(date_joined=now-timedelta(hours=25))
        last = User.objects.order_by("pk").last()
        DigestSession.objects.filter(user=last).update(expire_date=now-timedelta(seconds=1))
        with mock.patch("wainek_identity.deletion.DEV_ORPHAN_BATCH_SIZE", 2):
            first = expire_orphaned_staged_accounts(dry_run=False)
            self.assertEqual(first["scanned_candidates"], 2)
            self.assertEqual(first["purged_unverified_accounts"], 0)
            self.assertTrue(isinstance(first["next_after_id"], str))
            second = expire_orphaned_staged_accounts(dry_run=False, after_id=first["next_after_id"])
        self.assertEqual(second["purged_unverified_accounts"], 1)
        self.assertIsNone(second["next_after_id"])
        self.assertEqual(User.objects.count(), 2)

    def test_pending_delete_rejects_expired_framework_verification_flow(self):
        pending, _ = self.signup()
        from wainek_identity.sessions import SessionStore
        issued = SessionStore(pending).get("account_email_verification_code")["at"]
        with mock.patch("wainek_identity.deletion.time.time", return_value=issued+600.001):
            status, body = self.pending_delete(pending)
        self.status(status, 410, body)
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(DigestSession.objects.filter(session_key=digest_token(pending)).exists())
