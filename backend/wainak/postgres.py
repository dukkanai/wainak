"""Optional PostgreSQL repository for disposable synthetic databases only.

This correctness-first adapter serializes the small entire development store.
It is durable across service/process restarts, but is not a scalable production
query layer, production role design, or authorization boundary for arbitrary SQL.
"""

import copy
from contextlib import contextmanager

from .migrations import ADVISORY_LOCK_ID, SCHEMA_VERSION, RepositoryConfigurationError, require_disposable_database
from .repository import State


class PostgresRepository:
    durable = True

    def __init__(self, connect, *, enable_synthetic_persistence=False):
        if enable_synthetic_persistence is not True:
            raise RepositoryConfigurationError("Synthetic persistence must be explicitly enabled.")
        # Driver imported only for this optional adapter, not memory-mode tests.
        from psycopg.types.json import Jsonb
        self.connect = connect
        self.Jsonb = Jsonb

    @contextmanager
    def transaction(self):
        with self.connect() as connection:
            with connection.transaction():
                require_disposable_database(connection)
                connection.execute("SET LOCAL search_path = wainak_phase1_dev, pg_catalog")
                connection.execute("SET LOCAL statement_timeout = '10s'")
                connection.execute("SET LOCAL lock_timeout = '5s'")
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_ID,))
                marker = connection.execute("SELECT version, mode FROM schema_metadata WHERE singleton=true").fetchone()
                if marker != (SCHEMA_VERSION, "synthetic_development_only"):
                    raise RepositoryConfigurationError("Unsupported or missing synthetic schema marker.")
                state = self._load(connection)
                before = copy.deepcopy(state)
                yield state
                if state != before:
                    self._save(connection, state)

    def _load(self, connection):
        state = State()
        for identifier, payload in connection.execute("SELECT id, data FROM accounts"):
            state.accounts[identifier] = payload
        for actor, terms, privacy, accepted in connection.execute("SELECT account_id, terms_version, privacy_version, accepted_at FROM consents"):
            state.accounts[actor]["consents"] = {"terms_version": terms, "privacy_version": privacy,
                                                  "accepted_at": accepted.isoformat()}
        state.sessions = dict(connection.execute("SELECT token_hash, account_id FROM sessions"))
        for identifier, initiator, recipient, status, proposer in connection.execute(
                "SELECT id,initiator_id,recipient_id,status,exclusive_requested_by FROM relationships"):
            state.relationships[identifier] = {"id": identifier, "initiator_id": initiator,
                "recipient_id": recipient, "status": status, "exclusive_requested_by": proposer}
        for actor, rel in connection.execute("SELECT account_id,relationship_id FROM exclusive_claims"):
            state.accounts[actor]["exclusive_relationship_id"] = rel
        state.blocks = set(connection.execute("SELECT blocker_id,target_id FROM safety_blocks"))
        for identifier, reporter, target, rel, category, status, evidence in connection.execute(
                "SELECT id,reporter_id,target_id,relationship_id,category,status,evidence_uploaded FROM reports"):
            state.reports[identifier] = {"id": identifier, "reporter_id": reporter, "target_id": target,
                "relationship_id": rel, "category": category, "status": status, "evidence_uploaded": evidence}
        for actor, key, target, rel in connection.execute("SELECT actor_id,request_key,target_id,relationship_id FROM request_idempotency"):
            state.idempotency[(actor, key)] = (target, rel)
        return state

    def _save(self, connection, state):
        # Foreign-key order is explicit. The single advisory transaction lock is
        # held throughout load, domain validation and replacement. A failure in
        # any insert/constraint rolls the WHOLE transition back.
        for table in ("request_idempotency", "reports", "safety_blocks", "exclusive_claims", "sessions",
                      "consents", "relationships", "accounts"):
            connection.execute("DELETE FROM " + table)  # static internal allowlist, never input
        with connection.cursor() as cursor:
            account_rows, consent_rows, claims = [], [], []
            for actor, account in state.accounts.items():
                payload = copy.deepcopy(account)
                consent = payload.pop("consents", None)
                exclusive = payload.get("exclusive_relationship_id")
                payload["exclusive_relationship_id"] = None
                account_rows.append((actor, account["deleted"], self.Jsonb(payload)))
                if consent:
                    consent_rows.append((actor, consent["terms_version"], consent["privacy_version"], consent["accepted_at"]))
                if exclusive:
                    claims.append((actor, exclusive))
            cursor.executemany("INSERT INTO accounts(id,deleted,data) VALUES (%s,%s,%s)", account_rows)
            cursor.executemany("INSERT INTO consents(account_id,terms_version,privacy_version,accepted_at) VALUES (%s,%s,%s,%s)", consent_rows)
            cursor.executemany("INSERT INTO sessions(token_hash,account_id) VALUES (%s,%s)", list(state.sessions.items()))
            cursor.executemany("""INSERT INTO relationships(id,initiator_id,recipient_id,status,exclusive_requested_by)
                                  VALUES (%s,%s,%s,%s,%s)""",
                               [(r["id"],r["initiator_id"],r["recipient_id"],r["status"],r["exclusive_requested_by"])
                                for r in state.relationships.values()])
            cursor.executemany("INSERT INTO exclusive_claims(account_id,relationship_id) VALUES (%s,%s)", claims)
            cursor.executemany("INSERT INTO safety_blocks(blocker_id,target_id) VALUES (%s,%s)", list(state.blocks))
            cursor.executemany("""INSERT INTO reports(id,reporter_id,target_id,relationship_id,category,status,evidence_uploaded)
                                  VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                               [(r["id"],r["reporter_id"],r["target_id"],r["relationship_id"],r["category"],r["status"],r["evidence_uploaded"])
                                for r in state.reports.values()])
            cursor.executemany("INSERT INTO request_idempotency(actor_id,request_key,target_id,relationship_id) VALUES (%s,%s,%s,%s)",
                               [(actor,key,target,rel) for (actor,key),(target,rel) in state.idempotency.items()])
