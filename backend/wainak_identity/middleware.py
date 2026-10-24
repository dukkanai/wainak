import json
import re
from django.conf import settings
from django.db import connection, transaction
from django.http import JsonResponse
from wainak.api import unique_object
from wainak.domain import DomainError
from . import rate_limits

AUTH_LOCK_ID = 8724102402
AUTH_PREFIX = "/_allauth/app/v1/"
ALLOWED_AUTH = {
    ("POST", "auth/signup"): {"email", "password", "birth_date", "is_muslim", "terms_version", "privacy_version"},
    ("POST", "auth/login"): {"email", "password"},
    ("POST", "auth/email/verify"): {"key"},
    ("POST", "auth/email/verify/resend"): set(),
    ("POST", "auth/password/request"): {"email"},
    ("POST", "auth/password/reset"): {"key", "password"},
    ("POST", "account/password/change"): {"current_password", "new_password"},
    ("GET", "auth/session"): set(), ("DELETE", "auth/session"): set(),
}


def error(status, code):
    return JsonResponse({"error": {"code": code, "message": "The request cannot be completed."}}, status=status)


class SyntheticBoundary:
    def __init__(self, get_response):
        from django.middleware.csrf import CsrfViewMiddleware
        self.get_response = get_response
        self.csrf = CsrfViewMiddleware(get_response)

    def __call__(self, request):
        response = self.handle(request)
        if getattr(request, "_wainak_deletion_web", False):
            if getattr(request, "_wainak_deletion_web_api", False):
                from django.middleware.csrf import get_token
                # Django rotates its CSRF secret on login. Refresh the masked
                # token without putting it in a URL or readable cookie.
                response["X-CSRFToken"] = get_token(request)
            response = self.csrf.process_response(request, response)
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        response["X-Content-Type-Options"] = "nosniff"
        response.setdefault("Content-Security-Policy", "default-src 'none'")
        return response

    def handle(self, request):
        if settings.WAINAK_IDENTITY_SANDBOX is not True or connection.vendor != "postgresql":
            return error(503, "sandbox_not_configured")
        if not re.fullmatch(r"(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?", request.META.get("HTTP_HOST", "")):
            return error(403, "local_only")
        from .web_deletion import WEB_PATH, WEB_OPERATIONS, csrf_protected_callback
        web_page = request.path.rstrip("/") == WEB_PATH and request.method == "GET"
        marker = request.META.get("HTTP_X_WAINAK_DELETION_WEB")
        if marker is not None and marker != "1":
            return error(403, "unsupported_transport")
        web_api = marker == "1"
        if web_api and (request.method, request.path) not in WEB_OPERATIONS:
            return error(404, "web_operation_not_available")
        if web_page or web_api:
            if set(request.COOKIES) - {settings.CSRF_COOKIE_NAME}:
                return error(403, "unsupported_cookies")
            request._wainak_deletion_web = True
            request._wainak_deletion_web_api = web_api
            self.csrf.process_request(request)
            if web_api:
                if not request.META.get("HTTP_ORIGIN"):
                    return error(403, "csrf_required")
                # The sentinel is NOT csrf_exempt; downstream allauth app views
                # cannot opt this browser-specific boundary out of CSRF checking.
                if self.csrf.process_view(request, csrf_protected_callback, (), {}) is not None:
                    return error(403, "csrf_failed")
        elif request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_COOKIE"):
            return error(403, "native_sandbox_only")
        if request.META.get("QUERY_STRING") or request.META.get("HTTP_AUTHORIZATION"):
            return error(400, "unsupported_credentials_or_query")
        path = request.path
        if web_page:
            return self.get_response(request)
        if path.startswith(AUTH_PREFIX) and (request.method, path[len(AUTH_PREFIX):]) not in ALLOWED_AUTH:
            return error(404, "not_found")
        if path.startswith("/v1/dev/") or path.startswith("/_allauth/") and not path.startswith(AUTH_PREFIX):
            return error(404, "not_found")
        data = {}
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            length = request.META.get("CONTENT_LENGTH", "0")
            if not length.isascii() or not length.isdigit() or len(length) > 8 or int(length) > 16384:
                return error(413, "invalid_body_length")
            if int(length):
                if request.content_type != "application/json":
                    return error(415, "json_required")
                try:
                    data = json.loads(request.body, object_pairs_hook=unique_object,
                                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
                    if not isinstance(data, dict):
                        raise ValueError()
                except (ValueError, UnicodeError, DomainError, RecursionError):
                    return error(400, "invalid_json")
            if path.startswith(AUTH_PREFIX):
                if set(data) - ALLOWED_AUTH[(request.method, path[len(AUTH_PREFIX):])]:
                    return error(400, "invalid_input")
                if any(key != "is_muslim" and not isinstance(value, str) for key, value in data.items()):
                    return error(400, "invalid_input_type")
                if path.endswith("auth/signup") and data.get("is_muslim") is not True:
                    return error(400, "explicit_declaration_required")
                if "email" in data and isinstance(data["email"], str):
                    from .adapters import canonical_email
                    from django.core.exceptions import ValidationError
                    try:
                        data["email"] = canonical_email(data["email"])
                    except ValidationError:
                        return error(400, "synthetic_email_required")
                    request._body = json.dumps(data, separators=(",", ":")).encode()
        request.identity_data = data
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout='20s'")
                    cursor.execute("SET LOCAL lock_timeout='10s'")
                    # Correctness-first bounded sandbox. Lock BEFORE session/auth
                    # loading, then domain lock on the SAME connection/transaction.
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [AUTH_LOCK_ID])
                if not settings.WAINAK_DISABLE_LIMITS_FOR_FIXTURES:
                    limited = self.limit(request, data)
                    if limited:
                        return limited
                response = self.get_response(request)
                if response.status_code >= 500:
                    transaction.set_rollback(True)
                    return error(500, "internal_error")
                return response
        except Exception:
            return error(500, "internal_error")

    def limit(self, request, data):
        path = request.path
        if not path.startswith(AUTH_PREFIX) and path not in {"/identity/v1/reauthenticate", "/identity/v1/pending-account"}:
            return None
        action = path
        ip = request.META.get("REMOTE_ADDR", "unknown")
        scopes = [("ip", ip, 30, 60)]
        email = data.get("email")
        if isinstance(email, str):
            scopes.append(("email", email, 5, 300 if path.endswith("login") else 3600))
        token = request.META.get("HTTP_X_SESSION_TOKEN")
        if token and request.method != "GET":
            scopes.append(("session", token, 10, 60))
        for kind, subject, limit, seconds in scopes:
            if not rate_limits.consume(action, kind, subject, limit, seconds):
                response = error(429, "rate_limited")
                response["Retry-After"] = str(seconds)
                return response
        return None
