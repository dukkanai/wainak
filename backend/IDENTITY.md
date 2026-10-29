# Identity sandbox — test harness only

Read `../contracts/identity-api.md` and
`../docs/phase2-identity-architecture.md` before integration.

There is intentionally no public server command, `.env`, production secret,
real SMTP adapter or existing-database DSN flag. The integrated native mobile
auth UI is now in `../apps/mobile`; it remains a synthetic development UI, not
a production account service. See `../docs/phase2-integration.md` for exact-source
integration gates and local-only main authorization.
`wainek_identity.bootstrap.configure` accepts the owned disposable harness's
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

The unchanged phase1 PostgreSQL14-case suite runs first. The identity class then
applies Django migrations in its lazy `setUpClass`, before its identity test cases.
The additive pending deletion/web cases run after that class, followed by any
independent QA hook. All migrations target only this new disposable database. Tests use
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
approved retention/backups, mobile secure token storage, device testing, payments,
chat/media encryption and moderation evidence upload. A tested native development
auth UI does not close those production gates. A local main move is separately
authorized only after the exact integration checks pass; no remote publication,
deployment or store/security-readiness claim follows.

Runtime result inventory is recorded in the phase2 architecture/QA report after
the final frozen commit is tested; draft source alone is not passing evidence.

For the additive inline script regression (mock DOM/network, not a browser),
use a verified Node24 runtime. Earlier backend-only checks used local Node24.19.0;
the integration checkpoint may use the separately authorized project-scoped server
runtime, with its official archive/checksum recorded alongside the exact test report.
Compare template/test Git blob hashes when using a separate verification workspace:

```sh
node backend/tests/test_web_deletion_script.mjs
```

See `../docs/phase2-deletion-web.md` for the pending-account ownership contract,
explicit dry-run/apply orphan utility and internal keyset continuation. No cleanup
job is scheduled automatically and its24-hour rule is synthetic-only.
