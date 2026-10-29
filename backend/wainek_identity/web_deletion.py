"""Local-only deletion UI; marker selects stricter CSRF, never authentication."""
import secrets

from django.http import HttpResponse, HttpResponseNotAllowed
from django.middleware.csrf import get_token
from django.template.loader import render_to_string

WEB_PATH = "/account-deletion"
WEB_OPERATIONS = {
    ("POST", "/_allauth/app/v1/auth/login"),
    ("POST", "/_allauth/app/v1/auth/email/verify"),
    ("POST", "/_allauth/app/v1/auth/email/verify/resend"),
    ("DELETE", "/_allauth/app/v1/auth/session"),
    ("POST", "/identity/v1/reauthenticate"),
    ("DELETE", "/identity/v1/me"),
    ("DELETE", "/identity/v1/pending-account"),
}


def csrf_protected_callback(request):
    """Deliberately NOT csrf_exempt, even when the downstream app view is."""
    raise RuntimeError("This CSRF sentinel is inspected, never invoked")


def page(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    nonce = secrets.token_urlsafe(24)  # Ephemeral CSP nonce, not an account secret.
    html = render_to_string("wainek_identity/account_deletion.html",
                            {"csrf_token_value": get_token(request), "nonce": nonce})
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
        "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
    response["X-Frame-Options"] = "DENY"
    response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response
