# Phase 2 additive pending deletion / web surface — independent QA

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Date: 2026-10-24 UTC.
**نجحت الاختبارات المحددة على النسخة نفسها. النتيجة لتطوير معزول فقط؛ لا نشر أو بريد حقيقي أو اعتماد متجر، ولا اختبار متصفح فعلي.**

## Source, separation and terminal evidence

- Backend: `dev/phase2-auth-20261024`,
  `/home/chatbot/wainak-dev/backend-auth-phase2`.
- Exact tested additive commit: **`93dd42f2141d551e86ec55861bc66802be247bef`**.
- Parent baseline: `dee6ec30085e3b3e2a12ea25c912967f27f1dcd7`.
- QA worktree/branch: `/home/chatbot/wainak-dev/qa-auth-phase2`,
  `dev/phase2-auth-qa-20261024`. Only additive QA files were changed.
- Additive QA tests SHA256:
  `ff6eacecad780bdbd7abee56d1762c1065f83e24a3eec5251ebacdcab6eb80cd`.
- Additive runner SHA256:
  `f839209a0bf0bd15ef321fed8d108b04904ed84f8cd8a05310a12a9db05088f9`.
- Rerun baseline QA tests SHA256:
  `3dfdd62b71179bc3d0e48abbe8d44d2e5c0cfb04e3766b7f5099e0f1caa2134d`.

The runner requires the expected backend commit and a clean tree before imports
and again after the suite. No result was transferred merely because code shared
a name with the baseline. The original baseline report remains byte-identical:
`phase2-auth-qa-results.md`, SHA256
`567af52200d3e9599755978359055b374c71cf7cee8973c5c3cfa02f69d85b2c`,
originally committed in QA `c3e1b62063e0fcb1b3b809196682db205550fc0a`.

| Check | Evidence | Outcome |
|---|---|---|
| Full disposable suite, independently run | Job `3a7e4eb5-0c01-47aa-9aa8-dfe1d4f91bd1`,08:50:23.898–08:51:38.609 UTC,exit0 | **103/103 PASS**,69.047s unittest |
| Count breakdown |14 PostgreSQL +30 developer identity +16 developer deletion/web +22 baseline QA rerun +21 new independent QA | Distinct cases within this run; old reruns are not described as21 new cases |
| Backend unit/control regression | Job `8e78e588-d96c-42c1-8e57-a2540b6c8c49`,08:52:56–08:52:57 UTC,same clean HEAD | **57/57 PASS**,0.107s; documented-operation coverage is included, not an extra count |
| Phase1 OpenAPI sync / whitespace | Same job/HEAD | PASS; no claim of new phase2 machine-readable OpenAPI coverage |
| Source publication guard | Same job, Git index blobs only |97 files,0 issues; narrow guard, not comprehensive secret/vulnerability scanning |
| Exact-script Node regressions | Local Node **v24.19.0**,08:51 UTC, committed blob copies | **4 mocked-DOM/network scenarios PASS**; not server Node execution or browser E2E |
| Independent cleanup |08:52:57 UTC after terminal completion | PASS; no labeled containers/volumes, owned tempdirs or test runner processes |

This additive independent run passed on its first execution. The earlier
baseline fixture failure remains accurately recorded in the baseline report;
it is neither omitted nor counted as a new failure here.

## Environment and allowed scope

Server `ostath`; all server Git/files/test processes as `chatbot`.
The same isolated Python3.14.4 / Django5.2.18 / allauth65.20.1 identity environment
was used. The harness reported PostgreSQL17.11 and psycopg3.3.6. No new server
package, browser or Node installation was performed for this review.

A fresh owned disposable PostgreSQL container/volume used the existing pinned
image, network=none, no published ports. Only this new DB received schema and
synthetic data. The authorization did not extend to existing DBs, real SMTP,
public hosting, persistent production keys, service/resource/permission changes,
main edits, merge, push or deployment. None was performed by QA.

Before the run, labeled container/volume and actual
`/tmp/wainak-postgres-test-*` inventories were empty. The harness verified its
exact resources were removed. The independent post-run check again found zero
containers/volumes with `com.wainak.disposable-postgres-test`, zero chatbot-owned
tempdirs at that path, and no matching identity/QA runner process.

Both developer and independently authored web round trips used a private owned
WSGI child at `127.0.0.1:0`, a real HTTP CookieJar, proxies disabled and bounded
responses. The QA child reused the reviewed helper, with stop/join and, if
needed, terminate/kill of that exact owned child in finally. Keys and account
proofs stayed in fixture memory. No fake mailbox contents, password, bearer,
verification code or reset link was printed. No operational access was created.

## What was implemented and verified

### Pending registration deletion

`DELETE /identity/v1/pending-account` takes only
`{password, confirmation:"DELETE"}` and the native session header.
It requires an actual current account-bound pending verification state,
the matching persisted unverified active User and current password.
An anti-enumeration fake duplicate-signup state is not ownership. An already
verified user cannot use this route to bypass full-session recent-auth deletion.
Email or a caller-supplied actor field is never authority.

Tests prove wrong password/confirmation, missing or wrong-purpose proof,
expired flow, fake pending state and cross-account retargeting fail closed.
Verification versus deletion is serialized: a verified account is not deleted
by stale pending proof, and deletion does not permit later resurrection.
Injected failure after domain erasure rolls the shared transaction back.
Pending erasure and old-proof revocation remain after an actual DB restart.

### Explicit staged-orphan maintenance

`expire_orphaned_staged_accounts(dry_run=True, after_id=None)` is an internal,
explicit utility, not an endpoint or scheduled job. It uses server time and the
clearly labeled **24-hour synthetic fixture rule**, not an approved production
retention period. It scans at most100 candidates per keyset batch. Callers must
follow `next_after_id` and begin a later sweep fromNone for new candidates.

Verified, younger and currently owned-active accounts are protected. Session
protection uses a User FK plus decrypted current auth-hash or actual recent
pending ownership; email fingerprint alone is not enough. Inspection is
non-mutating, not SessionStore.load/touch. Dry-run row equality, transactional
rollback of identity/domain/security-counter pruning, account-bound protection,
fake-flow exclusion and cleanup/login concurrency were tested.

QA's keyset test injected a batch size of2 with3 real fixture accounts to prove
progress past an entirely active first batch. It is an algorithm/liveness test,
**not** a100-account capacity, load or performance certification.

### Standalone sandbox web deletion surface

The source route `GET /account-deletion` provides an Arabic/English development
page. No persistent/public web service was published. A caller-controlled
`X-Wainak-Deletion-Web:1` marker merely selects a narrower, stricter transport:
an explicit method/path allowlist, matching Origin and real Django CSRF checks
using a deliberately non-exempt sentinel even when downstream app views are
csrf_exempt. Only the CSRF cookie is allowed; cookie authentication remains
disabled. Native requests without that web mode retain their cookie/Origin
rejection.

The CSRF cookie is HttpOnly/SameSiteStrict. Secure=False is explicitly limited
to this HTTP loopback fixture; it is **not** a production HTTPS configuration.
The masked token starts in HTML metadata and refreshes through X-CSRFToken after
login/verification rotation. The account bearer remains only in page RAM, never
a URL or application storage. No-store, nonce-based CSP, self-only connections,
frame-ancestors none and no-referrer were checked.

Positive live HTTP tests performed GET page→login→CSRF rotation→password reauth
→DELETE using one CookieJar without a manual reload. Negative tests reject
missing/wrong CSRF, missing/foreign/mismatched Origin, missing cookie, extra
session cookie, marker spoofing, Authorization/query credentials and routes
outside the web allowlist even with a valid bearer. Web entry and pending proof
retain atomic rate controls.

These are real HTTP/middleware tests and static/Node-script checks; they do
**not** execute the page in a real browser.

## Draft findings closed before this acceptance run

The following were identified during review of the additive draft, not as
production exploits or regressions in the previously verified baseline:

1. **Late-response local credential restoration (P2 draft lifecycle risk).**
   Clearing RAM on pagehide alone did not guard a delayed fetch/JSON completion.
   Final code uses an epoch plus owned AbortControllers, guards subsequent
   auth/deletion actions and prevents a stale operation from clearing a newer
   account. Exact-script tests cover late fetch, late JSON, stale reauth after
   another account signs in, and confirmation reset between accounts.
2. **False orphan protection from fake signup state (P2 retention correctness).**
   A matching email fingerprint was not proof of ownership. Final code checks
   the User link and decrypted actual ownership; independent fake-flow test
   confirms it cannot prevent eligible orphan cleanup.
3. **Repeated first-batch starvation (P2 maintenance correctness).**
   Limiting before skipping active users could repeatedly scan the same batch.
   Final explicit keyset cursor advances; independent small-batch regression
   passed. It still requires an explicit caller to continue a sweep.
4. **CSRF rotation was a design acceptance gate, not a claimed observed
   production vulnerability.** Updated masked-token transport and same-cookie-jar
   positive/negative tests verify the final implementation.

No open P0/P1 bypass was observed in the exercised final sandbox paths.
That bounded statement is not proof that the whole application is secure.

## Acceptance matrix for this additive commit

PASS is limited to the named evidence. PARTIAL/NOT RUN is not a release approval.

| Gate | Status | Evidence / limit |
|---|---|---|
| D2-PENDING-01 | PASS | Actual owned pending session +password+confirmation; successful erasure without false verification |
| D2-PENDING-02 | PASS | Fake duplicate state rejected even with the actual owner's password |
| D2-PENDING-03 | PASS, sampled edges | Wrong/missing/expired/unknown/wrong-purpose proof rejected; exact600-second pending-delete boundary not separately tested |
| D2-PENDING-04 | PASS | Body/header/other password cannot retarget A's deletion to B |
| D2-PENDING-05 | PASS | Fully verified user and other pending session cannot use pending fallback |
| D2-PENDING-06 | PASS | Verification/delete race and sequential old-proof checks; one ownership transition |
| D2-PENDING-07 | PASS | Failure injection rolls back identity/domain and leaves pending verification usable |
| D2-PENDING-08 | PARTIAL | Replay denied after actual DB restart; separate pending-specific fresh HTTP process restart not additionally exercised |
| D2-EXPIRY-01 | PASS | Server timestamp, explicit fixture policy; no public time/age authority input |
| D2-EXPIRY-02 | PASS, tested states |24-hour boundary and younger/verified/current-owned exclusions; fake state does not protect |
| D2-EXPIRY-03 | PASS, named race | Auth→domain serialization and cleanup versus owned login race; not every possible ordering stress-tested |
| D2-EXPIRY-04 | PASS | Dry-run full inspected-row equality, rollback, bounded keyset progress; no capacity claim |
| D2-EXPIRY-05 | PASS, scope | No scheduler;24h clearly synthetic, production retention not approved |
| D2-WEB-01 | PASS, HTTP/source | Non-mutating local page, no-store/CSP/non-reused nonce/frame denial; browser enforcement not exercised |
| D2-WEB-02 | PASS | Marker does not authorize or expand route/method set; valid native profile rejected in web mode |
| D2-WEB-03 | PASS | Actual Django CSRF negative controls with valid bearer and CookieJar |
| D2-WEB-04 | PASS | Non-exempt sentinel, foreign/missing Origin, scheme/port and marker rejection |
| D2-WEB-05 | PASS | CSRF cookie only, cookie auth/Bearer/query rejected; native behavior preserved |
| D2-WEB-06 | PASS | Real owned web login/pending flow and recent-password deletion; no arbitrary-email deletion |
| D2-WEB-07 | PARTIAL | Source avoids application storage/URLs/logging; Node validates RAM clearing/late responses; no browser instrumentation audit |
| D2-WEB-08 | PARTIAL | Four deterministic async/consent mock scenarios; actual keyboard/navigation/interruption/browser UX not run |
| D2-WEB-09 | PARTIAL | Atomic pending-session and web email limits passed; baseline enumeration cases rerun; no full timing/abuse certification |
| D2-WEB-10 | PASS, honest limit | Web password recovery and public store deletion URL are not implemented/approved and are explicitly disclosed |
| D2-WEB-11 | PASS, HTTP+mock | Rotated masked token works without reload; stale responses cannot restore/retarget in exact-script mocked cases |
| D2-RESOURCE-01 | PASS | Fresh owned DB/loopback children and independent terminal cleanup; no existing services changed |
| D2-PROVENANCE-01 | PASS | Exact clean commit before/after, test hashes, terminal job and separate local Node provenance |

## Remaining release gates

- Real browser execution, screen readers,200% text/focus/layout, Android/iOS,
  auth Flutter integration and secure native bearer storage are NOT RUN/not
  implemented for this auth/web milestone.
- No public web deletion URL, actual mailbox/SMTP, web password recovery,
  durable mail outbox, HTTPS deployment, production KMS/rotation, DB-role
  hardening, monitoring or scheduled orphan cleanup.
- Production retention/legal basis, legal holds, backups, billing cancellation,
  moderation/CSAE, D25 evidence, E2EE/chat and store approval remain unresolved.
  Minimal tombstones/receipts/counters and temporary fake-mail snapshots remain
  as disclosed;24h is not a legal retention decision.
- The baseline matrix's other PARTIAL gates are not silently upgraded by these
  additions. New successful cases close named pending/orphan/web-surface gaps,
  not the entire production account lifecycle.

## Reproduction and local Node provenance

Run the server suite only as chatbot with the existing explicit disposable-test
authorization; no external DSN or production credentials are accepted:

```sh
/home/chatbot/wainak-dev/auth-tools-phase2/venv/bin/python \
  /home/chatbot/wainak-dev/qa-auth-phase2/qa/phase2_deletion/run_deletion_independent.py \
  --backend-root /home/chatbot/wainak-dev/backend-auth-phase2 \
  --expected-backend-commit 93dd42f2141d551e86ec55861bc66802be247bef \
  --run-disposable-identity
```

Node was unavailable in the server PATH; no package was installed there. QA
exported only these reviewed committed Git blobs, checked their exact UTF-8 bytes,
and ran the script in a separate local execution workspace using Node24.19.0:

- `backend/tests/test_web_deletion_script.mjs`:
  `5f2aaaed03e4b1f279b9c8f4e706b68bf6a9b96c3959d758693c5797db9d45b2`.
- `backend/wainak_identity/templates/wainak_identity/account_deletion.html`:
  `5fc9b1564f7c6e5dc156a44724ea97f5906c92b137e3bcfe2d05a097a0285f7f`.

Local command: `node backend/tests/test_web_deletion_script.mjs`.
The test extracts the exact inline script and supplies a mocked DOM/fetch; it
creates no real network requests or browser. Its four scenarios are separate
from the103 Python cases, not counted again inside that number.

## New independently authored test catalogue (21)

- `test_fake_duplicate_pending_cannot_delete_the_existing_unverified_owner`
- `test_fake_duplicate_signup_does_not_protect_an_orphan_as_owned_activity`
- `test_live_loopback_web_cookie_csrf_login_reauth_delete_round_trip`
- `test_orphan_apply_racing_owned_login_has_serializable_ownership_result`
- `test_orphan_dry_run_is_read_only_and_boundary_apply_excludes_young_active_verified`
- `test_orphan_fault_rolls_back_domain_identity_and_counter_pruning`
- `test_orphan_keyset_advances_past_a_full_owned_active_batch`
- `test_orphan_maintenance_rejects_non_sandbox_and_non_boolean_apply_flag`
- `test_pending_deletion_failure_rolls_back_both_identity_and_domain`
- `test_pending_erasure_and_revocation_survive_owned_database_restart`
- `test_pending_owner_can_delete_and_old_challenge_cannot_resurrect`
- `test_pending_proof_is_not_retargetable_by_body_header_or_other_password`
- `test_pending_verification_delete_race_has_only_one_ownership_transition`
- `test_pending_wrong_password_confirmation_and_expired_flow_fail_closed`
- `test_verified_account_cannot_use_pending_route_or_wrong_purpose_proof`
- `test_web_csrf_gate_rejects_missing_wrong_foreign_and_cookieless_even_with_bearer`
- `test_web_entry_preserves_atomic_email_rate_limit`
- `test_web_login_rotates_csrf_then_reauth_and_delete_work_without_reload`
- `test_web_marker_cannot_expand_routes_or_enable_cookie_auth_and_native_rule_stays`
- `test_web_page_has_non_reused_csp_nonce_and_private_csrf_cookie`
- `test_web_pending_login_and_delete_require_owned_flow_not_email_only`
