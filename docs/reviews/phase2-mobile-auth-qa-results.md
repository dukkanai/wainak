# Phase 2 native synthetic identity — independent QA

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Date: 2026-10-24 UTC. **The tested native development slice passed the checks
listed below. This is not production, release, store, full-project or all-platform
approval.** No open P0/P1 finding remains in this reviewed slice; unimplemented and
unexecuted gates remain explicit.

## Exact pair and source provenance

- Mobile: `482f7de35b795c6c9eaf5a96d8a97c1631b0b6c5`,
  `dev/phase2-mobile-auth-20261024`, `/home/chatbot/wainak-dev/mobile-auth-phase2`.
- Backend: `144937a34e88e3b558b0c9a007d36d529c5621a1`,
  `dev/phase2-auth-20261024`, `/home/chatbot/wainak-dev/backend-auth-phase2`.
- QA branch: `dev/phase2-auth-qa-20261024`,
  `/home/chatbot/wainak-dev/qa-auth-phase2`; this report and four independent test
  files are committed together after execution.
- Main remained `9102af8606277c80412613e46dd7140d3b8fa663`, clean. No merge,
  push, deployment, live DB migration, real mail, payment or real user was involved.

Reviewer confirmed host `ostath`; all project/test/Git operations ran as `chatbot`.
The final mobile commit changed documentation only versus developer-tested d69ad71,
but the reviewer still tested the exact final commit independently. A fresh
`git archive` containing `apps/mobile` was extracted to
`/home/chatbot/wainak-dev/qa-mobile-auth-cold-482f7de`. Neither `build` nor
`.dart_tool` existed before offline dependency resolution and the first test run.
No previous kernel/build cache was copied. Existing pinned SDK/package downloads
were reused; this is a cold **project build**, not a fresh SDK installation.

At 11:16:29, all **107 committed mobile files** in the tested archive were compared
byte-for-byte to the final commit and matched. The two independent eligibility
widget cases were added as one explicitly QA-owned overlay file in the archive,
not to the developer's worktree. Both developer worktrees and main stayed clean.
The separate standalone QA probes imported the frozen mobile worktree, whose
exact HEAD, clean state and client hash were verified.

## Independently executed results

| Evidence | Exact result |
|---|---|
| Cold default Flutter suite | **47 passed, 2 explicit live opt-ins skipped**; job `6fc61f34-1f0e-4752-902c-28a9ca49eea2`, 11:09:23.107–11:10:10.708, exit 0 |
| Actual identity widget → HTTP → Django/allauth → fresh PG | **1 journey passed**; job `c700bc47-e932-49be-b506-39d78d5a2796`, 11:12:29.073–11:13:14.890, exit 0, 42 s test time |
| Two additional independently authored UI eligibility cases | **2 passed**, job `4a7d8ac7-2049-4844-8349-d1ba59fba706` |
| Analyzer including QA overlay | **No issues**, same job, 2.8 s |
| Standalone client checks | **21 passed**, same job; repeated from the aggregate client test inside the default suite, not 21 additional unique Flutter tests |
| Private PIPE parser checks | **5 passed**, same job |
| Independently authored deferred lifecycle probes | **9 passed** (3 pending-transition + 6 actor/destructive-action cases), same job |
| Independent live pending/duplicate-flow deletion | **Both journeys passed** in one private disposable fixture, same job |
| Final adversarial job terminal | 11:14:24.539–11:15:09.974, exit 0 |
| Source/cleanup audit | job `cd8ef1bf-f810-4ba5-a3d4-b8aee24cb4a1`, 11:16:29.173–11:16:29.641, exit 0 |

Do not sum the rows into a fictional count of unique tests. The live fixture also
runs the same 14 PostgreSQL prerequisites before readiness; these are repeated
prerequisites, not new independent scenarios. The previously documented backend
103-case identity/deletion suite and 68-unit/5-PIPE-probe results retain their own
exact source evidence in the earlier reports; they were not rerun wholesale here.

The default suite's phase2 live identity skip was subsequently closed by the
separate opt-in widget run above. The phase1 legacy live-backend opt-in was **not
rerun on this new mobile commit**; historical phase1 live evidence stays tied to
its original version. Its mocked/domain/client/widget regressions did run here.

## What the live evidence actually proves

### Widget-driven journey

The test disables Flutter's fake HTTP client only for its loopback test binding.
After test compilation, actual widget taps start the reviewed private Python PIPE
fixture and drive registration, pending verification, a code retrieved from the
RAM-only committed fake mailbox, framework email verification, profile/preferences,
three reflection questions, an independently authenticated peer session, global
revocation and peer 401, a peer-triggered revocation displayed as 401 in the UI,
logout/login, recent-password verified deletion and fresh owned pending deletion.
No simulated authentication/verification/admin endpoint or fake peer approval is
used. This is headless widget E2E, **not a physical-device test**.

### Independently authored live adversarial journey

`identity_live_deletion_probe.dart` uses the native typed client and real HTTP,
Django/allauth and fresh PG. It establishes that:

1. An owned pending flow rejects an incorrect password without deleting the account,
   accepts its correct password and explicit confirmation, then rejects login to
   the deleted identity.
2. A duplicate anti-enumeration signup flow cannot erase an existing verified
   account, even when this controlled test supplies that account's correct current
   password. The actual owner can still read its profile. The owner subsequently
   deletes through reauthentication, and its other authenticated session is denied
   and clears its local identity.

Synthetic credentials/codes/bearers stay in process memory/private anonymous pipes;
assertions and diagnostics do not print their operands. The bridge rejects proxy
use/redirects, malformed/oversize private records, trailing output and nonempty
stderr. Normal completion requires terminal cleanup fields, both pipe EOFs and
child exit 0. This fixture uses an owned WSGI thread; **it is not an application/DB
restart test**, and live 401 here is revocation, not waiting 30 minutes/24 hours.

## Independent edge-case coverage and findings

- `qa_identity_eligibility_test.dart`: UI age 17 plus all declarations cannot send
  registration; omitted privacy consent remains false and blocks registration
  until explicitly selected. The latter has a positive pending-flow control.
- `identity_client_race_probe.dart`: late resend, late pending session refresh and
  late expired-flow response cannot overwrite/downgrade/revoke a newer verified
  session. A successful protected-domain request is the positive control.
- `identity_client_actor_probe.dart`: old A-domain 401 or A identity proof cannot
  clear/replace B; A's deferred reauthentication cannot continue to delete B;
  old confirmation sends no request; closing rejects a late identity proof;
  old logout-all completion cannot clear the newer B session.

### Closed findings

**P1 — pending/auth session generation race.** Independently reproduced as 3/3
failures on the original draft client hash `15b88935...`. Generation advancement
when installing pending/verified/rotated flows closed the defect; the same three
probes passed on `21c2f574...` and all nine probes passed again on final
`8ac893a1...`. A stale confirmation is bound to the generation captured when its
modal opened, and authenticated deletion rechecks after asynchronous reauth.
This was a client lifecycle defect, not a demonstrated backend authorization bypass.

**P2 — leap-day synthetic age boundary.** Draft date normalization could turn an
18-year-old fixture into a 17-year-old date on February 29. A server-independent
clock seam and day clamp are covered by the final 21-check client suite. This does
not establish real-world age verification.

**Test-fixture controls.** QA requested incremental byte bounds before newline,
stdout/stderr EOF validation and trailing-output rejection in the Dart bridge;
all are now exercised. The backend buffered-command deadline issue and its fix
are documented in the separate private-PIPE QA report. The initial widget import
identity error was fixed by canonical package imports in tests/runners; it was a
harness compiler issue, not an app permission bypass. Earlier heap failures were
not counted as functional passes.

## Acceptance matrix

| Gate from plan | Result and boundary |
|---|---|
| F2-SCOPE-01 | PASS for explicit synthetic native mode, loopback origin, persistent warning and no silent fake fallback. Default main without WAINAK_DEV_MODE is disabled. Production packaging/explicit dev flag in a release build NOT evaluated. |
| F2-REG-01 | PASS current UI/client minor and missing-consent rejection, explicit declarations/version; live valid registration. Direct API minor/version evidence remains in separately versioned backend QA, not newly claimed here. |
| F2-FLOW-01 | PASS pending 401 versus authenticated proof, logout 401 success, real revoked-session 401 clearing. |
| F2-VERIFY-01 | PASS fake invalid/resend paths and real framework verification via private mailbox; no client verification bypass. Full server expiry/attempt races retain backend-specific evidence. |
| F2-TOKEN-01 | PASS reviewed RAM-only X-Session-Token transport, no token URLs/storage/log output, fixed loopback origin, DIRECT proxy and no redirects. Native secure-storage/release audit NOT implemented. |
| F2-RACE-01/02 | PASS nine independent deferred cases, modal-generation widget case and close/busy regressions. |
| F2-NAV-01 | PASS busy pointer/keyboard suppression, cancel controls, explicit confirmation and no automatic retry on uncertain requests. |
| F2-PRIVACY-01 | PASS pending cannot access profile; revoked/deleted state clears identity/declarations. Identity-mode matching/block/chat is not implemented. |
| F2-LOGIN-01 | PASS actual actor proof/login and independent duplicate-flow isolation; not legal identity verification. |
| F2-REVOKE-01 | PASS current/global logout, actual second session denial, stale completion guards. |
| F2-DELETE-01/02 | PASS verified reauth/confirmation, real owned pending delete, wrong-password rejection and duplicate-flow non-ownership. Retention/backup guarantees remain explicitly limited. |
| F2-ERROR-01 | PARTIAL: fixed typed errors, uncertainty/no retry, expiry/rate-limit paths covered by source and listed checks; not every HTTP status or every OS/network interruption has a new live test. |
| F2-API-01 | PASS supported profile/preferences/assessment contract and explicit unsupported relationship/payment/chat scope. |
| F2-A11Y-01 | PARTIAL: headless Arabic RTL at 320 px/200% plus keyboard/busy and verification/delete flows passed. Actual VoiceOver/TalkBack/NVDA/device evaluation NOT RUN. |
| F2-LIVE-01 | PASS actual widget→HTTP→allauth→fresh PG journey for this exact pair. |
| F2-LIVE-02 | PARTIAL: revocation/deletion continuity within live fixture passed; no new actual server/DB restart in this mobile run. Earlier backend restart evidence is separate. |
| F2-MAIL-01 | PASS reviewed private anonymous PIPE only; no mailbox/admin HTTP route, real SMTP or secret env/argv/files/logs. |
| F2-EVIDENCE-01 | PASS exact commits, cold source archive, 107-file equality, job IDs, test source hashes and independent cleanup below. |

## Source hashes

| File | SHA-256 |
|---|---|
| Mobile `lib/src/identity/client.dart` | `8ac893a14d762e26ae01932c2e5ec5482500c340958fb1f763c5382105355173` |
| Mobile `tool/identity_fixture_bridge.dart` | `1837fed5ecbaa3cd771648c5481c7820970e7d344c34152f0806825e68f3d4c7` |
| Mobile `tool/private_fixture_protocol.dart` | `2b777f800a12677405da6838c3f32d84fbc6d80613ac4a18fed5b6c08f357dfe` |
| Mobile live widget test | `f555cd131b221845f411f8466eb20428af8723687b3c0dc14d20a32fe24ea4cf` |
| QA pending-transition probe | `bdb8acac7ed0277ae2cdd008342f3cbc4645851985438a3436e063c5839992c6` |
| QA actor-lifecycle probe | `55551240c13fac2520a3f188549ef64dce8a7e76e4e42c880b72c2ca01f670aa` |
| QA live deletion probe | `645e13b5ecb225d4978e36aab647608d4fb8f9631e2b515de1427528f6742865` |
| QA eligibility widget overlay | `55e2eccecf00a220dde4154e27c216f3a4a0eac1f1e25cca75faf39d08f007d1` |

## Cleanup, resources and reproduction

Audit at 11:14:24 after the widget fixture and final independent audit at 11:16:29
found **zero** labeled containers/volumes and chatbot-owned
`/tmp/wainak-postgres-test-*` directories. Final audit also found zero owned fixture
or Flutter tester processes. No cleanup of unrelated resources was performed.

Temporary owner 2 GiB / compiler wrapper 768/16 was explicitly authorized after the
single earlier heap failure. One compiler or disposable fixture job ran at a time;
PG starts only after compilation, inside the actual test. Project HOME/PUB_CACHE
were under `mobile-tools`, analytics disabled, FLUTTER_TOOL_ARGS384/16. Direct Dart
checks used heap128. The first suite was cold; later isolated widget/probe commands
reused that verified project's caches and are not called additional cold builds.

After QA's explicit release at11:16:35, the UI coordinator restored wrapper384/8
at11:16:53 (SHA `a5117daa0261dc7e3f3daec2c26796f425d192fa937e2e44288798d7ccda1063`).
The backend coordinator verified MemoryMax1GiB at11:18:16, unchanged MainPID3460430 /
NRestarts5 and prior properties, no kill/reclaim, zero fixture resources and18
Mailcow containers still stopped. This restoration evidence was supplied by the
coordinators, not another compiler/PG run. Record:
`/home/chatbot/wainak-dev/owner-memorymax-phase2-20261024T1059.restored.json`, SHA
`ee2e77dd5d67055f46e8d71f81613f26d04f7f3190feaaa9da28a2bb74553761`.
Mailcow remains stopped under the user's explicit instruction. No additional
compiler or resource change is needed for this report.

Representative commands from the isolated archive (all as chatbot):

```sh
flutter pub get --offline
flutter test --no-pub --concurrency=1 --reporter=expanded
WAINAK_RUN_IDENTITY_WIDGET=1 flutter test --no-pub --concurrency=1 --reporter=expanded test/identity_live_widget_test.dart
# Copy only the new QA-owned overlay into the archive's test/ directory first.
flutter test --no-pub --concurrency=1 --reporter=expanded test/qa_identity_eligibility_test.dart
flutter analyze --no-pub
<dart-sdk>/dart --old_gen_heap_size=128 --enable-asserts tool/check_identity_client.dart
<dart-sdk>/dart --old_gen_heap_size=128 --enable-asserts tool/check_identity_protocol.dart
<dart-sdk>/dart --old_gen_heap_size=128 <qa>/qa/phase2_mobile/identity_client_race_probe.dart
<dart-sdk>/dart --old_gen_heap_size=128 <qa>/qa/phase2_mobile/identity_client_actor_probe.dart
<dart-sdk>/dart --old_gen_heap_size=128 <qa>/qa/phase2_mobile/identity_live_deletion_probe.dart --run-disposable-identity
```

The standalone QA probes intentionally import the reviewed frozen server worktree
via absolute file URIs. The widget overlay resolves the candidate's canonical
package imports. They are server-specific test artifacts, not app entrypoints.

## Unresolved release/platform/product gates

Developer web job `1b5fec9d-ffda-4ed4-a5bc-57c06e7a476f` produced a JavaScript debug
artifact with exit 0, **but its optional wasm dry-run FAILED with heap exhaustion**.
This mixed result was not rerun or relabeled by QA as all-target success. Identity
web mode intentionally shows unsupported status; browser authentication is not
implemented and no Origin/Cookie policy was relaxed for it.

Android/iOS release builds, actual devices/readers, production HTTPS/SMTP, secure
session persistence, KMS/rotation, operational moderation/CSAE, approved retention/
legal basis, a publicly hosted deletion-request service, store declarations and
acceptance remain outside this development result. Password reset/change UI and
identity-mode relationship/activation/discovery/chat/payment integration are not
implemented. The 24-hour orphan rule is a sandbox fixture policy, not approved
production retention. No E2EE identity/key/history recovery is inferred from email
verification or password reset. No merge or deployment was performed.


## Merge-readiness boundary

This is evidence for review of a **native synthetic-auth development integration**,
not permission to merge main. Mobile and backend were tested as the exact pair
above in separate worktrees. No combined integration merge commit has yet been
created or independently verified by this reviewer. A separately authorized merge
must resolve any conflicts and re-run relevant checks against that actual combined
commit; old pair results must not silently certify changed merge output.

The failed wasm preflight, skipped legacy live opt-in and unexecuted device/release/
production gates prohibit describing the whole project or every target as approved.
A limited development integration decision can explicitly exclude those targets,
but does not erase the failures or authorize deployment. No merge operation was
performed or requested by this reviewer.
