# Phase3 bounded implementation plan

Baseline: locally integrated main `b5f63ef0090be2513833a86e22c6c7032514c9f7`.
Work occurs on separate backend/mobile/QA development branches. No main merge,
remote push, deployment, live DB migration, real email or new persistent key.

## Gaps to close

1. Connect existing native identity state to profile/preferences/assessment,
   candidate discovery, outgoing requests and a recipient's own incoming inbox.
2. Add fresh identity-only direction/action hints and make strict recipient decline
   available with stale consent, without weakening acceptance or role checks.
3. Independently test auth-backed reciprocal eligibility, request/rate/idempotency
   races, stale state, block/report/delete, session loss and database restart.
4. Stop the product journey truthfully at accepted_pending_activation. Payment,
   card transport and server conversation storage are not implemented here.

The initial base-class review suggested a peer-consent gap; deeper review found
IdentityDomainService already enforces current consent for both participants and
hides stale-consent peers. That is existing protection, not a newly fixed flaw.
Phase1 DevelopmentService/DTOs remain unchanged.

## Data-flow inventory

| Data | Allowed destination in this slice |
|---|---|
| synthetic auth secret/email code | existing encrypted/digested session store and private test mailbox PIPE; never logs |
| profile, preferences, initial assessment answers | existing account/matching repository; private owner reads |
| candidate projection | allowlisted peer fields only, derived from current eligibility |
| request, consent, block, report metadata | existing transactional state/receipts; no free text/evidence |
| direction/action hints | computed response only; no new persistent table |
| dialogue selection, answers, results, ciphertext | **not accepted, transmitted or stored** |
| payment entitlement | **not provided by this slice** |

Detailed contract: ../contracts/phase3-matching.md. Static authored cards differ
from the personal act of selecting/answering one. D16/D17 do not permit relabeling
that act as harmless metadata or storing ciphertext on the server. D25 remains an
explicitly deferred evidence exception, not general messaging permission.

## Verification gates

- Existing backend68 unit/control and60 built-in PG/identity/deletion regressions.
- New authenticated role/action/consent/safety/privacy/race/restart tests, then
  independent QA on exact commits. Test fixtures remain synthetic and disposable.
- Native client/widget async boundaries and actual UI→HTTP→Django→temporary PG,
  with both parties authenticated through fake-mail proof, not client impersonation.
- No public activation, content upload/history/outbox or evidence endpoint; no new
  DB schema for dialogue and no dialogue content in persisted fixture snapshots.
- Source hashes, clean branches, ephemeral-resource cleanup, existing DB/services
  intact. Fixed owner4GiB/compiler2560MiB/young8 remain; one heavy job and≥4.5GiB
  host MemAvailable preflight. Mailcow stays stopped.

This is a development acceptance plan, not production or store certification.

### Author draft verification, 2026-10-24

Job `cf2b3038-89c8-4e7d-a9ef-c2ea64e6f785` finished12:46:55UTC with exit0:
68 unit/control tests, phase1 contract synchronization and77 built-in isolated tests
(14 legacy PostgreSQL +30 identity +16 deletion/web +17 matching) passed. Counts
overlap prior regression suites and are not an aggregate unique-test total.
The matching cases include independent-session roles, stale-consent safety decline,
authoritative verification/inactivity, underage redaction, idempotency and accept/cancel
races, database restart, block/delete/revoke, and rejected dialogue payloads.

Evidence is the coordinator's external `phase3-backend-evidence/draft1-20261024T1246.json`,
SHA256 `4c5be2b6fdea0bb8880546a8ceaf84a0790042637c784aa1056dbbe31d4aaebe`.
It binds the tested draft source hashes, not a claimed future commit. Pre/post owned
container/volume/actual `/tmp/wainak-postgres-test-*` inventories were empty; original
database stayed healthy. A preceding coordinator output-summary regex failed before
any PG launch; after correcting that wrapper, the complete test run above passed.

Independent exact-commit QA and the new Flutter matching journey remain pending.
No phase3 merge into main, production release, dialogue or entitlement acceptance
is implied by these backend results.
