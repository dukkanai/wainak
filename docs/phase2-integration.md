# Phase-two local integration checkpoint

This branch combines the development backend, native Flutter auth UI, and independent
QA history. It is **not a deployment or production approval**. Only synthetic
`@example.invalid` accounts, in-memory fake mail, and disposable PostgreSQL are used.
Real SMTP, production keys/auth provisioning, payment, chat/media, device builds,
store submission, and a deployed deletion website remain outside this checkpoint.

## Preserved source history

- Main baseline: `9102af8606277c80412613e46dd7140d3b8fa663`.
- Backend: `144937a34e88e3b558b0c9a007d36d529c5621a1`.
- Tested mobile application: `482f7de35b795c6c9eaf5a96d8a97c1631b0b6c5`.
- Mobile test-only fixture provenance seam: `40c39c669e71c2050d4e791624468b11be94776b` (includes `0dc290d`).
- Independent QA history and portable legacy runner: `1404dd4eab4e9c4674fd5f1254d754480f63a74b`.

Merge commits preserve these ancestors. Backend Python/SQL/lock/contract and mobile application library bytes must match
their reviewed source commits; backend README/status documentation is updated
explicitly for the combined tree. The integration-specific
changes are documentation and test harness provenance, not new product behavior.
A tracked-file SHA-256 manifest is created outside the tree after freezing the
candidate, then checked again after tests. Independent QA records the exact candidate
commit separately; previous separate-branch PASS results are not integration evidence.

## The exact-backend boundary

Run from the integrated `apps/mobile` directory with explicit, non-secret source paths:

```bash
export WAINAK_BACKEND_ROOT="$(git rev-parse --show-toplevel)"
export WAINAK_IDENTITY_FIXTURE_SCRIPT="$WAINAK_BACKEND_ROOT/backend/integration/serve_identity_fixture.py"
```

The identity test bridge accepts an explicit `script:` argument or this environment
variable, validates an owned regular local source file, and reports its path/hash.
There is no fallback to an older development worktree. These variables convey **no**
password, session, mail code, key, or DB connection. Private mail remains in anonymous
PIPE memory. The legacy API test's backend root must also identify this integration.

The QA Python runners require `--backend-root` and `--expected-backend-commit`, verify
clean exact HEAD before/after, and use only the harness-created database. Run QA overlays
in a separate documented verification worktree; never silently modify the candidate.

## Acceptance gates before a local main update

All required checks are PENDING until an exact-candidate report says otherwise:

1. Git ancestry, upstream blob equivalence, clean tracked-source manifest, publication
   boundaries, syntax/format, contract synchronization, schema-state and dependency checks.
2. Backend unit/authorization tests, independent memory cases, PostgreSQL transactional
   and race tests, auth/deletion/CSRF/retention tests, and all five private PIPE cleanup probes.
3. Cold native Flutter suite, explicit identity live widget/HTTP/PostgreSQL chain,
   legacy memory HTTP and legacy native/widget/PostgreSQL restart compatibility,
   session-generation races, parser and eligibility/pending-account adversarial cases.
4. Existing operations/recovery and original prototype browser/accessibility regressions;
   Node-only deletion-page mock scenarios remain distinct from browser testing.
5. Owned resource cleanup and confirmation that existing DB/services, Mailcow state,
   main, and all unrelated files were preserved throughout verification.

Wasm dry-run compatibility is distinct from an executable Wasm build/browser runtime.
The earlier exact-mobile compatibility follow-up is documented in
[the QA addendum](reviews/phase2-wasm-preflight-followup.md); do not transfer its result
to an untested changed application. No device/store/production readiness is implied.

## Resource policy and isolation

The owner explicitly requested persistent compiler old-generation heap2560MiB and
approved the containing service MemoryMax4GiB. Young-generation flag8 is preserved.
These are ceilings, not reserved RAM, and must **not** be lowered automatically.
Check current host MemAvailable≥4.5GiB before a heavy run; one heavy job at a time.
JS and Wasm checks run sequentially, not Flutter's default parallel dual compiler.
No production DB, real email, persistent credentials, public test ports, or automatic
Mailcow start. Mailcow remains stopped until the owner explicitly asks otherwise.

## Local-only main procedure

A main move requires the owner's authorization, all exact-candidate gates passing,
and the coordinator's verification of the final report. Recheck clean baseline main,
no active Git hooks/filters or deployment watchers, unchanged runtime configuration,
and the exact tested integration HEAD immediately before the operation. If main can
trigger deployment, stop instead of moving it.

Use a **local fast-forward only** to the tested integration commit, so the resulting
main SHA is exactly the tested candidate (no untested merge result). Do not push, open
a PR, alter branch protection, deploy, restart services, or apply live migrations.
The existing GitHub workflow is legacy tests-only and triggers on remote push/PR;
this local checkpoint neither runs nor substitutes for required future GitHub checks.
Remote publication still requires its separately authorized PR/CI process.
