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
    @staticmethod
    def current_consents(account):
        consent = account.get("consents") or {}
        return (consent.get("terms_version") == POLICY_VERSION
                and consent.get("privacy_version") == POLICY_VERSION
                and bool(consent.get("accepted_at")))

    def _eligible(self, account, allow_exclusive=None):
        return self.current_consents(account) and super()._eligible(account, allow_exclusive)

    def _view_relationship(self, actor, rel):
        result = super()._view_relationship(actor, rel)
        peer = rel["recipient_id"] if actor == rel["initiator_id"] else rel["initiator_id"]
        if not self.current_consents(self.accounts[peer]):
            result["peer"] = None
        return result

    @locked
    def require_current_consents(self, actor):
        if not self.current_consents(self._account(actor)):
            fail(403, "consent_required", "Current policy acceptance is required; re-consent UI is not implemented.")


def service():
    return IdentityDomainService(repository=SharedDomainRepository())
