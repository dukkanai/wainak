"""Synthetic account erasure and bounded orphan maintenance; no public jobs."""
from datetime import timedelta
import math
import time

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from allauth.account.models import EmailAddress
from wainak.domain import fail, fields

from .models import DeletionReceipt, DigestSession, RateBucket, User
from .repository import service
from .sessions import email_fingerprint

DEV_ORPHAN_BATCH_SIZE = 100
DEV_ORPHAN_HOURS = 24  # Test-fixture policy only; NOT approved production retention.
DEV_ORPHAN_POLICY = "synthetic-orphan-24h-not-production-retention"


def erase_identity(user, session=None, *, policy="synthetic-purge-v1-not-production-retention"):
    if not connection.in_atomic_block:
        raise RuntimeError("Erasure requires the shared identity/domain transaction")
    result = service().delete_account(user.domain_id, {"confirmation": "DELETE"})
    DeletionReceipt.objects.create(account_id=user.pk, domain_id=user.domain_id,
                                   deleted_at=timezone.now(), policy=policy)
    DigestSession.objects.filter(Q(user=user) | Q(subject_email_digest=email_fingerprint(user.email))).delete()
    user.delete()
    if session is not None:
        session.flush()
    return {**result, "identity_erased": True,
            "retained_synthetic_records": ["minimal_relationship_account_tombstones", "deletion_receipt",
                                           "other_accounts_idempotency_receipt_tombstones", "expiring_rate_counters",
                                           "fake_mailbox_snapshots_until_fixture_exit"],
            "retention_policy": policy,
            "limits": "No live backups, billing, E2EE history, evidence store or production retention is managed by this fixture."}


def delete_pending(request, data):
    from django.core.exceptions import ValidationError
    from allauth.account.internal.flows.email_verification_by_code import EmailVerificationProcess
    from allauth.headless.internal.sessionkit import lookup_session
    fields(data, {"password", "confirmation"})
    if data["confirmation"] != "DELETE" or not isinstance(data["password"], str):
        fail(400, "confirmation_required", "Explicit deletion confirmation and password are required.")
    raw = request.META.get("HTTP_X_SESSION_TOKEN", "")
    session = lookup_session(raw) if raw else None
    state = session.get("account_email_verification_code") if session else None
    if not isinstance(state, dict) or state.get("account_already_exists") or not state.get("user_id"):
        fail(401, "pending_ownership_required", "A current owned pending flow is required.")
    issued = state.get("at")
    if not isinstance(issued, (int, float)) or isinstance(issued, bool) or not math.isfinite(issued) or issued > time.time():
        fail(401, "pending_ownership_required", "A current owned pending flow is required.")
    process = EmailVerificationProcess(request, state)
    if not process.is_valid():
        session.delete()
        fail(410, "pending_flow_expired", "Sign in again before deleting the pending registration.")
    try:
        user = User.objects.filter(pk=state["user_id"], is_active=True).first()
    except (ValueError, ValidationError):
        user = None
    if (user is None or not user.domain_id or state.get("email") != user.email
            or EmailAddress.objects.filter(user=user, verified=True).exists()):
        fail(401, "pending_ownership_required", "A current owned pending flow is required.")
    if not user.check_password(data["password"]):
        fail(403, "reauthentication_failed", "Authentication could not be confirmed.")
    return erase_identity(user, session)


def _has_current_owned_session(user, now):
    from django.contrib.auth import SESSION_KEY, HASH_SESSION_KEY
    from django.utils.crypto import constant_time_compare
    rows = DigestSession.objects.filter(user=user, expire_date__gt=now,
        created_at__gt=now-timedelta(seconds=settings.WAINAK_SESSION_ABSOLUTE_SECONDS),
        last_seen_at__gt=now-timedelta(seconds=settings.WAINAK_SESSION_IDLE_SECONDS))
    for row in rows:
        data = row.get_decoded()  # Non-mutating; NEVER SessionStore.load()/touch.
        if (data.get(SESSION_KEY) == str(user.pk) and isinstance(data.get(HASH_SESSION_KEY), str)
                and constant_time_compare(data[HASH_SESSION_KEY], user.get_session_auth_hash())):
            return True
        pending = data.get("account_email_verification_code")
        if not isinstance(pending, dict) or pending.get("account_already_exists"):
            continue
        issued = pending.get("at")
        if (pending.get("user_id") == str(user.pk) and pending.get("email") == user.email
                and isinstance(issued, (int, float)) and not isinstance(issued, bool)
                and math.isfinite(issued) and 0 <= now.timestamp()-issued <= settings.ACCOUNT_EMAIL_VERIFICATION_BY_CODE_TIMEOUT):
            return True
    return False


def expire_orphaned_staged_accounts(*, dry_run=True, after_id=None):
    """Explicit owned-test maintenance, never automatically scheduled or exposed.

    Scan a bounded keyset page of unverified registrations aged >=24h with no
    currently valid OWNED session. after_id/next_after_id are internal non-auth
    UUID cursors (never email, password or session token), not a public endpoint.
    Restart from None for a later sweep, including concurrent new candidates. Serialize with verification/reset/delete before loading
    either identity or domain state. Expired rows/counters are also pruned.
    """
    if settings.WAINAK_IDENTITY_SANDBOX is not True or connection.vendor != "postgresql":
        raise RuntimeError("Orphan expiry is only configured for the disposable sandbox")
    from wainak.migrations import require_disposable_database
    from .middleware import AUTH_LOCK_ID
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be explicit boolean")
    now = timezone.now()
    count = eligible = scanned = 0
    last_id = None
    with transaction.atomic():
        connection.ensure_connection()
        require_disposable_database(connection.connection)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout='20s'")
            cursor.execute("SET LOCAL lock_timeout='10s'")
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [AUTH_LOCK_ID])
        sessions = DigestSession.objects.filter(expire_date__lte=now)
        counters = RateBucket.objects.filter(expires_at__lte=now)
        expired_sessions, expired_counters = sessions.count(), counters.count()
        if not dry_run:
            sessions.delete()
            counters.delete()
        from django.db.models import Exists, OuterRef
        verified = EmailAddress.objects.filter(user_id=OuterRef("pk"), verified=True)
        candidates = User.objects.annotate(has_verified=Exists(verified)).filter(
            date_joined__lte=now-timedelta(hours=DEV_ORPHAN_HOURS), has_verified=False)
        if after_id is not None:
            import uuid
            candidates = candidates.filter(pk__gt=uuid.UUID(str(after_id)))
        candidates = candidates.order_by("pk")[:DEV_ORPHAN_BATCH_SIZE]
        for user in candidates:
            scanned += 1
            last_id = str(user.pk)
            if EmailAddress.objects.filter(user=user, verified=True).exists():
                continue
            if _has_current_owned_session(user, now):
                continue
            if not user.domain_id:
                raise RuntimeError("Incomplete synthetic domain link requires investigation, not blind erasure")
            eligible += 1
            if not dry_run:
                erase_identity(user, policy=DEV_ORPHAN_POLICY)
                count += 1
    return {"dry_run": dry_run, "scanned_candidates": scanned, "eligible_orphaned_accounts": eligible,
            "purged_unverified_accounts": count, "eligible_expired_sessions": expired_sessions,
            "eligible_expired_rate_counters": expired_counters, "policy": DEV_ORPHAN_POLICY,
            "next_after_id": last_id if scanned == DEV_ORPHAN_BATCH_SIZE else None,
            "production_retention_approved": False}
