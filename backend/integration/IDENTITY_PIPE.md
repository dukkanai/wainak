# Private mobile identity fixture (development only)

This additive test fixture preserves `93dd42f` application routes and auth behavior.
It is **not** a deployable server, email API, credential provider, or public mailbox.
No persistent application key, real email, provider account, or live DB is accepted.

## Ownership and startup

The Dart test starts Python **inside the running test body, after compilation**:

- executable: `/home/chatbot/wainak-dev/auth-tools-phase2/venv/bin/python`
- script: `/home/chatbot/wainak-dev/backend-auth-phase2/backend/integration/serve_identity_fixture.py`
- arguments: `--run-disposable-identity-fixture` (optional `--lifetime-seconds 180`, range2–300)
- normal `Process.start`, anonymous stdin/stdout pipes; never `inheritStdio`, a shell,
  stdout forwarding, files, URLs, dart-defines, or environment variables for secrets.
- environment allowlist only: project HOME, `/usr/bin:/bin` PATH, `LANG=C.UTF-8`,
  `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`; inheritParentEnvironment=false.
  Do not inherit SMTP, DB, proxy, analytics, or unrelated service credentials.
- no server/DB before the explicit opt-in and anonymous-PIPE checks pass.

The existing reviewed `run_postgres` creates its own pinned-image DB, with no host
ports, network none, memory192MiB, ephemeral credential in its private temporary
secret file, and exact label/name cleanup. Application keys stay in Python memory.
Its14 legacy PG cases run first, then lazy Django migrations in **that new DB only**.
The fixture refuses readiness if those prerequisites fail. It erases the legacy
synthetic domain rows before the client journey. Startup can take30–90s; allow120s.

WSGI binds only `127.0.0.1:0`. It runs in an owned Python thread in the same process
as the on-commit fake OUTBOX; it is **not** a fresh-process restart test. Framework
signup/verification/password hashing/session checks and the PostgreSQL domain bridge
are real. No simulated authentication, admin/expiry endpoint, rate-limit bypass,
activation, or payment is added. Real SMTP remains disabled.

## Private protocol v1

UTF-8 newline JSON, ≤4096bytes/line, ≤256commands, integer request id0–1,000,000.
Reject duplicate keys, unknown fields/commands, nonfinite values, non-fixture emails,
unknown purposes, negative cursors, arbitrary destinations, and malformed input.
Only the test process consumes these pipes; **never print a whole protocol response**.

Startup metadata:

```json
{"type":"ready","mode":"identity_fixture","private_mailbox":true,"base_url":"http://127.0.0.1:<ephemeral>","lifetime_seconds":180}
```

Validate the URL before use: http, exact host127.0.0.1, explicit port, no userinfo,
path, query, or fragment. Disable proxies and reject redirects in the HTTP client.
For each normal account/signup flow, choose a fresh random `@example.invalid` email
and strong synthetic password in RAM. Never include generated values in assertions
that might print actual/expected operands. Do not log HTTP bodies or headers.

Mail request (only after the real HTTP operation finishes):

```json
{"id":1,"op":"mail","email":"fixture@example.invalid","purpose":"verify","after":0}
```

Response is `{id,ok:true,sequence:N,value:<PRIVATE CODE>}` or
`{id,ok:false,error:"not_ready"}`. `sequence` is a process-local OUTBOX index, not a
token. It returns the latest matching **committed** event strictly after `after`.
Use the returned sequence for a later resend; do not reuse an old code accidentally.
`purpose:"reset"` extracts only the opaque key from the synthetic fixed reset URL;
it never follows the URL. There is no arbitrary mailbox/body/recipient enumeration
command. Email is strictly canonical ASCII lowercase fixture format.

Shutdown command `{"id":2,"op":"shutdown"}` yields `{id,ok:true,stopping:true}`.
After HTTP shutdown and the PG harness's verified container/volume/tempdir removal:
`{type:"closed",cleanup_verified:true,checks_passed:true,reason:"shutdown"}`, exit0.
A successful journey requires **both** this terminal acknowledgement and exit0.
Do not infer cleanup from the first stopping acknowledgement.

EOF, SIGTERM/SIGINT, lifetime timeout, idle60s, malformed/oversize input, command
budget, and output/broken-pipe timeout all unwind the same owned cleanup. Graceful
abnormal exits are2; readable terminal reason can be eof/terminated/lifetime_timeout/
idle_timeout/fixture_failed. Cleanup false is a blocker, not a successful test.
No secret-bearing exception traceback, Docker output, HTTP access log, or body is
forwarded; child stderr is empty normally, fixed preflight diagnostic on rejection.

On test failure, close stdin and drain/discard private stdout/stderr while awaiting
exit. Allow120s for bounded startup/owned Docker cleanup; if necessary send TERM to
**this child only**, not a process group. Never claim SIGKILL/host failure cleans DBs;
force termination requires an explicit independent artifact audit. No unrelated
process/container/volume can be removed. A closed/broken stdout cannot acknowledge
cleanup; independently audit labels/tempdirs in that negative test.

The WSGI accepted socket is bounded and explicitly interrupted during shutdown;
SQL statements have the existing20s limit. The HTTP thread closes its own thread-local
Django connections. Idle/lifetime starts at readiness, not during prerequisite tests.
Parent Dart must enforce its own startup deadline and cleanup in finally/tearDown.
No Dart code should expose fixture paths or PIPE capability in an application build.

## Evidence and limits

Run protocol-only tests (no Docker/framework):
`python -m unittest discover -s backend/tests -p test_identity_fixture_protocol.py -v`

Run author private client probes sequentially, as chatbot, only with the compiler/DB
window reserved:
`<venv-python> backend/integration/probe_identity_fixture.py --run-disposable-fixture-probes`

Probes cover real signup→pending→PIPE code→framework verify→HTTP profile, independent
sessions/global revoke→401, login/reauth/delete→401; shutdown, EOF, TERM with an
unfinished HTTP request, lifetime expiry, and broken output pipe. All protocol/mail
values remain in RAM. Independent resource audit is required after the probes.

This is not mobile widget/browser acceptance by itself. UI/QA must pin both commits
and run their actual widget journey. Backend expiry/races/restarts have separate
identity evidence; this fixture does not simulate expiry or prove production key
provisioning, TLS, email delivery, app secure storage, accessibility, or store approval.

### Author run, 2026-10-24 UTC

-11 protocol/control tests PASS locally; complete server suite is re-run on the
 additive commit below, not inferred from the older57-test result.
- Five disposable probes PASS, job `e9fa1827-28f0-4b8e-9f7a-f01774f654d7`,
 09:21:09.737–09:23:45.756, exit0. Each fixture separately passed14 unchanged PG
 prerequisite cases; these are repeated prerequisites, not70 new unique tests.
- Normal journey exercised real HTTP signup/pending verification, private PIPE mail,
 framework verification, profile update, second login, global revocation/401,
 re-login/reauthentication, physical identity deletion and old-session401.
- EOF, TERM during unfinished HTTP headers,2s lifetime expiry, and deliberately
 broken protocol stdout all exited and restored the pre-run artifact inventory.
- Separate audit job `229490ab-daaf-4978-8a88-29416a68acf1` at09:25:00:
 zero labeled containers/volumes and zero owned `/tmp/wainak-postgres-test-*` dirs;
 existing `wainak-db-1` running/healthy. Owner memory576503808/max1073741824 bytes.
 No resource-limit/service/configuration change was performed by these tests.
- QA reviewed isolation and requested the per-command batch deadline regression;
 independent exact-commit runtime confirmation is separate, not claimed here.
- Flutter widget compilation was blocked by its384MiB frontend heap before any
 auth widget assertion. These Python probes do **not** prove mobile auth UI E2E.
