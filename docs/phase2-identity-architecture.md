# Phase 2 — synthetic identity sandbox (development only)

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](STATUS.md).

This branch extends, rather than replaces, the phase 1 development contracts.
It does **not** enable a public service or production authentication deployment.
Only an explicitly created disposable PostgreSQL database is accepted. Existing
project databases, Mailcow/SMTP, mobile build settings and main are untouched.

## Decision and provenance

- Django **5.2.18** (5.2 LTS) supplies password hashing/validation, authentication
  hashes, sessions, transactions and schema migrations.
- django-allauth **65.20.1**, app-only headless endpoints, supplies established
  email verification, password login/change and password-bound reset links.
- argon2-cffi **25.1.0** uses Django's real default Argon2 cost in these tests;
  expensive authentication races are bounded, not run with large fan-out.
- cryptography **50.0.2** supplies standard Fernet encryption, not custom crypto.
- psycopg **3.3.6** joins identity and phase 1 domain operations on the same
  Django-owned PostgreSQL connection.

`backend/requirements-identity.lock` pins every resolved wheel with SHA-256.
The development resolver used official PyPI/files.pythonhosted.org wheels only,
with `--only-binary` and `--require-hashes`; no remote installation script.
The observed interpreter is CPython **3.14.4**, Linux x86_64. These are recorded
tested versions, not a promise they will remain the latest or free of defects.

Primary framework references: [Django support](https://www.djangoproject.com/download/),
[passwords](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/),
[custom DB sessions](https://docs.djangoproject.com/en/5.2/topics/http/sessions/#extending-database-backed-session-engines),
[allauth session tokens](https://docs.allauth.org/en/latest/headless/token-strategies/session-tokens.html),
[rate limits](https://docs.allauth.org/en/dev/common/rate_limits.html).

## Boundary and transaction

The harness alone configures settings from a private Python connection factory.
The native API accepts loopback Host, no Origin/cookie/Bearer/query credentials, bounded
JSON and an explicit endpoint allowlist. Only synthetic `@example.invalid`
addresses are accepted, with lower-case normalization and database uniqueness.
The additive local deletion web exception is separately CSRF/Origin checked;
see `phase2-deletion-web.md`. Email verification proves access to a fake mailbox in this test, **not** identity,
age, marital status, suitability, device trust or E2EE-key ownership. Adult and
current-policy declarations remain server-validated; they are not document checks.

An outer Django transaction takes the auth advisory lock **before** session load.
Domain operations use the same raw psycopg connection and nested savepoints,
then the phase 1 domain lock. Registration, reset/revocation and deletion must not
commit identity/domain halves independently. Fake messages are delivered to a
process-local mailbox only after commit. A delivery failure after commit cannot
roll back registration, but never proves email ownership or grants access. A
durable provider outbox/retry is not implemented. No mailbox API/log/SMTP exists.

The domain snapshot adapter and global serialization deliberately favor
correctness for a tiny development fixture. They are **not** scalable production
SQL, a production DB-role design, or a performance/availability certification.
The identity subclass re-checks persisted policy versions; stale accounts cannot
appear or initiate protected matching actions. Re-consent UI is not implemented:
the API fails closed, while block/report/end/cancel/delete remain available.

## Sessions and tokens

The native app session token is a framework-generated bearer secret. Only its
SHA-256 digest (64 characters) is stored as the lookup key. The session payload
contains pending verification secrets, so signing alone would not conceal them:
Fernet encrypts a row-bound envelope to reject ciphertext swapping. Public
manager/encode shortcuts are disabled; sync and async backend paths use the same
digest semantics. allauth's session auth-hash validation is retained, rather than
trusting a cached user ID. Token values never go into test assertions/log output.

Valid reads touch the 30-minute idle window without extending the 24-hour
absolute lifetime. Login rotates the pending session. Reset/password change and
global logout revoke account-bound authenticated **and** pending sessions using
a purpose-separated HMAC fingerprint where a pending row has no user FK.
An unrelated actor's session must not be flushed by another account's reset.
Sensitive deletion requires authentication within five minutes or password reauth.

Verification codes are session-bound, limited to five attempts and ten minutes;
resends are bounded. Password reset uses framework **links**, not reset-by-code:
the inspected vendor code flow can verify email indirectly. The link flow uses
the password-bound token generator and must not silently verify an unverified
address or log in after reset. Email change, social login, MFA and administrator
accounts are outside this sandbox's allowlist.

Signing, encryption and rate-HMAC keys are generated only in parent-harness RAM.
Restart tests may preserve that RAM object: this is not evidence of production
KMS provisioning, durable key storage, rotation or disaster recovery. No persistent
key file, access credential, provider account or E2EE identity is created.

## Abuse, deletion and remaining gates

Rate buckets use one atomic PostgreSQL conditional upsert, not a process-local
cache. Subjects are purpose-separated HMACs; untrusted X-Forwarded-For is ignored.
IP/email/session/user policies are explicit development limits, not tuned abuse
protection. Expired counters/sessions have an explicit prune operation, not a
new scheduled service. Reports require actor + operation + key + payload receipts;
replay cannot create another report or restore purged data. No paid safety feature.

Deletion physically removes the synthetic auth user/password/email/session data
and domain profile/preferences/assessment/consents. Minimal relationship/account
tombstones, a deletion receipt, other accounts' idempotency receipt tombstones
and expiring rate counters can remain. Fake-mail snapshots in the test harness
(`OUTBOX` and Django mail.outbox), like caller memory, remain until fixture/process
teardown; database deletion does not claim to erase these captured test messages. Related
synthetic reports are purged, with no claim about a real moderation legal hold.
There is **no approved production retention duration** or connected backup/store
subscription/evidence service to erase. D25 uploads remain disabled. Email reset
does not recover conversations or encryption keys. Chat/media remain unimplemented.

Before a real deployment: independent security acceptance on the exact release,
production transaction/query design, secret provisioning, real email-provider
permission, HTTPS/native secure token storage, abuse controls/monitoring, retention
and deletion policy, backup behavior and platform/device testing are still needed.
No main merge, push, release, live migration or service publication is authorized
by this document.

## Verification evidence

Author candidate run `abcc2352-af64-49e9-ae0c-76e19c1f9fb4` ended
2026-10-24 08:11:28 UTC: **44/44 passed** (14 unchanged PostgreSQL regressions +
30 identity/security cases), in38.072s, PostgreSQL17.11/psycopg3.3.6.
It includes real loopback HTTP across three distinct WSGI processes and two
owned-database restarts, session durability then deletion/revocation durability.
No secrets cross argv/environment/output. Independent metadata inspection at
08:12:22 confirmed zero labeled test containers/volumes and zero temporary DB
secret/socket directories; owner memory.max remained1GiB with zero OOM events.

Earlier draft runs exposed and resolved: non-JSON500 errors on injected failure;
incorrect resend setting name (fail-closed409); and two test expectations (expired
pending flow410; the legacy schema itself rejects arbitrary policy strings).
No earlier failed run is being counted as passed. These are author observations
on candidate source, not independent approval. Independent QA must test the exact
frozen development commit; its separate `docs/reviews/phase2-auth-qa-results.md`
report identifies the final reviewed commit and any remaining limitations.
