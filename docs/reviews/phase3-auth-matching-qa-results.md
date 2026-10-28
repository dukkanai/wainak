# Phase 3 authenticated introductions — independent QA

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

2026-10-24 UTC. Development-only candidate pair, not an integrated main merge:

- Backend `3bc638f8884cc9d8da586d649f96c34a53476e1b`,
  `dev/phase3-auth-matching-20261024`, `backend-matching-phase3`.
- Flutter `a271d98e47c63931bd3d43cf2404e0ae0d67ca39`,
  `dev/phase3-mobile-matching-20261024`, `mobile-matching-phase3`.
- QA runner/probes at `220a5e346cbe389d2475a5d77e3db945a6a1391c`,
  `dev/phase3-auth-matching-qa-20261024`, `qa-matching-phase3`.
- Common accepted baseline remains main `b5f63ef0090be2513833a86e22c6c7032514c9f7`.

Worktrees are under `/home/chatbot/wainak-dev`. Commands ran as chatbot on ostath.
No main update, push, deployment, existing DB migration or real email occurred.
Scope and negative gates are in `phase3-auth-matching-qa-plan.md`.

## Outcome and scope

**PASS for the bounded development candidate pair above.** No unresolved P0/P1
finding remains in the executed matrix. The same-session post-block P1 was
independently reproduced and closed; a separate live-test root/lifecycle failure
was corrected in test code only, with the original assertions retained and rerun.
This is not production/store approval or permission for a new main merge.

The implemented slice discovers synthetic eligible candidates, creates introduction
requests, distinguishes incoming/outgoing roles, accepts/declines or cancels/ends,
and supports independent metadata report/block. Each actor uses its own framework
session; there is no simulate-recipient UI. Acceptance stops at
`accepted_pending_activation`, with communication permissions false.

Identity-only hints are recomputed and non-authoritative. The actual mutation
rechecks membership, role, eligibility and safety. Current allauth verification
and active-user state are snapshotted per request, before narrowing the domain
schema search path; a stale domain verification mirror alone does not suffice.
Safe decline is exempted from stale-consent rejection only for the exact method,
route and `{decision:"decline"}` payload. Phase1 domain/API code remains unchanged.

## Backend exact-commit execution

Job `0b931dfb-d09c-4f3c-a8b7-03f720e8a38c`,
13:17:51.367–13:19:39.597, exit 0:

| Check | Result |
|---|---|
| Backend unit/control | 68 PASS, 0.180s test time |
| Independent legacy in-memory authorization/race tests | 12 PASS, 0.843s |
| QA exact-source runner guards | 5 PASS, 0.005s |
| OpenAPI artifact synchronization | PASS |
| Publication guard | 245 tracked files, 0 issues |
| Combined disposable PostgreSQL identity/matching QA | 141 PASS,100.139s test time |

The 141-case suite comprises 14 legacy PG + 30 auth + 16 pending-delete/web + 17 new
backend matching tests, followed by the existing 22 independent auth + 21 independent
deletion/web + 21 new independent matching cases. The prior 43 were actually rerun;
old b5 results were not transferred. Related scenarios at different layers are not
claims of 141 distinct threats or comprehensive security coverage.

New independent cases cover recipient/initiator and third-party authority; forged
actor fields/headers; exact public projection; missing/future-policy consent;
strict safe-decline exceptions; underage, inactive and unverified peers despite a
true domain mirror; reciprocal preference/discovery/marital-limit changes;
current-state idempotent replay; concurrent same/opposite requests; accept versus
block/delete races; locked activation and unsupported dialogue routes; durable
terminal-state replay after a real DB restart. Django test-client adversarial
requests use the actual disposable PostgreSQL transaction layer. The inherited
suite additionally exercises actual loopback HTTP/process-restart paths.

The new QA source is `qa/phase3_matching/test_matching_independent.py`, SHA256
`17713855c42e30244ab729e0615c3719c53a44caa29c8cbb39aa8c3e4760666b`.
Runner SHA256 `90468ed60eeacfa1295985a104042097c5d34a1f233996897eabca107faf284e`.
The combined command requires `--backend-root`, full `--expected-backend-commit`,
`--run-disposable-identity --include-existing-qa`; it rejects a dirty/mismatched
candidate and imports fixture helpers from that exact root. It accepts no external
DSN. Raw subprocess outputs were held in RAM; only fixed summaries/test names and
hashes were emitted on failure paths, not private mailbox/assertion operands.

Before/after checks asserted clean exact backend/QA HEADs and zero labeled test
containers, volumes and chatbot-owned `/tmp/wainak-postgres-test-*` directories.
The complete combined stdout/stderr hash is
`4ecfcf5401569989974fb7af24bbbbbebf327383e2472ab89cbf360a422fd177`.

## P1 found, reproduced and corrected

An early uncommitted matching repository used session generation alone. A deferred
list/accept response in the **same** session could restore peer data/actions after
a successful block. This affected the new draft, not accepted main b5.

Baseline repository SHA256:
`a282e61aae0c6a5f8990c1d926f528aab5c5b84c2a1032c2305e7096d753207f`.
The independent pure-Dart injected-transport probe reported three failures and one
410-session control pass in `fd349cd6-54ea-423b-9fa2-84f4d50b9fc1`,
12:49:42.721–12:49:43.557. Safe fixed diagnostics specifically confirmed restored
relationship/actions, accepted peer and candidate after block acknowledgement.

The fix adds a matching mutation barrier and per-list read sequence, retains
uncertain intent keys, and stamps candidate/safety contexts with actor/generation.
Successful block clears projections immediately even if an older action is pending;
older actions/read results cannot repopulate them. Business report410 does not
expire authentication. The parser also rejects card permission outside valid
legacy active/exclusive state or with null peer; this UI exposes no card action.

The **unchanged final probe** SHA256
`1de4c4259a5e36fc4e19a586a050ebfb654f6a6e4b81be461baf7e65ebb6e1de`
passed 4/4 on committed 53c73627 core blobs in job
`76302cd1-f351-4c23-8325-08db3aea73cc` at 13:17:26, and again on 68e06c8 and the final a271d98
snapshots; the final execution is described below. Final repository SHA256
`3865ed344c881b63fa7876220e91ec17553b087be74abc54ea450b79001af35e`;
client SHA256 `b577710ca3e56169a9e35df267b1af7eaa6cd578f9c7c342d341a9836415aecc`.
This closes that specific P1; it is not a generic claim that all races are solved.

## Independent cold Flutter and lifecycle checks

Fresh detached worktree `/home/chatbot/wainak-dev/qa-mobile-matching-a271d98`,
with no project `.dart_tool` or `build` before `pub get --offline`. The isolated SDK
and package cache were reused; this is a cold project/kernel build, not a cold
SDK installation or dependency-network test.

Final combined cold/live job `8932ed86-11ad-44b4-81ab-0f7619abeb6e`,
13:35:33.104–13:38:08.695, exit 0 (cold-suite command 54.435s):

| Check | Result |
|---|---|
| Offline resolution | PASS |
| Flutter analyzer | PASS, no issues |
| Full cold default suite | 56 PASS; 3 explicit live opt-ins skipped |
| Independent matching deferred-response probe | 4/4 PASS |
| Independent pending-flow races | 3/3 PASS |
| Independent actor/session/confirmation races | 6/6 PASS |

The full suite includes one aggregate containing 12 new typed-matching checks and
8 new matching widgets; the aggregate's 12 inner checks are not 12 additional
Flutter test cases. It also reruns prior auth/legacy widget tests, including
RTL320px/200% text, semantics and busy keyboard behavior. The three live opt-ins
are tracked explicitly rather than counted as passed.

Two final presentation corrections are included in 68 and preserved in the tested final a271 commit: the UI
no longer falsely says assessment completion is a server discovery prerequisite,
and incoming requested state says the decision awaits **you**, not the other party.
Recipient widget assertion passed on the corrected source. Discoverability defaults
false and has an explicit user checkbox. Confirmation captures the originating
repository and stamped target; navigation does not silently retarget another account.

All 116 tracked mobile files were hash-verified unchanged before/after the cold job.
One disclosed QA-only untracked overlay exists outside the app test directory:
`qa/phase3_matching/matching_race_probe.dart`, with the exact SHA above. No tracked
application code was edited in the test snapshot.

## Actual native HTTP / PostgreSQL widget journeys

The same final job then executed two separately opted-in journeys against the
explicit fixture from backend 3bc638f:

| Journey | Exact result |
|---|---|
| Existing identity onboarding/session/revocation/deletion widget regression | 1 PASS; 48.569s command |
| New two-actor matching/retry/recipient-acceptance/safety widgets | 1 PASS; 45.266s command |

Both printed the selected fixture path
`/home/chatbot/wainak-dev/backend-matching-phase3/backend/integration/serve_identity_fixture.py`,
SHA256 `83194285de3d16759536009c9a6ba9ebb73f272291487911d1dcf5930b181177`.
The fixture imports the exact frozen backend root, not an older worktree. Passwords,
verification codes and temporary keys remain in RAM/private anonymous pipes; no
HTTP mailbox/admin endpoint is introduced. The database is fresh, network-none
and has no published host ports. These are actual native-loopback HTTP/framework/
PostgreSQL journeys driven by headless widgets, not physical-device E2E.

Matching uses two independently registered and verified framework sessions. It
forwards a real request to the server, intentionally drops exactly one response,
then verifies retry reused the same key and created only one relationship. The
initiator's direct acceptance is rejected, the recipient confirms through its own
UI, and acceptance leaves all communication locked. Reporting does not block;
blocking redacts the peer; the blocked peer can still submit metadata reporting.
All four fixed stage markers were reached, ending at blocked-peer reporting.
No recipient response or relationship state was fabricated by the transport seam.

Identity live test SHA256:
`a6dda9a2882ca4f4015861b12cfc3a1dd664e9a626044dead52f878b71c23d87`.
Matching live test SHA256:
`7bba72456e68fd1b834e45cf33af139e6d393b6c77cd6fbe5d42572cb60f923c`.
The fixture's repeated PG prerequisites are not additional unique mobile cases.
The matching widget does not itself restart the server mid-journey; durable
matching-state/replay restart coverage belongs to the separate backend tests.

### Failure history, not silently converted to success

An earlier independent cold run on 68e06c8 passed 56 / 3 skips, and its identity live
regression passed. The new matching live test failed before the first matching
interaction in job `27f844f4-35a3-4fd4-9d51-8a8e9f0eca4d`, ending 13:28:01.
A safe-diagnostic rerun `71dca0d5-cc0b-4c3a-bf7f-698aa5ef5b3d` reproduced the same
failure at 13:31:10, with test-root mount/first-navigation finder stack lines 176,
188 and 80. Cleanup passed after both failures; private operands were not emitted.

Commit a271 changes only the live test: explicit RTL Directionality above the
IndexedStack, settling initial hydration before the first tap, and four fixed
non-sensitive phase markers. No application/client change or assertion removal
was used to obtain the pass. The final cold suite and **both** live journeys were
then rerun on that exact new commit, rather than inheriting the prior results.

## Privacy boundary and remaining limits

No selected dialogue-card ID, answer, couple progress, transcript, ciphertext
queue, send/history/outbox/media endpoint or implicit report attachment was added.
Unknown dialogue payloads are rejected and the independent DB-domain snapshot
remains unchanged. This targeted assertion is not proof about every possible log;
source/schema review and the absence of new dialogue transport are separate evidence.
Matching assessment answers remain the separately declared account-data purpose.
D25 evidence upload remains disabled. There is no payment or entitlement override
in the identity HTTP API and no card-opening button in this client.

Candidates cap 20; own relationship lists currently return all records without
pagination. The allauth verification snapshot also queries all active verified
accounts. Both are documented small-sandbox limitations, not production scalability
or fairness guarantees. Production email delivery/recovery infrastructure, HTTPS,
KMS/rotation, secure mobile token persistence, payments/refunds, E2EE/relay/device
outbox, moderation/CSAE operations, approved retention and public account-deletion
hosting remain outside this implementation. Mailbox ownership does not prove age,
legal identity or trust in a conversation device.

No physical Android/iOS release/device, native screen reader, Flutter web/browser
runtime or new Wasm build was executed for this phase. Earlier Wasm evidence applies
to its explicitly documented previous source, not automatically to these changes.
Publication scans are narrow index-pattern checks, not a complete secret/advisory
or penetration-test certification. Dependencies did not change in this slice;
no new external dependency/CVE audit is claimed.

## Final source and cleanup audit

Audit job `2586df32-50f7-4310-9ced-a83ffd3871ee`,
13:39:14.793–13:39:18.630, exit 0, independently verified:

- All 245 backend tracked blobs equal 3bc638f; all 249 tracked blobs in the author
  mobile worktree and detached QA snapshot equal a271. Both author trees are clean;
  the snapshot has exactly the one disclosed QA-only probe overlay.
- Zero labeled test containers, volumes, owned actual/tmp test directories, and
  owned matching fixture/compiler/tester processes. No unrelated resource removal.
- Original wainak DB health remains healthy; all 18 Mailcow containers remain exited.
- Main remains clean at b5f63ef. The permanent compiler wrapper hash remains
  `1d444483788a88fef0ab11c28e9f0b46c5f40bb65a027fa3afef635ade643978`.
- Mobile source publication 249/0 and QA source publication 248/0 before adding this
  report; the backend publication 245/0 is recorded above. These remain narrow guards.

Final machine-readable artifacts are under
`/home/chatbot/wainak-dev/phase3-qa-evidence/a271d98e47c63931bd3d43cf2404e0ae0d67ca39/`:
- `final-cold-live-result.json`, SHA256
  `d9d92b70be24428c31c02818bd8085da7009020ffa993a43510a679f62722f80`.
- `source-manifest.json` (116 mobile files), SHA256
  `4fc57aefdc84fa595965cd58369cc7664be0e6fae1e1a8f8bea955ce561919ff`.
- `final-audit.json`, the exact source/resource readback summary.

The heavy window was explicitly released after this audit. No additional compile,
resource-limit change, main update or deployment is scheduled by this reviewer.

One heavy job ran at a time, with host MemAvailable ≥ 4.5 GiB checked before each phase.
Permanent owner 4 GiB / compiler 2560/8 MiB settings were preserved, not rolled back, and
Mailcow remained off. Only new owned disposable test resources were used.

The earlier QA save/commit denial occurred before execution; one allowed retry
was also denied. The operation remained stopped until the user's specific 13:13:46
approval for QA files/local Git/disposable tests, then the same guarded operation
succeeded in job 5e536311. No substitute writer, alternate route or main mutation
was used. This is an authorization history, not a technical test failure.
