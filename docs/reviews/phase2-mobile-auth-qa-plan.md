# Phase 2 Flutter auth — independent QA plan

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Date:2026-10-24. **NOT RUN; mobile source/commit pending.**
Backend reference is93dd42f2141d551e86ec55861bc66802be247bef, not a production
service. Backend103/57 and web mocked-Node4 results do not certify a new Flutter
client. Phase1 mobileefd0421d559af6ee50ce04b887c7c40481d01aa0 remains immutable.

## Scope and resource boundary

Review the separately developed synthetic auth mode and its explicit contract:
register, pending verification, login, current profile, expiry, logout/revocation
and verified/pending deletion. No real mail, operational user/key, payment,
deployment or existing DB access. All server work aschatbot. Current owner1GiB
limit stays unchanged; reserve a single compiler/PG window, report cold/warm
cache and memory blockers honestly, and do not repeatedly retry a known failing
cold compiler or raise limits without authorization.

## Acceptance gates

| ID | Priority | Required evidence |
|---|---|---|
| F2-SCOPE-01 | P0 | Distinct synthetic auth mode; no silent legacy dev-token/auth fallback, unsupported web transport or production-ready appearance |
| F2-REG-01 | P0 | UI and direct API18+/current consent; booleans and versions correct, no client-controlled verified flag |
| F2-FLOW-01 | P0 | allauth401 can mean successful pending/reset/logout; typed flow handling distinguishes it from expired/invalid authentication |
| F2-VERIFY-01 | P0 | Verification purpose/session binding, code rejected/expired/resend-limited states, no fake partner decision or automatic client verification |
| F2-TOKEN-01 | P0 | X-Session-Token only for this API; no tokens/password/code in URL/log/storage/debug output; no forwarding a session to a changed base URL |
| F2-RACE-01 | P0 | Session generation guards before accepting late tokens/DTOs after logout/delete/mode switch/expiry/dispose |
| F2-RACE-02 | P0 | A stale401 must not clear a newer actor; a delayed A response must not populate B's profile or authorize deletion of B |
| F2-NAV-01 | P1 | Busy controls prevent repeated pointer AND keyboard requests; interruption/unknown outcome does not automatically repeat irreversible work |
| F2-PRIVACY-01 | P0 | Pending/unverified cannot enter protected profile/matching; expired/revoked/blocked state removes private projections immediately |
| F2-LOGIN-01 | P0 | Correct actor shown after actual login; wrong/deleted/revoked identity never treated as logged in; duplicate signup remains non-enumerating |
| F2-REVOKE-01 | P0 | Current logout and logout-all invalidate correct state, clear local bearer/DTOs, and do not revive through delayed responses |
| F2-DELETE-01 | P0 | Verified deletion requires current password/reauth and explicit confirmation; only identity_erased success is shown as deletion |
| F2-DELETE-02 | P0 | Pending deletion uses current owned pending flow+password; fake duplicate/verified fallback rejected; no email-only erasure |
| F2-ERROR-01 | P1 |400/401/403/409/410/429/500,timeout and cancellation handled without secret/error-body dumps or false success |
| F2-API-01 | P1 | Exact native DTO/route contract; identity API has no entitlement/activation endpoint, so unsupported features are not silently simulated |
| F2-A11Y-01 | P1 | RTL,200% text, labels/semantics/focus and password obscuring tested on the exact build; real VoiceOver/TalkBack separately NOT RUN if unavailable |
| F2-LIVE-01 | P0 | Independent widget actions→nativeHTTP→Django→freshPG where claimed, not only injected fake repository or client-only integration |
| F2-LIVE-02 | P1 | Actual server/DB restart and session revocation/erasure continuity, with exact source and owned-resource cleanup |
| F2-MAIL-01 | P0 | Live signup/verify test uses reviewed private fixture IPC only; no HTTP mailbox/admin bypass or secret env/argv/regular file/log |
| F2-EVIDENCE-01 | P1 | Exact backend/mobile/QA commits, test hashes, tool/cache/resource conditions, PASS/FAIL/NOT RUN and scope recorded independently |

## Fake mailbox integration constraint

The backend fake mailbox is Python process memory, not an HTTP API. Full live
Flutter signup→verification needs an explicitly reviewed private test-harness
channel to deliver the fake verification code to the test inRAM. Do not solve
this by exposing a mailbox endpoint, embedding codes in dart-define/environment/
arguments/files, or bypassing actual framework verification. The parent/backend
must coordinate the fixture seam before it runs. A login-only live test must
be labeled login-only, not verification UI E2E.

Native backend rejects Origin/cookies outside the special deletion-web allowlist.
A Flutter web build is therefore not evidence that general browser auth transport
works. Unsupported platform modes must fail clearly rather than borrow the web
deletion marker to widen the backend route boundary.

## Reporting

Keep prior baseline reports unchanged. First review source and test harness,
then run developer checks and independent adversarial/widget/live cases on the
same frozen candidate. Report P0/P1 findings immediately. Never convert source
inspection, warm-cache compilation, mocked transport, or a local package build
into real-device, SMTP, security, accessibility, store or production approval.
