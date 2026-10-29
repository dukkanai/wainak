# Disposable PostgreSQL integration tests

This is an **opt-in isolated verification harness**, not a deployment command.
Default unit/API tests still need no external dependency or service.

## Requirements and repeatable command

- Linux with existing Docker access and Python 3.13+ for this pinned test environment.
- Existing `libpq` (the server already has `psql`); no system package is installed.
- The already-present official image from the project's Compose configuration:
  `postgres:17-alpine@sha256:eee6c6e1b0894fa4fe0075eb054af9fd1cf39a35321c2d4110626cfe506411fb`.
  The harness uses `--pull never`; missing image is a blocker, not an implicit pull.
- A separate virtual environment with `psycopg==3.3.6`, official pure-Python wheel
  pinned by SHA-256 in `backend/requirements-postgres.txt`. This optional adapter
  follows the [official Psycopg installation documentation](https://www.psycopg.org/psycopg3/docs/basic/install.html).
  Pure mode uses existing host `libpq`; it does not bundle a different database client.

From the repository root, using an isolated venv you own:

```sh
python3 -m venv /your/private/temporary/venv
/your/private/temporary/venv/bin/python -m pip install \
  --disable-pip-version-check --no-cache-dir --only-binary=:all: --no-deps \
  --require-hashes --index-url https://pypi.org/simple \
  -r backend/requirements-postgres.txt
/your/private/temporary/venv/bin/python \
  backend/integration/run_postgres.py --run-disposable-postgres
```

Do not run this while another resource-heavy build needs the same host. The database
is limited to 192 MiB, half a CPU, 100 PIDs and 32 MiB shared memory. No host port is
published, `--network none` forbids network access, and `listen_addresses` is empty.
Python connects using a Unix socket inside a newly created mode-0700 temporary root.

## Isolation and cleanup

The harness generates a random `wainek-pgtest-<12 hex>` container and named volume,
and database `wainek_test_<12 hex>`. It refuses an existing generated name. Both Docker
resources carry the exact unique ownership label, checked before cleanup. The secret
is generated for this synthetic test, written mode 0600 only inside its private temp
root, and never placed in argv, repository files or printed output. No persistent
credential or application service is created. An isolated dev-tool venv is not a
credential and can be removed separately by its creator after review.

Cleanup removes only those newly created matching resources and verifies their
absence. A Docker inspection error is not treated as absence. The temporary directory
including the secret/socket is removed and its absence checked. If a cleanup or
ownership check fails, do not claim success or delete an unrelated resource; inspect
the exact failed artifact with the owner connector and report the blocker.

No input argument/environment DSN is accepted. The adapter and initial migration
also independently reject database names outside `wainek_test_[0-9a-f]{12}`. The
migration requires an explicit opt-in and a new empty database; it refuses an existing
user schema instead of overwriting or silently upgrading it. Schema markers further
restrict the adapter to `synthetic_development_only` version 1. This defense-in-depth
does not authorize pointing tools at an existing DB bearing a similar name.

## What the adapter persists

`Repository.transaction()` yields a consistent domain state and commits or rolls
back as one unit. The default memory implementation is copy-on-write. The optional
PostgreSQL implementation persists accounts, separate policy consents, hashed session
tokens, relationships, exclusive claims, directional safety blocks, metadata reports
and actor-scoped request idempotency. It has no message/evidence/media content table.

It holds a PostgreSQL transaction advisory lock across load, domain checks and save.
The first adapter deliberately replaces the small snapshot inside the same transaction.
This avoids a stale-state lost update across independent processes and makes rollback
testable, but serializes all work and is **not a scalable production query layer**.
It does not bypass transaction semantics by trusting a Python lock alone.

Database constraints include unique unordered relationship pairs, unique actor/request
keys, one exclusive claim per account, foreign keys, restricted enums and consent
versions, and deferred final-state validation requiring exactly both relationship
participants for an exclusive state. The trigger pins its search path. All user/domain
values use driver parameters; dynamic table names are a fixed internal allowlist.

This is not row-level security, production role design, an administration API, or a
complete defense against a privileged user directly changing SQL. Application actor
authorization remains in the domain and is retested across repository instances.

## Coverage and limits

Fourteen real PostgreSQL tests cover:

1. Profile, consent, assessment, session, relation and report persistence across fresh
   services and an actual Docker container restart using the same temporary volume.
2. Full rollback after an invalid report is inserted after relationship replacement.
3. Competing exclusivity acceptances in two independent OS processes/connections.
4. Ten block-versus-activation races with independent repository connections.
5. Durable idempotency replay returning current blocked permissions.
6. Reporting after the target blocked first, without restoring discovery.
7. Database pair/claim uniqueness and rejection of a one-sided exclusive state.
8. Account deletion erasing private data/consents/reports and revoking the session.
9. Hashed rather than plaintext tokens and no dialogue-content columns.
10. SQL metacharacters remaining data via bound parameters.
11. Migration refusal for a preexisting schema and a non-test database.
12. Parallel identical request keys producing one durable relationship and receipt.
13. JSON-adapter injection accurately reporting durable storage while remaining
    explicitly synthetic; no socket/network server is started for this check.

Initial execution on 2026-10-24: PostgreSQL **17.11**, psycopg **3.3.6**, 12/12 passed
in **23.583 seconds**; container, volume and secret/socket temp directory cleanup
verified. This precommit run is implementation evidence; the final commit's repeated
and independent test results must be used for acceptance.

Not tested/implemented here: migration of the existing Wainek DB, multi-host failover,
load capacity, production credentials/roles/RLS, real auth/email/session expiry,
encrypted backups, production retention/deletion, payments, chat cryptography, mobile
network integration, or store acceptance. No such capability is implied by a passing
disposable database test.
