# Phase 2 native identity sandbox

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
- Account/profile/preferences hydration on login preserves existing gender, marital status, declared wives, marriage goal and unedited preference lists. New empty accounts use the explicitly described female/single sample. Three adaptive reflection questions use backend option IDs.
- Auth transitions advance a generation; old pending replies cannot replace verified sessions. Delete/revoke confirmation is bound to the generation when opened, not whichever account is current later. Password/code controllers clear promptly, and disposed clients reject late responses.
- Busy forms exclude keyboard focus as well as pointer actions. Arabic/RTL, light/dark theme and existing48-target/16-helper tokens are retained. Layout tests exist but their execution must be checked in the evidence report.

Only ASCII canonical `@example.invalid` addresses are accepted. Do not reuse real passwords. Email proof is not legal identity, age assurance or device/key trust. No password-reset/change UI, secure token persistence, SMTP, social/MFA login, production keys or HTTPS deployment is implemented.

This mode currently ends at the authenticated profile/assessment. Relationship activation has no endpoint in the identity API; relationship/discovery/message/payment interfaces are not wired in this mode, and it never switches to phase1 simulation as a substitute. Existing phase1 safety flows remain in their own explicit modes.

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
