# Phase 2 mobile identity evidence — 2026-10-24

Candidate branch: `dev/phase2-mobile-auth-20261024`, based on phase1 `efd0421d559af6ee50ce04b887c7c40481d01aa0`. Backend application: `93dd42f2141d551e86ec55861bc66802be247bef`; additive private fixture: `144937a34e88e3b558b0c9a007d36d529c5621a1`. This report does not imply main merge, deployment, store acceptance or production security approval.

## Passed on the candidate source

- 21 standalone client checks, Dart heap128: pending versus authenticated state, server identity projection, token rotation, 401 logout success, current-session expiry, reauthentication/deletion, global revocation, rejected real addresses, no request for missing eligibility, closed/old generation guards, and leap-day date clamp. Run 09:37:49–09:37:53, job `081abe83-9621-445b-b572-1683746b1a8d`.
- 5 private protocol checks in the same run: fragmented UTF-8, 4096-byte incremental bound before newline, trailing records after closed, nonempty stderr rejection, and EOF requirements. No private protocol contents are printed.
- Analyzer: no issues at 09:38:10, job `f80b53e6-cbda-4c4e-bdb8-a72375e4c597`. The first analyzer pass found an opt-in test skip type error and two redundant assertions/import; those were corrected before this clean result.
- Actual native client → HTTP → Django/allauth → fresh PostgreSQL: signup/pending → RAM-only fake verification code → email-verified session → profile/preferences/three reflection questions → second independent session → global revoke and peer401 → logout401 → login → password reauthentication and verified deletion. Job `09a44046-48ef-4816-8846-defc285410cb`, 09:38:39–09:39:14, exit0. This is a client-driven journey, not widget taps. Fixture normal shutdown, both stream EOFs, cleanup fields and child exit0 were required. A separate audit at09:39:31 found no fixture containers, volumes, temporary directories or child processes.
- Independent QA reproduced a stale pending-response defect before the fix (3/3 failures), then passed exactly those three probes on the generation fix at09:25:41 and six additional account-switch/destructive-confirmation probes at09:29:21. These runs preceded the isolated leap-day-only patch; final exact-commit QA remains a separate gate.

Final source hashes for the above candidate checks:

```
8ac893a14d762e26ae01932c2e5ec5482500c340958fb1f763c5382105355173  lib/src/identity/client.dart
1837fed5ecbaa3cd771648c5481c7820970e7d344c34152f0806825e68f3d4c7  tool/identity_fixture_bridge.dart
2b777f800a12677405da6838c3f32d84fbc6d80613ac4a18fed5b6c08f357dfe  tool/private_fixture_protocol.dart
f555cd131b221845f411f8466eb20428af8723687b3c0dc14d20a32fe24ea4cf  test/identity_live_widget_test.dart
```

## Blocked / not run

- One bounded Flutter injected-widget compile attempt at09:20, job `120684cf-ed23-4ec6-80ea-d24c4c737939`, failed in the compiler at the384MiB Dart heap before any application assertions. It was cancelled; no remaining compiler was found at09:20:49. Owner cgroup remained1GiB, kernel OOM counters0. This is not a passing widget suite or an application assertion failure. No second heavy attempt or resource adjustment was made without further approval.
- The new injected widget suite (Arabic/RTL,320px at200%, busy keyboard, pending/verified deletion, cancel, account switch, profile preservation) is NOT RUN successfully.
- `test/identity_live_widget_test.dart` is analyzer-checked and opt-in only (`WAINAK_RUN_IDENTITY_WIDGET=1`). Actual widget-driven Django signup/verify/profile/revoke/expiry/logout/verified and pending deletion is NOT RUN. It starts the private fixture only inside the test body, after compilation; no environment flag contains a secret.
- Phase1's39 tests and prior actual live-widget PostgreSQL evidence belong to phase1 `efd0421`; they are not silently transferred to phase2. Phase2 full regression, web debug compile, Android/iOS builds, real devices, VoiceOver/TalkBack/NVDA evaluation and release/security gates are NOT RUN here.
- Native web identity is deliberately unsupported; no weakening of Origin/Cookie controls is used to make web pass. Password-reset/change UI, relationship activation/discovery/chat/payment integration, secure token persistence, real SMTP and production HTTPS are not implemented in this mode.
- Backend103/103 and private fixture68+5 independent results are backend evidence only, not mobile UI results. Live401 evidence here uses actual global revocation; it does not simulate passage of30-minute/24-hour expiry or claim an app-process/DB-restart test.

## Reproduction and resource discipline

All commands run as `chatbot`, from the isolated worktree's `apps/mobile`, not main. Tools:

```
HOME=/home/chatbot/wainak-dev/mobile-tools/home
PUB_CACHE=/home/chatbot/wainak-dev/mobile-tools/pub-cache
PATH=/home/chatbot/wainak-dev/mobile-tools/flutter/bin:$PATH
CI=true FLUTTER_SUPPRESS_ANALYTICS=true DART_SUPPRESS_ANALYTICS=true
FLUTTER_TOOL_ARGS='--old_gen_heap_size=384 --new_gen_semi_max_size=16'
```

Use the direct SDK Dart executable for lightweight checks:

```
/home/chatbot/wainak-dev/mobile-tools/flutter/bin/cache/dart-sdk/bin/dart --old_gen_heap_size=128 --enable-asserts tool/check_identity_client.dart
/home/chatbot/wainak-dev/mobile-tools/flutter/bin/cache/dart-sdk/bin/dart --old_gen_heap_size=128 --enable-asserts tool/check_identity_protocol.dart
flutter analyze --no-pub
```

Only in a coordinated, explicitly authorized disposable test window:

```
/home/chatbot/wainak-dev/mobile-tools/flutter/bin/cache/dart-sdk/bin/dart --old_gen_heap_size=128 --enable-asserts tool/check_identity_live.dart --run-disposable-identity
```

The fixture uses a fresh limited PostgreSQL container, local-only ephemeral HTTP and anonymous private pipes. No passwords/codes/tokens are placed in command text, environment, files, logs or an HTTP mailbox endpoint. The fake mailbox is not real delivery. No automatic destructive retry occurs on network uncertainty. Independent final QA should record its exact mobile/backend commit pair separately.
