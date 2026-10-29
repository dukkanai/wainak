"""Explicit migration artifact for NEW disposable synthetic databases only.

No migration runs at import, service construction, or ordinary API startup.
Production migrations, roles, retention and deployment remain out of scope.
"""

import re

SCHEMA = "wainak_phase1_dev"
SCHEMA_VERSION = 1
ADVISORY_LOCK_ID = 782343061

MIGRATION_001 = r"""
CREATE SCHEMA wainak_phase1_dev;
SET LOCAL search_path = wainak_phase1_dev, pg_catalog;

CREATE TABLE schema_metadata (
    singleton boolean PRIMARY KEY CHECK (singleton),
    version integer NOT NULL CHECK (version = 1),
    mode text NOT NULL CHECK (mode = 'synthetic_development_only')
);
INSERT INTO schema_metadata VALUES (true, 1, 'synthetic_development_only');

CREATE TABLE accounts (
    id text PRIMARY KEY CHECK (id ~ '^usr_[0-9a-f]{32}$'),
    deleted boolean NOT NULL,
    data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    CHECK (data ? 'id' AND data->>'id' IS NOT NULL AND data->>'id' = id),
    CHECK (data ? 'deleted' AND jsonb_typeof(data->'deleted') = 'boolean'
           AND (data->>'deleted')::boolean = deleted),
    CHECK (deleted OR (data->>'email' IS NOT NULL
           AND data->>'email' ~ '^[a-z0-9._-]{1,64}@example[.]invalid$'))
);
CREATE UNIQUE INDEX active_synthetic_email ON accounts ((data->>'email')) WHERE NOT deleted;

CREATE TABLE consents (
    account_id text PRIMARY KEY REFERENCES accounts(id),
    terms_version text NOT NULL CHECK (terms_version = 'dev-2026-10-24'),
    privacy_version text NOT NULL CHECK (privacy_version = 'dev-2026-10-24'),
    accepted_at timestamptz NOT NULL
);

CREATE TABLE sessions (
    token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    account_id text NOT NULL REFERENCES accounts(id)
);

CREATE TABLE relationships (
    id text PRIMARY KEY CHECK (id ~ '^rel_[0-9a-f]{32}$'),
    initiator_id text NOT NULL REFERENCES accounts(id),
    recipient_id text NOT NULL REFERENCES accounts(id),
    status text NOT NULL CHECK (status IN ('requested','accepted_pending_activation','active_cards',
                                          'exclusive_cards','declined','cancelled','ended','blocked')),
    exclusive_requested_by text REFERENCES accounts(id),
    CHECK (initiator_id <> recipient_id),
    CHECK (exclusive_requested_by IS NULL OR
           (status = 'active_cards' AND exclusive_requested_by IN (initiator_id, recipient_id)))
);
CREATE UNIQUE INDEX one_relationship_per_pair
    ON relationships (LEAST(initiator_id, recipient_id), GREATEST(initiator_id, recipient_id));

CREATE TABLE exclusive_claims (
    account_id text PRIMARY KEY REFERENCES accounts(id),
    relationship_id text NOT NULL REFERENCES relationships(id)
);
CREATE INDEX exclusive_relationship_members ON exclusive_claims(relationship_id);

CREATE TABLE safety_blocks (
    blocker_id text NOT NULL REFERENCES accounts(id),
    target_id text NOT NULL REFERENCES accounts(id),
    PRIMARY KEY (blocker_id, target_id),
    CHECK (blocker_id <> target_id)
);

CREATE TABLE reports (
    id text PRIMARY KEY CHECK (id ~ '^rpt_[0-9a-f]{32}$'),
    reporter_id text NOT NULL REFERENCES accounts(id),
    target_id text NOT NULL REFERENCES accounts(id),
    relationship_id text REFERENCES relationships(id),
    category text NOT NULL CHECK (category IN ('harassment','threat','impersonation','child_safety','other_safety')),
    status text NOT NULL CHECK (status = 'recorded_development_only'),
    evidence_uploaded boolean NOT NULL CHECK (evidence_uploaded = false),
    CHECK (reporter_id <> target_id)
);

CREATE TABLE request_idempotency (
    actor_id text NOT NULL REFERENCES accounts(id),
    request_key text NOT NULL CHECK (request_key ~ '^[A-Za-z0-9_-]{8,64}$'),
    target_id text NOT NULL REFERENCES accounts(id),
    relationship_id text NOT NULL REFERENCES relationships(id),
    PRIMARY KEY(actor_id, request_key)
);

-- A deferred check validates the final transaction state, not intermediate rows.
-- It complements (rather than replaces) the one-claim-per-account primary key.
CREATE FUNCTION validate_exclusive_claims() RETURNS trigger LANGUAGE plpgsql
SET search_path = wainak_phase1_dev, pg_catalog AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM exclusive_claims c JOIN relationships r ON r.id=c.relationship_id
        JOIN accounts a ON a.id=c.account_id
        WHERE r.status <> 'exclusive_cards' OR c.account_id NOT IN (r.initiator_id,r.recipient_id)
           OR a.deleted
    ) OR EXISTS (
        SELECT 1 FROM relationships r WHERE r.status='exclusive_cards'
        AND (SELECT count(*) FROM exclusive_claims c WHERE c.relationship_id=r.id) <> 2
    ) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='invalid exclusive claims';
    END IF;
    RETURN NULL;
END
$$;
CREATE CONSTRAINT TRIGGER consistent_exclusive_members
    AFTER INSERT OR UPDATE OR DELETE ON exclusive_claims DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION validate_exclusive_claims();
CREATE CONSTRAINT TRIGGER consistent_exclusive_relationship
    AFTER INSERT OR UPDATE OR DELETE ON relationships DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION validate_exclusive_claims();
CREATE CONSTRAINT TRIGGER consistent_exclusive_account
    AFTER INSERT OR UPDATE OR DELETE ON accounts DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION validate_exclusive_claims();
"""


class RepositoryConfigurationError(RuntimeError):
    pass


def require_disposable_database(connection):
    name = connection.execute("SELECT current_database()").fetchone()[0]
    if not isinstance(name, str) or not re.fullmatch(r"wainek_test_[0-9a-f]{12}", name):
        raise RepositoryConfigurationError("Refusing a database outside the uniquely named synthetic test namespace.")


def apply_initial_migration(connect, *, allow_new_disposable_database=False):
    if allow_new_disposable_database is not True:
        raise RepositoryConfigurationError("Explicit permission for a NEW disposable test database is required.")
    with connect() as connection:
        with connection.transaction():
            require_disposable_database(connection)
            connection.execute("SET LOCAL lock_timeout = '5s'")
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_ID,))
            # Refuse any existing user schema, including a previous migration:
            # a failed setup must be inspected, not overwritten or auto-upgraded.
            existing = connection.execute("""SELECT 1 FROM pg_namespace
                WHERE nspname NOT IN ('public','information_schema') AND nspname NOT LIKE 'pg_%'
                UNION ALL SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public'
                UNION ALL SELECT 1 FROM pg_proc WHERE pronamespace='public'::regnamespace
                UNION ALL SELECT 1 FROM pg_type WHERE typnamespace='public'::regnamespace
                LIMIT 1""").fetchone()
            if existing:
                raise RepositoryConfigurationError("Initial migration requires an empty database; no existing schema is changed.")
            connection.execute(MIGRATION_001)
