# Actual Flutter → HTTP → PostgreSQL chain

This additive acceptance harness uses the existing disposable PostgreSQL safeguards.
It does not publish an application, enable real accounts, or connect to the existing
Wainak database. Execute only as the project owner, with one Flutter build at a time.

```sh
/path/to/owned/psycopg-venv/bin/python \
  backend/integration/run_flutter_postgres.py --run-flutter-postgres \
  --mobile-root /path/to/owned/mobile-worktree/apps/mobile \
  --tools-root /path/to/owned/project-mobile-tools
```

`tools-root` must already contain `flutter/`, `home/` and `pub-cache/`, with an
accessible cached native Flutter test engine. The harness neither installs an SDK nor
changes permissions, cgroup limits, system services, or global settings. Optional
`DART_VM_OPTIONS` and `FLUTTER_TOOL_ARGS` from the explicit invoking test environment
are forwarded only if they contain the allowed heap-size flags; the owner connector's
remaining environment is not. The current project tool flags are
`FLUTTER_TOOL_ARGS="--old_gen_heap_size=384 --new_gen_semi_max_size=16"`.

The harness first runs the PostgreSQL regression suite. It then clears only the
newly created synthetic database fixture and starts a **separate Python WSGI process**
on `127.0.0.1` with an OS-assigned ephemeral port. The WSGI application injects the
PostgreSQL repository. Its private database connection factory/password remains in
Python memory; Flutter receives no DSN, DB credential or database socket path.

Flutter runs exactly:

```sh
flutter test --no-pub --concurrency=1 --reporter=expanded \
  test/native_backend_integration_test.dart
```

It receives only the loopback `WAINAK_TEST_BASE_URL` and private
`WAINAK_TEST_CONTROL_DIR` in addition to the constrained SDK environment. A client
may retain its own synthetic API session token in memory, as a real client must;
no token is put in a control file, command argument or persistent fixture.

Independent QA may select `--test-file test/qa_connected_postgres_test.dart` inside
its own isolated mobile copy. Only an owned regular `test/*_test.dart` path is accepted;
absolute paths, traversal and symlink escapes are rejected. This permits a real
connected widget test without modifying the UI worker's source or executing a shell
string. The selected file path/hash is included in the test result.

## Two restart checkpoints; no administrative HTTP endpoint

The reviewed Dart test implements these exact non-secret control files:

1. After activating the mutually accepted card relationship, it writes
   `active.ready` containing exactly `ready`, then waits for `active.resumed`.
2. Python validates the marker's owner, regular-file type, size, inode and content,
   stops the first WSGI process, restarts **only its disposable DB container**, and
   starts a new WSGI process on the same loopback port. After health verification it
   writes `active.resumed` containing exactly `resumed`.
3. Dart uses its existing in-memory sessions to reread accounts, relationship and
   available cards, then blocks/reports and writes `blocked.ready`.
4. Python repeats the DB/application-process restart, then creates `blocked.resumed`.
   Dart verifies persisted blocking, hidden peer/no card access, continued reporting,
   and account deletion without silently re-registering or accepting a new session.

The markers contain no names, account IDs, timestamps, tokens or content. There is
no restart/administration route in the product API. Both markers are mandatory;
Flutter exiting successfully without them is a failure, not a skipped pass.

## Failure and cleanup

The Flutter child runs in its own process group. On failure/timeout the harness
terminates only that owned process group, stops its own WSGI process, and returns to
the enclosing database harness's ownership-checked container/volume/temp-directory
cleanup. Symlinks, FIFOs, oversized/replaced markers and attempts to overwrite a
resume marker are rejected. Failure output is bounded and filters bearer/long opaque
values; the DB credential never enters the child environment or captured output.

Successful output records both repository commits/dirty flags, the Dart test content
hash, two DB restarts, three distinct WSGI processes, and the synthetic-only scope.
Final acceptance must use clean committed source and independent QA for those exact
bytes. A local draft pass is useful implementation evidence but not a production or
mobile-store release gate.

This verifies the real native Flutter test runner, typed client/repository, loopback
HTTP serialization, domain authorization and disposable PostgreSQL persistence in
one chain. It is **not** a physical Android/iOS device test, a web-origin test, real
email/auth/payment, cryptography, a load test or migration of the existing service.

## Recorded development run (2026-10-24)

The initial native chain completed at 05:49:50 UTC: **15/15 tests passed in
32.546 seconds** (14 PostgreSQL regressions plus the actual Flutter HTTP journey),
using PostgreSQL 17.11 / psycopg 3.3.6. Both `active` and `blocked` checkpoints
completed, with two database restarts and three distinct application processes.
The temporary container, volume and secret/socket/control directory were verified
removed. The UI source was clean commit `863b4d5c5df4d7be24b4b3a00e9ac5e6a8f83684`;
the selected native test SHA-256 was
`a52d87533ea7ba2875756575b2a17bd42548c2a035f2b2e2bc25ffe314056133`.

That first run used a backend draft over `944e8b9`; it is implementation evidence,
not by itself final-commit acceptance. Independent QA and a rerun must bind results
to the resulting additive backend commit. A connected widget test is a separate
result; the native repository journey does not assert UI taps.
