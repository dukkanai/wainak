# Native identity sandbox — phases 2 and 3

Explicit, separate development mode. Phase1 `fake` and `api` remain available and do not silently change their authentication.

```
--dart-define=WAINAK_DEV_MODE=true
--dart-define=WAINAK_REPOSITORY=identity
--dart-define=WAINAK_API_BASE_URL=http://127.0.0.1:<owned-fixture-port>
```

This mode is native-only; web and invalid origins fail closed. A device's localhost is its own network namespace. No port forwarding, host exposure or device networking is configured here. This is not a deployable service or production login.

## Implemented boundaries

- Native X-Session-Token in RAM only; no Bearer, Cookie, Origin, CSRF-web marker or token URL. The Django/allauth fixture is authoritative.
- Registration with fixture email/password, adult/Muslim declarations and policy versions; 401 pending verification is distinct from authenticated access.
- Session-bound fake-email code verification/resend; login, session refresh, logout, global revocation, owned pending deletion and recent-password authenticated deletion.
- Account/profile/preferences hydration on login preserves existing gender, marital status, declared wives, marriage goal and unedited preference lists. New empty accounts use an explicitly described female/single sample; phase3 exposes a synthetic gender selector while preserving unedited values. Three adaptive reflection questions use backend option IDs.
- Profile and preference saves are separate writes, not a transaction. Partial failure names confirmed writes, retains the submitted draft, uses read-only reconciliation without automatic write retries, and never transfers a prior-session outcome to a new account.
- Auth transitions advance a generation; old pending replies cannot replace verified sessions. Delete/revoke confirmation is bound to the generation when opened, not whichever account is current later. Password/code controllers clear promptly, and disposed clients reject late responses.
- Busy forms exclude keyboard focus as well as pointer actions. Arabic/RTL, light/dark theme and existing48-target/16-helper tokens are retained. Layout tests exist but their execution must be checked in the evidence report.

Only ASCII canonical `@example.invalid` addresses are accepted. Do not reuse real passwords. Email proof is not legal identity, age assurance or device/key trust. No password-reset/change UI, secure token persistence, SMTP, social/MFA login, production keys or HTTPS deployment is implemented.

Phase3 adds authenticated candidates, introduction requests, recipient acceptance/decline and independent safety actions. It stops at mutual acceptance: no activation/payment/card/text/media interface or server dialogue storage is added. It never switches to phase1 simulation as a substitute. See PHASE3_MATCHING.md for the contract, asynchronous safeguards and exact unexecuted acceptance gates. Existing phase1 modes remain explicit and unchanged.

Deletion describes the backend's bounded synthetic erasure, not removal of all tombstones/receipts/counters, backups, fake-mail snapshots or another device's memory. It neither cancels subscriptions nor recovers conversation keys. Refresh/401 revalidates session access; no local timer is treated as server-authoritative expiry.

## Lightweight checks

From apps/mobile with the recorded isolated Dart SDK:

```
dart --old_gen_heap_size=128 --enable-asserts tool/check_identity_client.dart
flutter analyze --no-pub
```

`test/identity_widget_test.dart` tests injected fixtures; it is not proof of live Django or email delivery. The standalone runner prints only static case names/counts and suppresses failure operands that might contain private test values.

## Opt-in actual framework journey

The test-only `tool/identity_fixture_bridge.dart` starts the separately reviewed Python fixture inside a running test body, after compilation. It uses anonymous stdin/stdout JSON pipes only; no secrets in flags, environment, files, HTTP mailbox endpoints or diagnostics. Read the backend's `backend/integration/IDENTITY_PIPE.md` first.

```
dart --old_gen_heap_size=128 tool/check_identity_live.dart --run-disposable-identity
```

That explicit command may create a fresh192MiB isolated PostgreSQL container/volume, run the existing14 PG prerequisites, start127.0.0.1 WSGI, and obtain synthetic verification codes through a private RAM-only pipe. It must be resource-coordinated and authorized before execution. The driver requires both terminal `cleanup_verified:true` and exit0, not only a shutdown acknowledgement. Failure handling closes stdin and waits for owned cleanup; it never automatically SIGKILLs the process or removes unrelated artifacts.

Live evidence, independent race probes, source SHAs and any compile/resource blockers belong in `IDENTITY_VERIFICATION.md`. Tests existing in source are not passed tests. Native Android/iOS builds, real screen readers, full security/release approval and store acceptance remain separate unexecuted gates.

The optional live widget journey uses WAINAK_RUN_IDENTITY_WIDGET=1 with flutter test --no-pub --concurrency=1 test/identity_live_widget_test.dart. This is a nonsecret opt-in, not authorization by itself. Its actual execution status is recorded separately.

## Integrated fixture selection (test-only)

Live tests now require either an explicit bridge script argument or WAINAK_IDENTITY_FIXTURE_SCRIPT=/absolute/owned/checkout/backend/integration/serve_identity_fixture.py. There is no fallback to another branch. For integration acceptance, set this to the integration checkout being tested, not backend-auth-phase2. The path must be canonical, nonsymlink, a regular file owned by the current OS UID, not group/world writable, and at most1MiB. A fixed local metadata/hash probe checks the file without importing/executing it; missing/invalid selection fails before starting the fixture or PostgreSQL. This is a trusted test capability, never imported by app lib code.

The live driver/widget test writes only nonsecret TEST_FIXTURE_PROVENANCE path+SHA256 to test evidence. No email/password/code/token is logged. Keep the selected fixture source frozen during a run. Run dart --old_gen_heap_size=128 tool/check_identity_fixture_selection.dart for nine path-selection checks without any fixture or DB execution. Existing non-live tests do not need the variable.

The metadata verifier uses O_NOFOLLOW/O_NONBLOCK and fstat before reading. Its output is bounded32KiB; a timeout terminates and awaits only that owned metadata child (TERM, then bounded KILL fallback), never the PostgreSQL fixture. FIFO rejection and forced timeout cleanup are covered by the light path checks.

## Portable fixture runtime (unified source)

The bridge additionally requires `WAINAK_IDENTITY_FIXTURE_PYTHON` and `WAINAK_IDENTITY_FIXTURE_HOME`, or explicit `python`/`home` arguments. Python must be an absolute executable path; venv interpreter symlinks retain their selected path. The home must be an existing private `0700` directory at its canonical path. There are no host-specific defaults. See [the current mobile guide](README.md) for all three fixture variables.

Only the selected home, fixed system PATH/language, and Python no-bytecode/unbuffered/no-user-site flags enter the child environment. The parent environment and credential/import overrides are not inherited. `test/identity_fixture_runtime_test.dart` checks rejection and precedence, private-path validation, immutable environment projection, and an actual small Python child without starting a fixture or database. These checks do not prove a selected interpreter or fixture source trustworthy.
