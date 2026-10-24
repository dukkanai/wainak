# Phase 4 local card preview — independent QA acceptance plan

2026-10-24. Baseline main: `5f3433b23d8a29999c24943414ff1fdbcc40f46d`.
Design plan drafted before execution; exact runtime results belong in a separate commit-specific QA report.

## Permitted slice

A development-only, explicitly enabled, standalone demonstration of a static
Arabic card catalog and allowlisted answers. One in-memory draft/preview at a
time. It is not an authenticated relationship, entitlement, message delivery,
conversation history, local outbox, encrypted store or E2EE implementation.

D16/D17 distinguish static public catalog data from a person's act of choosing or
answering a card. The latter is dialogue content and may not be relabeled as
ordinary server metadata. D25 is optional explicit report evidence, not permission
for automatic capture; uploads remain outside this prototype.

The proposed sample limits (Arabic only, no more than 12 cards, 2–5 responses per
card) are implementation bounds for this demonstration, not approved permanent
product/content limits. Static sample copy must not claim diagnostic/scoring value.

## Gates and independent tests

| ID | Gate | Planned evidence |
|---|---|---|
| LC-01 | Development opt-in defaults off; release builds refuse the demo. Identity and real relationship modes do not reach it or change entitlements. | Entry-point source review; enabled/disabled/release-gate unit/widget checks. A unit flag probe alone is not a real release build. |
| LC-02 | Catalog/card/response IDs are unique, nonempty and bounded; responses belong to exactly their card. Unsupported locale, malformed version identifier and malformed catalogs fail closed. The static sample has no untrusted version loader. | Table-driven valid/invalid input probes with runtime checks, not `assert` alone. |
| LC-03 | Catalog and exposed state are deeply immutable. | Attempt mutation through original input lists and returned getters; source inspection for copied/frozen nested lists. |
| LC-04 | A lease binds controller identity, catalog version, card and current epoch/revision; it is not a real credential. | Cross-controller, cross-version, previous-card and previous-session lease rejection, including equal numeric epochs and equal IDs. |
| LC-05 | Unknown/mismatched card/response/lease input cannot partially mutate current state. | Snapshot state before invalid calls; require equality afterward and fixed non-content-bearing error categories. |
| LC-06 | Only one card/answer exists in current draft. Selecting a different card clears the old answer; no answer history, progression score or replay log exists. | State-transition tests plus field/source inspection. Static catalog arrays are not a user transcript. |
| LC-07 | Repeated selection/preview has no extra action, delivery, accumulation or navigation. | Repeat action with current/stale leases; explicit idempotent or rejected outcome, never a second message. |
| LC-08 | Start is legal only from locked, clear/invalidate resets to locked and resets acceptance, disposed is terminal. | Transition matrix; repeated start/reset/dispose; no resurrection from callbacks. Return-to-catalog may preserve only the current local-only acceptance, never a draft. |
| LC-09 | Leaving/hiding the demo or losing foreground invalidates leases and removes draft references. | Host source review, route/back/mode/tab/lifecycle widget probes; do not rely solely on dispose for retained routes. |
| LC-10 | No HTTP/API/IO/storage/restoration/clipboard/share/push/analytics dependency or content serialization/logging exists. | Module and host import/dependency/call-site review, tracked diff/publication guard. A text scan alone is insufficient proof about arbitrary OS capture. |
| LC-11 | UI always states local preview and not sent; no partner acknowledgement, delivered/read/typing indicator, simulated real safety action or encryption claim. | Copy/widget assertions and review of all stages/errors. |
| LC-12 | Arabic RTL, 200% text, focus/semantics and interrupted navigation remain usable without retaining sensitive draft state. | Bounded widget checks when authorized; actual VoiceOver/TalkBack/device behavior remains not run unless explicitly tested. |
| LC-13 | Existing identity/matching behavior remains unchanged. | Exact-source diff, relevant regression tests and separate test-scope report. No old result automatically transfers to modified code. |

## Cleanup and honest privacy language

Clear/dispose removes application references and hides the preview. Dart garbage
collection does not establish cryptographic zeroization or deletion from RAM,
OS snapshots, crash dumps or screenshots. These platform limits must not be
represented as solved. No persistent cryptographic key or new provider is needed.

A synchronous pure-Dart controller is preferable; any asynchronous continuation
introduced by the host must retain the originating lease/revision. Invalidating
a controller due to `sessionChanged` or `safetyBlock` in tests is only a seam;
it is not proof of a live authentication/safety integration in this standalone mode.

## Stop conditions / excluded scope

Stop and seek a separate reviewed design before adding message transport, selected
card/answer persistence, server queues, notification payloads, device keys/backups,
report attachments, real relationship entry or entitlement activation. Current
API acceptance remains `accepted_pending_activation` with communication locked.
Do not merge main, push or deploy in this phase. Keep permanent owner 4 GiB and
compiler 2560/8 MiB, Mailcow off, and one coordinated heavy test job at a time.

Acceptance requires an exact candidate commit and explicit PASS/FAIL/NOT RUN
results with source provenance, not this plan or a static design approval alone.
