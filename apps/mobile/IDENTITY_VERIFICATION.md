# Phase 2 mobile identity evidence — 2026-10-24

Candidate branch: `dev/phase2-mobile-auth-20261024`, based on phase1 `efd0421d559af6ee50ce04b887c7c40481d01aa0`. Backend application: `93dd42f2141d551e86ec55861bc66802be247bef`; additive private fixture: `144937a34e88e3b558b0c9a007d36d529c5621a1`. This report does not imply main merge, deployment, store acceptance or production security approval.

## Passed on the candidate source

The executable acceptance snapshot is `d69ad71bfee61e3a8ec73c0e282a7856e2c36934`. A subsequent evidence-only commit may update this report without changing tested code. Final independent QA is recorded separately.

- Fresh cold `git archive` snapshot (no project `.dart_tool` or `build` cache), offline dependency resolution, then `flutter test --no-pub --concurrency=1 --reporter=expanded`: **47 passed, 2 deliberately opt-in tests skipped**, job `c2cefc34-5c11-4e14-b264-d13c80be66bc`, 11:02:58–11:03:49, exit0. Includes38 retained phase1 tests and9 identity tests (one aggregates the21 client checks; eight exercise widgets).
- Identity widget checks now PASS: signup/verification/profile/three questions/login/logout/verified deletion, owned pending deletion, expiry clears declarations, cancellation, busy keyboard/late close, preserving stored profile fields, old deletion confirmation, Arabic RTL at320px and200% scale.
- **Actual widget taps → native HTTP → Django/allauth → fresh PostgreSQL PASS**, job `578c8afd-0fff-471e-9fe6-61ee30d1e576`, 11:04:24–11:05:10, one journey43s. Private mailbox code stays in anonymous pipes/RAM. Covers registration, verification, profile/questions, independent peer session, global revocation and401 UI, logout/login, recent-password verified deletion, and fresh owned pending deletion. Fixture starts only after test compilation. Normal cleanup fields, stdout/stderr EOF and child exit0 are required; separate11:06:30 audit found no fixture containers/volumes/tmpdirs or Flutter test process. This is not a DB/app-process restart test.
- Client21 and analyzer reran successfully after the import-only correction in d69ad71. No app library logic changed in that correction.

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

## Web compilation: mixed result, not a clean all-target pass

Job `1b5fec9d-ffda-4ed4-a5bc-57c06e7a476f`,11:06:30–11:07:49, ran `flutter build web --debug --no-pub` with explicit development identity mode and loopback URL. Exit0 produced `build/web` (JavaScript debug), but the optional wasm dry-run exited255 with Dart heap exhaustion. **Wasm preflight FAILED** and was not retried; there is no blanket web-build/all-target success claim. Owner current usage briefly approached2GiB, without observed kernel OOM kill. Identity mode on web deliberately shows unsupported status, and no browser or real web authentication was exercised.

## Failure history and remaining limits

- At09:20 a single bounded Flutter attempt (job `120684cf-ed23-4ec6-80ea-d24c4c737939`) exhausted the384MiB frontend heap before assertions under the1GiB owner cgroup. It was stopped and no repeat occurred until explicit user approval at10:40:25 for a temporary2GiB service /768MiB compiler window. No kernel OOM kill was observed.
- First cold compile under the approved window (job `f43344e4-bf99-48ba-9645-78ebea1479d1`) cleared the memory barrier and passed38 baseline tests, but the new widget fixture could not load because relative and package imports created distinct ApiTransport library identities. This was a test-harness error, not an app authorization bypass. Canonical package imports in fixture/standalone runners fixed it in d69ad71, followed by the fresh cold47-test PASS above. Analyzer alone had not detected this compiler issue.
- The two skipped opt-ins in the default suite are phase1 live backend and phase2 live identity. Phase2 live identity subsequently passed separately. The historical phase1 live backend journey was NOT rerun against its old backend in this phase; its original evidence remains tied to efd0421.
- Native web identity is deliberately unsupported; no weakening of Origin/Cookie controls is used to make web pass. A web compilation result does not establish web login usability.
- Android/iOS builds, real devices, VoiceOver/TalkBack/NVDA evaluation, full release/security assessment and store acceptance remain NOT RUN. Password-reset/change UI, identity-mode relationship activation/discovery/chat/payment integration, secure token persistence, real SMTP and production HTTPS are not implemented.
- Backend103/103 and private fixture68+5 independent results are backend evidence only. Live401 evidence uses actual revocation, not simulated passage of30-minute/24-hour expiry. No real email or identity/age assurance is claimed.

## Reproduction and resource discipline

All commands run as `chatbot`, from the isolated worktree's `apps/mobile`, not main. Tools:

```
HOME=/home/chatbot/wainak-dev/mobile-tools/home
PUB_CACHE=/home/chatbot/wainak-dev/mobile-tools/pub-cache
PATH=/home/chatbot/wainak-dev/mobile-tools/flutter/bin:$PATH
CI=true FLUTTER_SUPPRESS_ANALYTICS=true DART_SUPPRESS_ANALYTICS=true
FLUTTER_TOOL_ARGS='--old_gen_heap_size=384 --new_gen_semi_max_size=16'
```

The compiler wrapper was temporarily changed from384/8 (SHA a5117daa0261dc7e3f3daec2c26796f425d192fa937e2e44288798d7ccda1063) to768/16 (SHA677f6121ffa3b9145e10aca3b3b9054fd87ae7781c5f19486892e1572baff07c), after the backend coordinator verified owner MemoryMax2147483648. FLUTTER_TOOL_ARGS stayed384/16. One compiler/test job at a time; no separate PG job during compilation. Observed owner current usage during cold testing was about1.65GiB; OOM/oom_kill counters0. Restoration to384/8 and1GiB is required after independent QA; the coordinator records that actual rollback separately. Mailcow remains stopped at the user’s explicit request.

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
