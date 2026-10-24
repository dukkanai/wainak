# Identity sandbox — test harness only

Read `../contracts/identity-api.md` and
`../docs/phase2-identity-architecture.md` before integration.

There is intentionally no public server command, `.env`, production secret,
real SMTP adapter, existing-database DSN flag or mobile auth build in this slice.
`wainak_identity.bootstrap.configure` accepts the owned disposable harness's
private Python connection factory. The account namespace is `@example.invalid`.

## Reproducible development checks

Use an isolated Python3.14 Linux x86_64 virtual environment and install the
hash-locked wheels from the official registry:

```sh
python -m pip install --only-binary=:all: --require-hashes -r backend/requirements-identity.lock
python -m pip check
PYTHONPATH=backend python backend/integration/run_identity.py --run-disposable-identity
```

The existing pinned official PostgreSQL image must already be present. The
harness never pulls it, publishes a host port or connects to the project DB.
It creates one labeled192MiB/network-none container and owned volume, generates
temporary synthetic DB credentials, and checks ownership before cleanup.
Authentication keys remain only in the Python harness parent's RAM; the temporary
DB password file is inside a private temporary directory removed at exit.

The unchanged phase1 PostgreSQL14-case suite runs first. Only afterward does the
identity class apply its migrations to this new disposable database. Tests use
real default-cost Argon2, sequential account operations, and limited database-only
counter concurrency. No Flutter compiler or service-memory adjustment is needed.
The HTTP durability case binds only127.0.0.1 on an ephemeral port, suppresses logs,
stops each exact owned process before restarting its own DB, and validates cleanup.

For independent QA, `run_identity.main(extra_test_factory=..., argv=[...])` accepts
a reviewed local Python callable `(connect, restart, temporary, keys)` returning
additional unittest cases. This is not a network API or a secret-exporting CLI.
The additional cases run after the built-in class's lazy migration setup. Never
print the factory's connection information, keys, session tokens or fake mailbox.

Schema artifacts can be checked without connecting to PostgreSQL by calling
`configure(schema_artifact_only=True)` and Django's `makemigrations --check --dry-run`.
That configuration uses SQLite `:memory:` only for model-state inspection; it
explicitly disables the HTTP application and is **not** a persistence test.

## Release boundaries

Passing these checks proves only this synthetic slice on the exact tested source.
The application is still missing production secret provisioning, HTTPS/provider
setup, durable mail retries, scalable domain SQL, tuned anti-abuse/monitoring,
approved retention/backups, mobile secure token storage/auth UI, device testing,
payments, chat/media encryption and moderation evidence upload. Main remains
unchanged. No merge, publication or store/security-readiness claim follows.

Runtime result inventory is recorded in the phase2 architecture/QA report after
the final frozen commit is tested; draft source alone is not passing evidence.
