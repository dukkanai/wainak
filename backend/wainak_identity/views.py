import hashlib
import json
import re
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from allauth.account.models import EmailAddress
from allauth.headless.internal.sessionkit import authenticate_by_x_session_token
from wainak.domain import DomainError, fail, fields
from .middleware import error
from .models import DigestSession, MutationReceipt
from .repository import service
from . import rate_limits


def authenticated(request):
    token = request.META.get("HTTP_X_SESSION_TOKEN", "")
    result = authenticate_by_x_session_token(token) if token else None
    if not result or not result[0].is_active:
        fail(401, "unauthenticated", "A current authenticated session is required.")
    user, session = result
    if not EmailAddress.objects.filter(user=user, email__iexact=user.email, verified=True).exists():
        fail(403, "email_verification_required", "Email ownership verification is required.")
    if not user.domain_id:
        fail(403, "account_unavailable", "The account is unavailable.")
    return user, session


def recent_auth(session):
    when = session.get("recent_auth_at")
    now = timezone.now().timestamp()
    if not isinstance(when, (int, float)) or when > now or now - when >= settings.WAINAK_REAUTH_SECONDS:
        fail(403, "reauthentication_required", "Recent authentication is required.")


def delete_identity(user, session, data):
    recent_auth(session)
    fields(data, {"confirmation"})
    if data["confirmation"] != "DELETE":
        fail(400, "confirmation_required", "Confirm account deletion explicitly.")
    from .deletion import erase_identity
    return erase_identity(user, session)


def report(user, data, key):
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
        fail(400, "idempotency_key_required", "A bounded report idempotency key is required.")
    fields(data, {"target_id", "category"}, {"relationship_id"})
    key_digest = hashlib.sha256(key.encode()).hexdigest()
    payload_digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = MutationReceipt.objects.filter(actor=user, operation="report", key_digest=key_digest).first()
    domain = service()
    if receipt:
        if receipt.payload_digest != payload_digest:
            fail(409, "idempotency_conflict", "The request key was used with different fields.")
        with domain.repository.transaction() as state:
            old = state.reports.get(receipt.resource_id)
            if old is None:
                fail(410, "report_no_longer_available", "The synthetic report has been purged.")
            if old["reporter_id"] != user.domain_id:
                fail(404, "not_found", "The resource is not available.")
            return {"id": old["id"], "status": old["status"], "evidence_uploaded": False,
                    "notice": "No live moderation team is connected. This simulation applies no public penalty."}
    result = domain.report(user.domain_id, data)
    MutationReceipt.objects.create(actor=user, operation="report", key_digest=key_digest,
                                   payload_digest=payload_digest, resource_id=result["id"])
    return result


def dispatch(request):
    path, method = request.path, request.method
    if path == "/identity/v1/health" and method == "GET":
        return JsonResponse({"mode": "synthetic_identity_sandbox", "durable_storage": True,
                             "real_email": False, "production_ready": False})
    try:
        if path == "/identity/v1/pending-account" and method == "DELETE":
            from .deletion import delete_pending
            return JsonResponse(delete_pending(request, request.identity_data))
        user, session = authenticated(request)
        data = request.identity_data
        if path == "/identity/v1/reauthenticate" and method == "POST":
            fields(data, {"password"})
            if not isinstance(data["password"], str) or not user.check_password(data["password"]):
                fail(403, "reauthentication_failed", "Authentication could not be confirmed.")
            session["recent_auth_at"] = timezone.now().timestamp()
            session.save()
            return JsonResponse({"reauthenticated": True})
        if path == "/identity/v1/logout-all" and method == "POST":
            fields(data, set())
            from django.db.models import Q
            from .sessions import email_fingerprint
            DigestSession.objects.filter(Q(user=user) | Q(subject_email_digest=email_fingerprint(user.email))).delete()
            session.flush()
            return JsonResponse({"revoked_all": True})
        if path == "/identity/v1/me" and method == "GET":
            session.save()
            return JsonResponse({"id": str(user.pk), "domain_id": user.domain_id, "email": user.email,
                                 "email_verified": True, "mode": "synthetic_identity_sandbox",
                                 "email_is_identity_verification": False})
        if path in {"/identity/v1/me", "/v1/me"} and method == "DELETE":
            return JsonResponse(delete_identity(user, session, data))
        if method == "POST" and path in {"/v1/reports", "/v1/relationships"}:
            limit = 10
            seconds = 3600 if path == "/v1/reports" else 60
            if not settings.WAINAK_DISABLE_LIMITS_FOR_FIXTURES and not rate_limits.consume(path, "user", str(user.pk), limit, seconds):
                response = error(429, "rate_limited")
                response["Retry-After"] = str(seconds)
                return response
        # Internal actor comes ONLY from the framework-authenticated User; never JSON/header actor input.
        actor, domain = user.domain_id, service()
        safety_decline = (method == "POST"
            and re.fullmatch(r"/v1/relationships/rel_[0-9a-f]{32}/respond", path) is not None
            and data == {"decision": "decline"})
        protected = (path.startswith("/v1/candidates") or path in {
            "/v1/me/profile", "/v1/me/preferences", "/v1/me/assessment", "/v1/me/assessment/answers"}
            or method == "POST" and path.startswith("/v1/relationships")
            and not path.endswith(("/end", "/cancel")) and not safety_decline)
        if protected:
            domain.require_current_consents(actor)
        routes = {
            ("GET", "/v1/me"): lambda: domain.me(actor),
            ("PUT", "/v1/me/profile"): lambda: domain.update_profile(actor, data),
            ("PUT", "/v1/me/preferences"): lambda: domain.update_preferences(actor, data),
            ("GET", "/v1/me/assessment"): lambda: domain.assessment(actor),
            ("POST", "/v1/me/assessment/answers"): lambda: domain.answer(actor, data),
            ("GET", "/v1/candidates"): lambda: domain.candidates(actor),
            ("GET", "/v1/relationships"): lambda: domain.list_relationships(actor),
            ("POST", "/v1/relationships"): lambda: domain.request(actor, data, request.META.get("HTTP_IDEMPOTENCY_KEY")),
            ("POST", "/v1/blocks"): lambda: domain.block(actor, data),
            ("POST", "/v1/reports"): lambda: report(user, data, request.META.get("HTTP_IDEMPOTENCY_KEY")),
        }
        route = routes.get((method, path))
        if route:
            result = route()
            session.save()
            return JsonResponse(result, status=201 if method == "POST" and path in {"/v1/relationships", "/v1/reports"} else 200)
        match = re.fullmatch(r"/v1/candidates/(usr_[0-9a-f]{32})", path)
        if match and method == "GET":
            return JsonResponse(domain.candidate(actor, match[1]))
        match = re.fullmatch(r"/v1/relationships/(rel_[0-9a-f]{32})(?:/(respond|cancel|end|cards|exclusive/request|exclusive/respond))?", path)
        if match:
            identifier, action = match.groups()
            if method == "GET" and action is None:
                return JsonResponse(domain.relationship(actor, identifier))
            if method == "GET" and action == "cards":
                return JsonResponse(domain.content(actor, identifier))
            actions = {"respond": domain.respond, "cancel": domain.cancel, "end": domain.end,
                       "exclusive/request": domain.request_exclusive, "exclusive/respond": domain.respond_exclusive}
            if method == "POST" and action in actions:
                return JsonResponse(actions[action](actor, identifier, data))
        return error(404, "not_found")
    except DomainError as exc:
        return JsonResponse({"error": {"code": exc.code, "message": exc.message}}, status=exc.status)
