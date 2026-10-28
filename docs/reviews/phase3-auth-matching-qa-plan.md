# Phase 3 authenticated matching / introduction — independent QA gates

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Baseline: `b5f63ef0090be2513833a86e22c6c7032514c9f7`, 2026-10-24.
Status: plan only, **no phase 3 candidate has passed yet**. Every result must name
its exact backend/mobile commits, test source and runtime job. Old merged results
are regression references, not evidence for new code.

## Deliberately bounded scope

Framework-authenticated synthetic accounts may discover eligible candidates,
request introduction, receive incoming requests, accept/decline, cancel/end,
block/report and refresh current state. UI stops at `accepted_pending_activation`.
Acceptance does not imply activation, payment, exclusivity or disclosure. No real
SMTP, production credential, deployment, push or main merge is included.

D16/17 prohibit automatic server storage of dialogue content, including encrypted
payloads. Selected dialogue-card IDs, answers, per-couple progress/history, outbox
and delivery queues are not assumed to be harmless metadata. They are outside
this slice. The authored content library and consented initial matching assessment
are distinct permitted data categories. D25 upload is still disabled; a report
contains bounded metadata only and never attaches content implicitly.

## Acceptance matrix

| ID | Gate and decisive negative cases |
|---|---|
| M01 | Actor is exclusively framework session → server user/domain mapping. Pending, revoked, expired and deleted sessions cannot discover/request/respond. JSON/header actor IDs do not substitute authority. |
| M02 | Both parties satisfy current consent, age18+, profile/preferences, discoverability, reciprocal preferences, marital limits and exclusivity at discovery and acceptance time. Changes after request are rechecked. |
| M03 | Public candidate/relationship projections exclude email, birth date, assessment answers, private preferences, wife count, tokens, health and disclosure fields. Hidden/blocked/deleted/stale-policy peers do not leak hidden reasons through discovery. |
| M04 | Relationship IDs are participant-scoped. Unrelated third account cannot read/respond/cancel/end/cards/exclusive or report with another relationship's authority. Incoming/outgoing labels are computed, not supplied by client. |
| M05 | Only recipient can accept/decline; initiator cannot impersonate it. Only initiator can cancel. Exact payload fields/types are checked. Available-action hints are non-authoritative and actual routes independently enforce state/role. |
| M06 | Stale consent may decline safely at the exact respond route, but may not accept, request or change eligibility fields. Extra fields, malformed decision, suffix confusion and boolean coercion cannot bypass the guard. Cancel/end/block/report/delete remain available within their own authority rules. |
| M07 | Actor + idempotency key + target binding: lost-response replay returns the same relationship and current safe state; same key/new target conflicts; different actors do not collide; opposite-direction/concurrent requests create at most one unordered pair. |
| M08 | Accept versus block/delete/cancel/end races cannot leave communication enabled. Terminal/current safety state wins regardless of stale success response. DB/WSGI restart preserves state and revoked access. No automatic reopening. |
| M09 | Accepted requests remain locked: all card/text/media/disclosure permissions false; no identity HTTP activation, development token, entitlement override or receipt shortcut. Purchase verification is not implemented, not silently simulated. |
| M10 | Block and report are independent/free; a target's prior block cannot prevent metadata reporting. Block suppresses cached peer projection without waiting for another successful GET. Report idempotency is actor/payload scoped; no implicit D25 attachment or punitive public verdict. |
| M11 | Missing routes for dialogue send/answer/selected-card/history/outbox/media reject input and do not persist it. Inspect schema/source and targeted synthetic markers, without claiming absence from every possible log solely from DB checks. |
| M12 | Candidate and relationship lists have explicit bounded behavior and deterministic handling. Opaque IDs/action hints do not expose global counts or private exclusion reasons. Do not invent pagination/fairness guarantees absent a contract. |
| U01 | Flutter uses independent real sessions for the two participants, never a simulate-recipient button. Incoming/outgoing and accepted-pending labels match actual DTOs; no activation/payment illusion. |
| U02 | Candidate/relationship and session generation are pinned through async refresh, back navigation, confirmation, retry and account switching. Late success/401/410 from an old session cannot overwrite or erase its replacement. |
| U03 | Retry reuses the same mutation key only for the same actor/target/intent, including uncertain/lost response. A new account or target gets a distinct intent; repeated taps and keyboard activation while busy cannot dispatch duplicate mutations. |
| U04 | Stale-consent/error/401 UI keeps safe actions available where authorized and clears sensitive cached data appropriately. Arabic RTL, narrow320px/200% text, semantics, keyboard/focus and interruption tests cover the new paths. Native device/readers remain separately not run. |

## Baseline facts, not newly discovered vulnerabilities

`IdentityDomainService._eligible` already checks stored current consent before
calling the domain eligibility rules, and `_pair_eligible` dispatches that override
for both parties. Its relationship projection also hides a stale-consent peer.
Do not describe peer-consent omission as a proven auth-bridge defect without a
reproduction. The existing actor-wide POST consent guard does prevent safe decline;
the proposed exception must be narrow and tested. Existing identity API docs have
backend-only wording that predates the now-implemented Flutter auth adapter;
update that description without claiming production readiness.

## Execution / evidence boundaries

Use own QA branch/worktree and chatbot ownership only. Exact clean candidate
checks before/after, explicit selected fixture path/SHA, no fallback to old branches.
Fresh disposable PostgreSQL only; keys/passwords/codes in RAM/private PIPE, never
HTTP mailbox routes, files, command arguments, environment or logs. Tests use
sanitized failure summaries. One heavy job at a time, at least4.5GiB host available.
Permanent owner4GiB/compiler2560/8 stay unchanged; Mailcow stays off.

Run bounded independent adversarial cases, backend regressions, cold new Flutter
suite and real two-session widget→HTTP→PG journey as the candidate permits. Verify
owned container/volume/tempdir/process cleanup. Distinguish headless widget, mock
transport, real native HTTP and browser/device evidence explicitly. No generic
security, policy/store or release approval follows from test counts.
