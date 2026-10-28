# Phase 2 additive deletion/web QA plan

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Date: 2026-10-24. **NOT RUN / source pending.** This is separate from the
verified baseline backend `dee6ec30085e3b3e2a12ea25c912967f27f1dcd7` and QA
`c3e1b62063e0fcb1b3b809196682db205550fc0a`. Do not transfer the66/57 results.

## Authorized boundary and intended evidence

Only the existing isolated Wainak development auth scope: synthetic accounts,
fake mailbox, owned disposable PostgreSQL, temporary in-memory keys and private
loopback HTTP. No public web hosting, real SMTP, new production keys, existing DB
migration, Flutter compiler, main change, deployment or security/resource change.
All server file/Git/test operations as chatbot. Sequential test window with backend.

Review exact source for pending deletion, explicit orphan expiry and standalone
web deletion surface before testing. Capture clean backend commit and QA test
hashes. Rerun affected baseline auth cases; never use inherited counts as new
independent cases. New result report must distinguish source/HTTP verification
from actual browser JavaScript execution or mobile integration.

## Acceptance matrix

Every row starts NOT RUN. A failed or untested gate is not an approval.

| ID | Priority | Required evidence |
|---|---|---|
| D2-PENDING-01 | P0 | Valid unverified pending session + current password + explicit confirmation identify the same actual User; no actor/email supplied as authority |
| D2-PENDING-02 | P0 | Duplicate/fake signup pending state cannot delete an existing user, verified or unverified |
| D2-PENDING-03 | P0 | Wrong password, expired/unknown/revoked token, missing confirmation and wrong-purpose reset/verification material fail closed |
| D2-PENDING-04 | P0 | A session for A cannot delete B; changing submitted identifiers or headers never retargets deletion |
| D2-PENDING-05 | P0 | A fully verified user cannot bypass recent-auth deletion using the pending route |
| D2-PENDING-06 | P0 | Concurrent verification/delete: verify-first means pending deletion denied; delete-first means verification cannot resurrect identity/domain/session |
| D2-PENDING-07 | P1 | Shared transaction rollback after domain or identity deletion failure leaves a consistent, usable prior state; no partial success response |
| D2-PENDING-08 | P1 | Repeated pending deletion/replay after DB/server restart cannot recreate an account or restore old links/challenges |
| D2-EXPIRY-01 | P0 | Orphan selection uses a server timestamp and explicit development policy, not user DOB/client clock |
| D2-EXPIRY-02 | P0 | Verified accounts and accounts with valid pending ownership sessions excluded; below/at/after expiry boundary tested |
| D2-EXPIRY-03 | P0 | Cleanup serialized with signup/verify/delete; a concurrent ownership transition is rechecked under the same lock |
| D2-EXPIRY-04 | P1 | Dry-run changes no rows; apply removes only selected synthetic records, rollback safe, no token/email/password in output |
| D2-EXPIRY-05 | P1 | No scheduled service or production retention claim created; no invented legal retention duration |
| D2-WEB-01 | P0 | GET surface is local-only, non-mutating, no-store; CSP nonce/self restrictions and frame-ancestors prevent unintended embedding |
| D2-WEB-02 | P0 | Browser marker is not authorization; only exact allowed route/method pairs; cannot access other native matching/admin endpoints |
| D2-WEB-03 | P0 | Real Django CSRF checks reject missing/wrong masked token, foreign Origin and absent required Origin even with a valid bearer |
| D2-WEB-04 | P0 | csrf_exempt vendor callbacks cannot bypass the owned CSRF gate; mismatched Host/Origin/port and forged marker tested |
| D2-WEB-05 | P0 | Only the exact CSRF cookie is accepted; cookie sessions, Authorization and query tokens remain rejected; native no-cookie behavior unchanged |
| D2-WEB-06 | P0 | Web login/verify establishes only its own bearer; full delete still needs current password/recent auth or validated pending proof |
| D2-WEB-07 | P1 | No bearer/reset/code in URL, storage, DOM diagnostic output or logs; JS token stays RAM and clears on logout/delete/pagehide |
| D2-WEB-08 | P1 | Repeated submit/interruption/stale401 cannot silently switch accounts; HTTP tests alone do not prove JS UX |
| D2-WEB-09 | P1 | Enumeration and atomic rate limits retained for anonymous entry and authenticated deletion proof; no arbitrary-email deletion |
| D2-WEB-10 | P1 | Password recovery absent/implemented status explicit; no claim of complete public store deletion requirement from loopback-only fixture |
| D2-WEB-11 | P1 | CSRF rotation after login/verification updates the in-memory masked token; one cookie-jar flow can reauth/delete without manual reload; no stale-response token resurrection after pagehide |
| D2-RESOURCE-01 | P0 | Owned PG/HTTP processes/volume/tempdir cleaned on pass and failure; no existing service/DB/public port changes |
| D2-PROVENANCE-01 | P1 | Exact additive commit, hashes, command, dependency environment, terminal outcome and independent cleanup recorded |

## Review cautions

- The native allauth app views may be csrf_exempt. A manually invoked
  CsrfViewMiddleware must not be given an exempt callback and then mistaken for
  an enforced check; negative tests are mandatory.
- A custom web marker is caller-controlled. It may select stricter origin/CSRF
  processing but must never grant identity, exempt validation, or widen routes.
- Pending signup state can represent an anti-enumeration fake flow. Presence
  of a session/code alone is not proof that it owns a persisted User.
- Password reset invalidates subject sessions. Old pending proof must not
  survive reset; deleting an unverified identity must not affect an unrelated
  authenticated actor.
- Any24-hour development orphan policy is a fixture rule only. Production
  retention, legal basis, abandoned-registration notices and scheduling remain
  separate owner decisions.
- Web source/HTTP checks do not establish actual browser rendering, JavaScript
  interaction, screen-reader behavior, public reachability or store compliance.
