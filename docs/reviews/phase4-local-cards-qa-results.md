# Phase 4 standalone local card preview — independent QA

2026-10-24 UTC. Candidate `acbc72a78074bf3be3628dc8dff10a54c9dcecde`,
`dev/phase4-local-cards-20261024`, `/home/chatbot/wainak-dev/mobile-local-cards-phase4`.
Baseline main remains `5f3433b23d8a29999c24943414ff1fdbcc40f46d`.

## Scope and privacy boundary

This is an explicitly enabled, development-only, standalone preview, not a
relationship conversation. Four illustrative Arabic-fusha cards have predefined
responses including deferral. There is no free text, scoring, delivery or partner
response. The sample is not a finalized content library or psychological measure.

Static catalog source differs from a person's act of choosing/answering a card.
Under D16/D17 the latter cannot be disguised as server metadata or automatically
stored on the server, even as ciphertext. This slice keeps one choice only in
application RAM, adds no IO/API/storage/restoration/clipboard/share/push/analytics
or serialization dependency to its module, and exposes no send/history/outbox.
D25 report attachments remain outside scope. It does not change real entitlement
or open `accepted_pending_activation` relationships.

Source review preceded execution. `catalog.dart` uses only `dart:collection`;
`controller.dart` imports only its catalog. The host imports Flutter/localizations,
the existing theme and these local modules. `main.dart` adds a separate
`local_cards` branch after the existing developer opt-in gate, passing actual
`kReleaseMode` into a fail-closed predicate. No account, relationship, API client or
persistence object reaches this mode. Existing backend/contracts and dependency
manifest/lockfile were verified unchanged from main.

The controller is synchronous. Runtime validation, final models and copied
unmodifiable nested lists enforce allowlists and bounded sample data. View tokens
bind controller identity, catalog version, revision and card. Every state-changing
callback captures its rendered token, including start. Invalid input is atomic;
exceptions/string diagnostics omit chosen values. Clear/invalidate removes the
card, answer and acknowledgement regardless of token, and dispose is terminal.

The host invalidates on route cover/pop, system Back, non-resumed lifecycle,
explicit visibility/scope change and disposal. Future embeddings must supply
visibility/scope accurately: a retained hidden tab is not detectable by dispose
alone. Enum hooks named session/safety invalidation are not live auth/block wiring.
Clearing drops references, not cryptographic zeroization; Dart/OS memory, crash
snapshots and screenshots are not guaranteed erased or prevented.

## Independent execution

An initial source-hash-only 22-case pure-Dart probe passed in
`af2e936f-0648-4d50-9036-62b4ebe8e936` at 14:26:14, without Flutter/network/DB.
That draft evidence was not substituted for the final candidate tests below.
Core hashes remained:

- Catalog: `4db0a07b59e64a7d092720fba48ddd80d5f7e2b02f428ea53af7b42447e140d5`.
- Controller: `407c19b49640d6df10db5c341fd48323ffd005bf53dff0dbe848462052b85e07`.

Final job `93f98340-b809-46ec-bc4c-a1828b3e400c`,
14:38:01.501–14:39:33.359, exit 0. All operations ran as chatbot on ostath.
A new QA worktree/branch, `qa-local-cards-phase4` /
`dev/phase4-local-cards-qa-20261024`, started at the exact candidate. The project
`.dart_tool` and `build` directories were absent initially. Existing isolated
SDK/package caches were reused: cold project/kernel, not cold SDK installation.

| Check | Result |
|---|---|
| Offline package resolution | PASS |
| Flutter analyzer | PASS, no issues |
| Cold default Flutter suite | 67 PASS; 4 explicit opt-ins skipped; 60.997s |
| Independent pure-Dart controller probes | 23/23 PASS; 0.526s |
| Independent host/default-entrypoint widget probes | 3/3 PASS; 6.860s |
| Explicit enabled local-only entrypoint | 1 PASS; 16.831s |
| Indexed-source publication guard | 266 files, 0 issues |

The default skips were the existing three live backend journeys plus the explicit
local entrypoint; the latter was subsequently run separately. No skipped backend
journey is counted as passed. The controller/widget probes and explicit entrypoint
ran after the default suite using that QA worktree's warmed project cache; only
the default suite is labeled cold. No source assertion failed in this final run.

The final independent controller probe has 23 named cases; it adds a direct
current-view predicate test to the earlier 22, without weakening them. It covers
mode flags, catalog validation/bounds/deferred choice, deep immutability, atomic
invalid inputs, cross-controller/version tokens, stale start/answer/preview,
repeat actions, card changes, all invalidation reasons and disposed-state behavior.
It is a pure Dart test, not proof of a platform lifecycle or actual release build.

The three independently authored widget probes verify:
1. Actual default `main()` renders the disabled build without developer opt-in.
2. Old answer/preview callbacks cannot target a new card after route cover/pop.
3. Old checkbox/start callbacks cannot alter a fresh acknowledgement or restore a
   preview after background/resume.

The developer's local widget cases were also independently rerun as part of the
full default suite: explicit boundaries, no text input, clear/reentry, back,
route cover, host visibility/scope, stale callbacks, and Arabic RTL at 320 logical
pixels/200% text with semantic actions. The 15 inner developer controller checks
form one aggregate Flutter case; they are not 15 extra cases added to the suite
count. Test counts across layers are not distinct threat counts.

Independent probe sources:
- `qa/phase4_cards/card_controller_probe.dart`, SHA256
  `fdfb6f2f14b26a081cb67a8e55e1f59ed3fb1e6de6480bbf49451acc3ee1af5b`.
- `qa/phase4_cards/local_cards_independent_widget_test.dart`, SHA256
  `1b95c09e56255379f9c6b3f526508e60e7b51f4fce23b43ec86249a695c0588f`.

The widget probe was copied to one disclosed untracked app-test overlay only for
its execution, verified by SHA, then removed in `finally`. Its canonical QA source
remains outside app code. No tracked candidate file was modified. The default cold
suite ran before that overlay was added. The explicit local entrypoint used only
`WAINAK_DEV_MODE=true` and `WAINAK_REPOSITORY=local_cards`; all real backend/live
fixture opt-ins remained unset throughout. No PostgreSQL or mailbox fixture ran.

## Source and cleanup audit

Independent final audit `02444193-6dd4-4d83-aaeb-dee531cd5e85`,
14:40:47.248–14:40:47.703, exit 0, verified:

- All 266 candidate tracked blobs (123 under `apps/mobile`) match the commit in
  both author and QA worktrees. The author worktree is clean. Before report save,
  the QA worktree had only the three disclosed untracked plan/probe files.
- Exactly eight intended paths differ from baseline: main entrypoint, three local
  module files, local documentation, two test files and the verification tool.
  Backend, contracts, identity/matching implementations and dependency manifests
  are unchanged. Module import allowlists match the reviewed design.
- The temporary app-test overlay was hash-verified and removed. No compiler or
  Flutter tester remained; labeled test containers/volumes/owned temp directories
  were empty. This phase never requested a PostgreSQL fixture.
- Main is still clean at 5f3433b. Original `wainak-db-1` remains running/healthy;
  all 18 Mailcow containers remain exited.
- Owner MainPID 3460430 / NRestarts 5 and permanent MemoryMax 4294967296 unchanged;
  `oom` and `oom_kill` counters are zero. Compiler wrapper SHA256 remains
  `1d444483788a88fef0ab11c28e9f0b46c5f40bb65a027fa3afef635ade643978`.

One heavy job ran at a time; host MemAvailable ≥4.5 GiB was checked before each
phase. The heavy window was explicitly released after this audit. No automatic
resource rollback, main mutation, push or deployment was performed.

Evidence directory:
`/home/chatbot/wainak-dev/phase4-qa-evidence/acbc72a78074bf3be3628dc8dff10a54c9dcecde/`.

- `result.json` SHA256:
  `c6046bc056053c65bcbcec2ebb69a44c47dfa84cd2243211d2ea0f2a69b54d9c`.
- `source-manifest.json` SHA256:
  `654090803ac5d8318d5ac16eb5f839d448d91909e00b7c627628a07fbce1c75f`.
- `final-audit.json` SHA256:
  `9b9fc5b2096d7b08c5edb90fdbacaada00b1bcc3fb0e5477d81dd434d89158e8`.

The report/plan and two canonical probes are committed separately on the QA branch;
no candidate app file was edited during QA. Publication guards are narrow indexed
pattern checks, not a complete secret or penetration-test audit.

## Outcome and limits

**PASS for the bounded local-only development preview on this exact candidate.**
No unresolved P0/P1 finding remains within the executed LC-01..13 matrix. The
release/device parts of LC-01/LC-12 are explicitly unrun as listed below; the result
is not a release/store/security certification or authorization for a main merge.

Actual Android/iOS release/device builds, VoiceOver/TalkBack, browser/Wasm runtime,
OS memory/snapshot guarantees and production packaging are NOT RUN. A boolean
release predicate plus source review is not a tested release binary. Existing
identity/matching widgets reran, but their live HTTP/PG suites and backend tests
were not rerun for this UI-only slice; backend/contracts were byte-unchanged.
No new external dependency/CVE audit, library-wide editorial approval, encryption,
secure local persistence, transport, entitlement activation or store approval is
claimed. Any future persistence/transport or real relationship integration needs
its own reviewed design and exact-version tests before implementation/acceptance.

The developer first corrected formatting before widget execution; that was not an
application assertion failure. Our final operation was initially denied before
execution because authorization was not associated with this project. Parent then
provided the actual user's broader 13:18 continuation authorization, enabling one
retry. That retry hit connector command-length validation before any job; only
file-data transport was compressed, retaining identical file hashes and visible
operation/guards. No alternate writer or permission bypass was used. The normalized
operation then ran under the same development scope. These authorization/schema
stops are not product test failures.
