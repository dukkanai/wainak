"""Identity/domain use ONE Django-owned psycopg connection and transaction.

The phase1 correctness-first snapshot domain adapter remains deliberately small-
scale. No second connection, commit, production DB role or scalable-query claim.
"""
import copy
import json
from contextlib import contextmanager
from django.db import connection, transaction
from wainak.domain import DevelopmentService, POLICY_VERSION, locked, fail
from wainak.migrations import ADVISORY_LOCK_ID, SCHEMA_VERSION, require_disposable_database
from wainak.postgres import PostgresRepository


class _JsonRows:
    """Cursor-local JSON decoder, without mutating Django's own adapters."""
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, parameters=None):
        from psycopg.types.json import set_json_loads
        with self.raw.cursor() as cursor:
            set_json_loads(json.loads, cursor)
            cursor.execute(sql, parameters)
            return cursor.fetchall()


class SharedDomainRepository(PostgresRepository):
    def __init__(self):
        super().__init__(lambda: None, enable_synthetic_persistence=True)

    @contextmanager
    def transaction(self):
        if not connection.in_atomic_block:
            raise RuntimeError("Identity domain calls require the outer auth transaction")
        with transaction.atomic():
            connection.ensure_connection()
            raw = connection.connection
            require_disposable_database(raw)
            raw.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_ID,))
            old_path = raw.execute("SHOW search_path").fetchone()[0]
            raw.execute("SET LOCAL search_path = wainak_phase1_dev, pg_catalog")
            try:
                marker = raw.execute("SELECT version,mode FROM schema_metadata WHERE singleton=true").fetchone()
                if marker != (SCHEMA_VERSION, "synthetic_development_only"):
                    raise RuntimeError("Synthetic domain schema is required")
                state = self._load(_JsonRows(raw))
                before = copy.deepcopy(state)
                yield state
                if state != before:
                    self._save(raw, state)
            finally:
                # set_config binds data, not an interpolated SQL identifier.
                from psycopg.pq import TransactionStatus
                if raw.info.transaction_status != TransactionStatus.INERROR:
                    raw.execute("SELECT set_config('search_path', %s, true)", (old_path,))


class IdentityDomainService(DevelopmentService):
    def __init__(self, *args, verified_domain_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        # Request-local snapshot taken under the outer auth transaction/lock,
        # before the domain adapter narrows PostgreSQL's search_path.
        self.verified_domain_ids = frozenset(verified_domain_ids)

    @staticmethod
    def current_consents(account):
        consent = account.get("consents") or {}
        return (consent.get("terms_version") == POLICY_VERSION
                and consent.get("privacy_version") == POLICY_VERSION
                and bool(consent.get("accepted_at")))

    def _eligible(self, account, allow_exclusive=None):
        return (account["id"] in self.verified_domain_ids and self.current_consents(account)
                and super()._eligible(account, allow_exclusive))

    def _may_project_peer(self, account):
        return (not account["deleted"] and account.get("profile") is not None
                and account["id"] in self.verified_domain_ids
                and account.get("dev_email_verified") is True
                and self.current_consents(account) and self._age(account) >= 18)

    def _view_relationship(self, actor, rel):
        result = super()._view_relationship(actor, rel)
        peer = rel["recipient_id"] if actor == rel["initiator_id"] else rel["initiator_id"]
        if not self._may_project_peer(self.accounts[peer]):
            result["peer"] = None
        incoming = actor == rel["recipient_id"]
        result["direction"] = "incoming" if incoming else "outgoing"
        actions = []
        if rel["status"] == "requested":
            if incoming:
                if self._discoverable(rel["initiator_id"], rel["recipient_id"]):
                    actions.append("accept")
                actions.append("decline")
            else:
                actions.append("cancel")
        if rel["status"] in {"accepted_pending_activation", "active_cards", "exclusive_cards"}:
            actions.append("end")
        if self._can_address(actor, peer):
            actions.extend(("block", "report"))
        # Hints are recomputed, not persisted or accepted as authority by routes.
        result["available_actions"] = actions
        return result

    @locked
    def require_current_consents(self, actor):
        if not self.current_consents(self._account(actor)):
            fail(403, "consent_required", "Current policy acceptance is required; re-consent UI is not implemented.")


def service():
    from django.db.models import F
    from allauth.account.models import EmailAddress
    if not connection.in_atomic_block:
        raise RuntimeError("Identity service requires the outer auth transaction")
    verified = EmailAddress.objects.filter(verified=True, user__is_active=True,
        email__iexact=F("user__email")).exclude(user__domain_id__isnull=True).values_list("user__domain_id", flat=True)
    return IdentityDomainService(repository=SharedDomainRepository(), verified_domain_ids=tuple(verified))
