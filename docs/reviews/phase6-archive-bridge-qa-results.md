# Phase 6 — independent synthetic Go archive bridge QA

2026-10-24, ostath. **Host Go feasibility accepted within the bounded synthetic
scope below. Android/JNI/AAR/unsigned APK acceptance is NOT established.**
No main merge, push, deployment, signing identity, real history, real recovery key,
cloud provider, device, emulator, adb or KVM action was performed by this QA.

## Exact source and provenance

- Candidate: `5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff`, branch
  `dev/phase6-archive-bridge-20261024`, worktree
  `/home/chatbot/wainak-dev/archive-bridge-phase6`.
- Candidate adds seven `archivebridge/` files. All 24 `archive/` files are byte
  identical to `8155772cf0a006078be433f45353c651d9ffe451`.
- Facade `archivebridge/bridge.go` SHA-256:
  `3cf7dcf2f25454bcf3c16dd3a6189382babcb93fe7fb2913a60383aeb48df415`.
- Final independent test source: QA commit
  `4e63016cdd540e89f83a5816a93fd12fd9df7f01` on
  `dev/phase6-archive-bridge-qa-20261024`, worktree
  `/home/chatbot/wainak-dev/qa-archive-bridge-phase6`.
- Test path `qa/phase6_archive_bridge/bridge_independent_test.go.txt`, SHA-256
  `16175d21a67563803c57b6c14fc0714959a1be4c893bfe48766227359a493603`.
  A temporary Go overlay introduces this same-package test file without changing
  candidate files. The runner verifies the imported core resolves to the exact
  candidate root, not another worktree.
- The final audit rehashed all 290 candidate and 295 QA tracked files against
  their committed blobs. Both worktrees were clean. Main remained clean at
  `5f3433b23d8a29999c24943414ff1fdbcc40f46d`.

## What this facade actually implements

The only exported constructor is `NewSyntheticSession()`: ephemeral upstream age
X25519 key generation in RAM, private fixed sample catalogue and synthetic owner.
No public key-string import/export, real account/catalogue input or persistent
key custody is exposed. The remaining proposed binding surface uses int64,
byte slices and ordinary error returns: Epoch, ExportHistory, ImportHistory,
HistorySnapshot, Cancel(handle, expectedEpoch) and Close.

The registry caps live/opening sessions at eight and actual work at two, with one
operation per session. Key generation reserves capacity first. Closed/cancelled
workers retain their work slots until actual completion. Handles never reuse;
epoch/handle overflow fails closed. Crypto runs outside the registry lock;
import's current-scope check and atomic RAM commit share one lock. Cancellation
after a completed commit does not undo that commit.

Input/output limits remain 1 MiB plaintext, 2 MiB ciphertext and 2,000 records.
History rows are imported/untrusted and never restore live identity, trust,
entitlement, delivery, ratchet, consent or outbox state. Owner matching is not
proof of authorship. Clearing references is not secure zeroization or protection
against OS paging/dumps. Handles are in-process scope guards, not authentication
against malicious code in the same process.

## Independent runtime results

| Gate | Result on exact candidate |
|---|---|
| Candidate facade suite | PASS: 12 top-level tests plus 17 hostile DTO subcases |
| Unchanged archive regression | PASS: 14 core/CLI top-level tests, including authenticated EOF, wrong key/owner, truncation, replay, atomicity, output faults and same-upstream CLI interop |
| Bounded fuzz | PASS: separate 10-second archive-open and strict-JSON fuzz targets; public synthetic seeds only |
| Independent facade tests | PASS: 17 top-level tests plus six cancel/close subcases |
| Compiler/module/static checks | PASS: candidate format, module verification, vet; independent overlay vet; publication scans |
| Source provenance | PASS: exact candidate/core/QA blobs and local module replacement before and after |
| Source advisory scan | Completed; three disclosed module-only findings, no package/symbol finding in this source graph |
| Process/temp/runtime audit | PASS: owned temporary directories empty, no owned compiler/crypto processes, unchanged runtime metadata |
| Go race detector | NOT RUN: required C toolchain unavailable; deterministic concurrency tests are not a substitute |
| gobind/JNI/AAR/unsigned APK | NOT RUN/BLOCKED: Android SDK acquisition returned official-endpoint 404; API-shape review is not a native build |
| Android/iOS/device runtime | NOT RUN; no device/emulator execution or native loading claim |

The 17 independent tests cover:

1. Public synthetic roundtrip and idempotent Close.
2. Invalid/closed/extreme handles and incorrect epochs.
3. Eight-context capacity, nonreuse and handle overflow.
4. Concurrent constructor reservation before key generation.
5. Epoch overflow closes the context.
6. Closed workers retain both global and per-work capacity until completion.
7. Cancel preserves the occupied per-handle slot; stale cancel cannot affect the
   newer epoch.
8. Export owns its bytes after copying; later caller mutation cannot retarget it.
9. Import owns ciphertext after copying; later caller mutation cannot corrupt it.
10. Returned snapshot bytes do not alias retained history.
11. Export/snapshot publication is suppressed after Cancel or Close (four cases).
12. Cancel/Close before import commit wins atomically (two cases).
13. Already committed history survives cancellation without rollback fiction.
14. Same-key fixtures still reject a foreign owner and a divergent same-version
    catalogue; the test is not merely a wrong-key rejection.
15. Tamper, truncation, appended ciphertext and replay leave prior history intact.
16. Decoded duplicate/unknown/authority fields, invalid types, malformed UTF-8,
    lone surrogate, noncanonical time, invalid choice, record/input caps reject.
17. Returned history projection has only the fixed allowlisted fields and
    imported=true/authenticated_author=false annotations.

Test hooks are unexported, nil on the public singleton and assigned before worker
execution. Assertions and persisted results contain fixed labels, not keys,
plaintext or ciphertext. Inputs must not be concurrently mutated while a
synchronous Go call is initially copying them; tests mutate only after the
synchronized after-copy stage. Real JNI array-copy semantics remain untested.

## Failed attempt, accurately classified

Initial QA commit `97bf1da2920be1e6c552cb6e9240b403dcb4dc6e` had an invalid test
fixture: its alternate catalogue supplied one response, while the unchanged core
requires two to five. The test failed at `fixture catalog`, before the intended
cross-owner/catalogue assertion. The other 16 independent top-level tests passed.
A diagnostic rerun confirmed that exact fixed failure label. QA commit `4e63016`
added a second alternate response only; no product source changed and no assertion
was removed. All 17 tests then passed. The failed evidence is retained separately.

## Advisory and dependency limits

The final candidate's source+test scan used the existing pinned govulncheck 1.9.0
binary (SHA-256 `4907a1e5eaae5e3c5b6a120173916b011ea23a0c1c83be8b4f8a09a2a7f69691`),
Go 1.27.3 and official database snapshot modified `2026-10-21T00:27:29Z`.
Fourteen module graph entries include two local modules and twelve external
modules; 172 source/test packages were enumerated. The graph imports no SSH or
OpenPGP package. Existing core dependency notices are unchanged, not a new legal
opinion or full Android dependency review.

Three findings remain in pinned `golang.org/x/crypto v0.55.0`:

- [GO-2026-5932](https://vuln.go.dev/ID/GO-2026-5932.json): unmaintained OpenPGP.
- [GO-2026-6354](https://pkg.go.dev/vuln/GO-2026-6354) and
  [GO-2026-6355](https://pkg.go.dev/vuln/GO-2026-6355): SSH issues, fixed upstream in
  v0.56.0. This change did not silently upgrade dependencies.

These are module-only findings in this exact source graph, with no package or
symbol trace. That is bounded non-reachability evidence, **not zero known
vulnerabilities, a cryptographic audit or authorization for a future SSH path**.
The actual gomobile/Android/JVM graph and native binary still require separate
analysis if those build stages become available. No source was uploaded to a
third-party audit service; the scanner queried official vulnerability metadata.

## Tool provenance observation

Independent job `2af5d5c9-381b-4d0b-a5fe-313afab5131c` at 17:38:31 matched retained
Temurin 21.0.13+9 tar bytes to the exact official release asset 665757550, size
207,858,352 and SHA-256
`d7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c`.
The [official release metadata](https://api.github.com/repos/adoptium/temurin21-binaries/releases/tags/jdk-21.0.13%2B9)
response hash was `c4c4a49a29fe9c6cc3197a60cb51b3081f985daedfc5cfa2ecd8e72a92005269`.
This establishes download provenance, not installed-tree equivalence, SDK
availability, Kotlin compilation or Android compatibility.

## Commands, jobs and evidence

All server work ran as chatbot, without changing owner limits or other services.
Go tests use GOTOOLCHAIN=local, CGO_ENABLED=0, GOMAXPROCS=2, GOMEMLIMIT=512MiB,
GOFLAGS=-p=1 -mod=readonly, controlled existing caches and offline module access.
One coordinated heavy job was active at a time; resource preflight required
at least 4.5 GiB host available memory. No new tool was installed by QA.

Commands:

```
python3 archivebridge/run_checks.py --run-synthetic-bridge --expected-commit 5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff
python3 archive/run_checks.py --run-synthetic-archive --expected-commit 5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff --fuzz-seconds 10
python3 qa/phase6_archive_bridge/run_bridge_independent.py --candidate-root /home/chatbot/wainak-dev/archive-bridge-phase6 --candidate 5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff --evidence <new-owned-evidence-directory> --run-synthetic-bridge
govulncheck -json -test ./...
```

- Initial exact run `4002e226-58ed-43df-b391-979aa650c7ff`, terminal 17:43:10,
  exit 1 solely for the QA fixture described above; runtime equality true.
- Fixed-label diagnostic `c49d8a64-975f-4d15-81c4-22c732f33e48`, 17:43:57.
- Final independent suite and scan `9d87ec7e-bf18-41d6-bed4-0d5d0aa9bdf6`,
  terminal 17:45:18, exit 0.
- Final audit `14016ffe-7f4f-4afe-bfcd-2c5e1e11b2b1`, terminal 17:46:05, exit 0.

Evidence root:
`/home/chatbot/wainak-dev/phase6-qa-evidence/5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff/`

| Artifact | SHA-256 |
|---|---|
| host-test-results.json (initial, includes failed QA fixture) | 6351f5e0a468aa9f486f9e25b20adcc2ee275bf96454cbf592629f619fb180ad |
| final/independent-bridge-results.json | f53639cccb56e36ba74e9ab0e7c2a3331a8543eaa6c0197ed7b33a3497317a6f |
| final/bridge-advisory.json | f26eed426bb78c7e8cb319100ef1aaf0e9f09a7334a99328c05710a76cfcc0d9 |
| final/candidate-source-manifest.json | a1a8cfdbfd49eecf38be166d95be6f6de8c41fd1ea160116032c18eb8fb5b20f |
| final/qa-source-manifest.json | 4480d4b1febc8d41f203982f963261c97d28bd1c5c1f973079814f82cef1fcd0 |
| final/final-audit.json | dd7aa785c62ea51740b72bb2afa4b0f2374a5d3981ae80ac8b35484d2957b7f1 |

Final audit: all 23 container metadata records and owner service metadata matched
before/after; 18 Mailcow containers remained stopped. Main stayed unchanged.
Owned tools temporary directory was empty, no live owned Go/age/scanner/Flutter
process remained, and owner oom/oom_kill counters were zero. Permanent owner
4 GiB/compiler2560/8 settings were preserved. The heavy window was explicitly
released to the Flutter developer after this audit.

## Remaining gates and decision

No unresolved product defect was found in the reviewed host Go scope. This is not
approval of the whole phase6 native feature. The proposed Dart/Kotlin layer has a
separate candidate and independent lifecycle/codec/cleanup gates; its results
must not be inferred from this report. SDK/JNI generation, actual AAR linkage,
unsigned APK signing-material absence, packaged ABI/16KiB alignment, native
runtime scheduling and device behavior remain open. A successful future build
alone cannot prove native execution, store acceptance, secure key custody or
real-history restore. No main change or deployment follows from this report.
