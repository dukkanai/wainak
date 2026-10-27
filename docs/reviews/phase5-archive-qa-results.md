# Phase5 synthetic Linux archive — independent QA results

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

2026-10-24. **Bounded Linux feasibility gates passed, with disclosed dependency
advisories and explicit untested native/production scope.** This is not a general
security approval, cryptographic audit, deployment or main-merge authorization.

## Exact scope and provenance

- Candidate: `8155772cf0a006078be433f45353c651d9ffe451`, branch
  `dev/phase5-archive-20261024`, worktree `/home/chatbot/wainak-dev/archive-phase5`.
- Baseline/main remains `5f3433b23d8a29999c24943414ff1fdbcc40f46d`.
  Exactly24 added `archive/` files; no backend, Flutter, API, auth or production
  database changes. The phase4 local-card demo is not integrated here.
- Independent QA code: `47c10d7b6d8095b117794631c64ea00a07529363`, branch
  `dev/phase5-archive-qa-20261024`, worktree
  `/home/chatbot/wainak-dev/qa-archive-phase5`. It adds QA files only.
- Candidate's283 tracked blobs were matched to committed blobs, the QA copy and
  the pre-test manifest. The259 baseline main blobs remain identical.
- Core `archive/archive.go` SHA256:
  `20ed943c8e8a4c4c8f1b3c19c422c3530678302b408884c8c311b71efa0d639e`.
- Independent API test SHA256:
  `ea1b30c2ff0eef58725320c21b4c9e7e4ff2c598c3233540572d38e1edcaf8e8`.
  QA imports the archive through a checked relative module replacement into its
  own byte-matched worktree, not an older development branch.

This package encrypts a finite-choice history snapshot in standard age v1 binary
format, restricted to one native X25519 recipient. The record allowlist contains
only event ID, canonical timestamp, card ID and response ID, plus schema/catalog
version and owner metadata. It exposes no network, server, phone database, cloud,
login, delivery, outbox, device-trust or ratchet integration.

Current owner is supplied independently of archive metadata. Owner equality does
**not** prove account ownership, sender identity or historical truth: anyone with
the public recipient can construct another valid archive. Imported rows remain
Imported=true and AuthenticatedAuthor=false. No active authority is restored.

## Independently executed checks

| Check | Result and exact evidence |
|---|---|
| Candidate-defined core/CLI tests |14 top-level tests PASS on candidate8155772, including real pinned CLI round trips, wrong/malformed key diagnostics, finalization failures and runtime canary checks. Subcases and fuzz seeds are not added to this count. |
| Candidate runner lifecycle |3 Python cases PASS. |
| Fuzz smoke |Separate ciphertext and strict-JSON targets,10 seconds each, PASS. This is not sustained fuzz coverage. |
| Build hygiene |Application module verification, application vet, independent QA vet and publication scan PASS. Candidate publication scanned283 tracked files with0 issues. |
| Independent API suites |15 top-level suites PASS, with hostile-input and IO subcases. |
| Independent output-limit regression |1 io.Copy/ReaderFrom probe PASS using a test-only Go overlay; no candidate archive file was changed. |
| Independent process lifecycle |4 cases PASS: ordinary success, exited leader with retained pipe, exited leader with closed pipe but live child, and output-bound failure with a child. Independent /proc observation found no live owned group afterward. |
| Public bootstrap proof |Offline signature verification plus negative signature control, independent Merkle inclusion folding, ZIP h1 and all12,071 installed Go file bytes PASS. |
| Dependency/notice integrity |Exact12 non-main module graph entries and13 notice files match committed manifest and upstream cached sources. This includes test-only modules, not12 runtime dependencies; not a legal review. |
| Selected upstream vectors |48 uncompressed binary X25519/header/HMAC/stanza/small-stream Decrypt cases PASS on pinned age1.3.2. Not the entire upstream vector/test suite. |
| Exact-source advisory analysis |Completed against frozen candidate, source including tests and pinned CLI binary; findings disclosed below, not “zero vulnerabilities.” |

Terminal jobs:
- `bbd10997-a00e-4cd9-be36-3a5c2b9f7f5e`,16:34:37 UTC exit0:
  candidate-defined gates, source/publication and unchanged runtime metadata.
- `389faf6c-d23b-4cf1-862c-6c33e7a7b4a6`,16:37:56 UTC exit0:
  independent15+1+4, offline provenance, QA vet/publication.
- `f4bd52b3-80f2-4d10-bea6-4f8f19e2e222`,16:39:32 UTC exit0:
  final source/CLI advisory scans, graph/notices and48 selected upstream vectors.
- `fc37b763-2845-41aa-9c0e-3d19e583d954`,16:40:47 UTC exit0:
  final independent source/runtime/cleanup audit.

No old draft success was transferred to the final candidate. The first QA
preflight (`2528629b`) stopped before any tests because its Docker metadata
template accessed missing Health fields on stopped containers. Only an empty QA
evidence directory was created; a safe metadata accessor fixed the QA harness.
This was not an application failure or an authorization bypass.

## Six-gate assessment

**L1 — provenance/dependencies: PASS, known advisories retained.** Go1.27.3,
age1.3.2 and govulncheck1.9.0 are pinned. Test resolution is offline with
GOTOOLCHAIN=local/GOENV=off/CGO_ENABLED=0. Scanner queries used the official
vulnerability database, not a source-code upload service. No silent upgrade.

The official tar download had returned404. A separately authenticated official
Go module ZIP was used; a tar checksum is not treated as ZIP authentication.
Independent verification checked the saved fresh signed SumDB proof, its inclusion
and HashZip binding, and12,071 installed files (226,846,155 bytes). The original
installation retained only proof metadata; the later retained proof is explicitly
a fresh recheck, not an original-proof retention claim. The pinned public verifier
key matches [official Go source](https://go.dev/src/cmd/go/internal/modfetch/key.go).

- Toolchain ZIP SHA256:
  `af4c06478303fdd1bfb335fab86c7ccb9b12e529044a946a16a1c4bcc779f8d7`.
- Module h1: `h1:r0ub+FnqzZxoWm/dSUOI9DcIqYWn/mNYGFJcv7PyBzs=`.
- Reference CLI SHA256:
  `a8d94f59c5bd168e706ba3ac2e9ce81087290495ab1076549f3eaa853ae93d27`.

**L2 — format interoperability: PASS, same implementation.** Wrapper ciphertext
was decrypted by the pinned upstream CLI to exact original JSON bytes; CLI output
opened through the wrapper. Repeated exports differed. Secret and recipient
material used anonymous inherited FDs; no key/recipient argv or environment
values. Both sides use the same upstream age implementation: not independent
cryptographic algorithm verification or mobile interoperability.

**L3 — authenticated completion/atomic import: PASS for the exposed seams.**
Open quarantines bounded RAM until authenticated EOF, then validates the schema.
Valid JSON prefixes followed by corrupted/truncated endings never returned a
batch. Tests cover65,535/65,536/65,537 and131,071/131,072/131,073-byte plaintext
boundaries and the1MiB limit. Final writer Close and every output write matter.
Mixed conflicts abort the whole import; even identical existing-event replay is
rejected rather than overwriting. No prefix was committed.

**L4 — hostile input and bounds: PASS for tested matrix.** Wrong/zero identity,
wrong owner, multi-recipient/scrypt/armor profile rejection, corrupted headers and
payloads, truncation, concatenation/appended bytes, plaintext/ciphertext/record
caps, invalid UTF-8, lone surrogates, decoded duplicate JSON keys, case aliases,
wrong/null types, unknown fields, excess depth, trailing JSON and cross-card
response misuse were rejected. No compression/decompression is implemented.
Fuzzing is only a smoke; tested examples do not prove complete parser safety.

**L5 — history isolation: PASS.** Invalid/zero opaque batches, foreign owners and
divergent same-version catalogues cannot bypass the store's allowlist. Catalog
construction copies caller collections; stores snapshot the catalog holder.
Returned views are copies. Concurrent capacity imports preserve the2,000-row cap;
conflict/replay semantics remain atomic. Forbidden auth, device, trust, consent,
entitlement, path/URL, arbitrary-message and outbox fields are rejected at both
snapshot and record levels. History cannot grant live permissions.

**L6 — interruption/output/leak truth: PASS for bounded synthetic IO.** Negative,
excess, short and partial-error writer counts, injected ENOSPC and cancellation
are errors, not successful exports. Cancellation during decrypted reading returns
no batch. Child output caps and cleanup after leader exit are independently
regressed. Owned temporary-file scans found no runtime-generated canary/key
staging; raw child stderr/test operands were not published.

This is not proof against OS paging/core dumps or secure zeroization. The ordinary
Stringer methods do not universally redact reflection or `%#v`. A blocked
arbitrary caller Writer is not forcibly cancellable. Cancellation after import's
precommit linearization point does not undo a committed batch. SealTo errors
require discarding all partial output; no fsync/provider durability is promised.
Public schema literals and upstream public vectors are nonsecret test data;
Go may persist public fuzz mutations in its owned cache. Runtime-generated keys
and private canaries were not supplied to those corpus targets.

## Findings closed against this candidate

| Finding | Earlier evidence | Exact final closure |
|---|---|---|
| P1-A, output-bound bypass |Draft interop SHA375dea65 embedded bytes.Buffer, promoting ReaderFrom. Independent job46d9b320 reproduced128 bytes accepted into cap4 with nil error. |Named private buffer; independent TestQABoundedCopyProbe and candidate regression PASS. |
| P1-B, child survives exited leader |Static review of runner8880154c found cleanup conditional on live leader, leaving inherited-pipe descendants possible. |Always inspect/clean the owned new process group; independent4 lifecycle cases PASS, including closed-pipe child. No claim to reap non-child zombies; only live code/FD cleanup and leader wait. |
| P2, mutable catalog holder |Independent jobfe997059 on old core62e3dd5a demonstrated external `*catalog=*other` retargeted a previously constructed store. |Private catalog value snapshot in core20ed943c; TestQAStoreCatalogHolderCannotBeRetargeted PASS. |

No unresolved P0/P1 was established inside this reviewed, bounded archive scope.
That does not clear untested features or the dependency findings below.

## Disclosed dependency findings

Exact-source scanner ran16:39:28–16:39:31 UTC, DB last modified
2026-10-21T00:27:29Z, symbol level. Source including tests:3 module-level finding
events,0 affected imported-package events,0 detected symbol traces. CLI binary:
3 module-level plus2 SSH package-level events,0 detected affected symbol traces.
Independent package enumeration contains171 packages with no SSH/OpenPGP imports
in the application/test graph. Known findings remain in pinned x/crypto0.55.0:

- [GO-2026-5932](https://vuln.go.dev/ID/GO-2026-5932.json): OpenPGP is
  unmaintained/unsafe; no fixed version is listed.
- [GO-2026-6354](https://pkg.go.dev/vuln/GO-2026-6354) and
  [GO-2026-6355](https://pkg.go.dev/vuln/GO-2026-6355): SSH connection denial of
  service, fixed in0.56.0. Listed affected entry points construct/dial SSH
  connections, not the native X25519 archive path tested here.

This supports a narrow non-reachability assessment, not “no vulnerabilities,”
unknown-vulnerability clearance, or permission to expose SSH/other CLI modes.
Reassess before distribution, new imports or any broader reachable feature.

## Cleanup and unchanged services

Final audit verifies candidate and QA copy283 blobs, baseline main259 blobs and
clean worktrees. All23 container runtime records, owner/caddy PID/restart/state
metadata remain unchanged from pre-test. Original DB is healthy;18 Mailcow
containers remain stopped. Tools temporary tree and owned lifecycle/PG tempdirs
are empty; no live Go compiler/age/scanner/Flutter tester remains.
Owner4GiB and permanent compiler2560/8 settings are unchanged; owner OOM and
OOM-kill counters are0. No main write, push, merge, deployment, real account,
SMTP or cloud/provider operation occurred.

## Evidence and reproduction

Evidence root:
`/home/chatbot/wainak-dev/phase5-qa-evidence/8155772cf0a006078be433f45353c651d9ffe451/`

| Artifact | SHA256 |
|---|---|
| source-manifest.json |`ee778445cc7886910d209272ae67ae7a07fc9965357867aa27eb19bd07403b16`|
| candidate-results.json |`0b128882d560d3417666a520ba2dd3f80df010ea3db3460f44c471a29fe9d34a`|
| independent-results.json |`6fde4518face6e049bb0c259851632c0357c81afa27ede204fd31cea3ee86590`|
| final-security-results.json |`21dca42d030d7461e6893916651e3ca6729064b2b966d00705d3323866b373e5`|
| source_advisory.json |`abdbcec10c823990526503b729416a36e9e6b088d96feb9457a2de274f52bc8c`|
| upstream-vectors.json |`4397dff486d969c591b020c311868f278379683f32be4bc9d650ec51a0b10c5a`|
| final-audit.json |`59808d77c8b3b20490c4178e10105656d5a3813c47f5ba2db2354ef616ecc317`|

As chatbot, with the coordinated single heavy window:

```
# In the clean candidate worktree:
PYTHONDONTWRITEBYTECODE=1 python3 archive/test_runner.py
PYTHONDONTWRITEBYTECODE=1 python3 archive/run_checks.py --run-synthetic-archive \
  --expected-commit 8155772cf0a006078be433f45353c651d9ffe451 --fuzz-seconds 10

# In the clean QA worktree, use a NEW owned evidence directory:
PYTHONDONTWRITEBYTECODE=1 python3 qa/phase5_archive/run_independent.py \
  --run-synthetic-archive --candidate 8155772cf0a006078be433f45353c651d9ffe451 \
  --evidence /absolute/new-owned-evidence-directory
```

The runner refuses existing result overwrite and checks relative-module source
provenance. Its overlay adds only the internal bound test; it does not edit app
files. A later report-only commit does not alter the candidate or tested QA code.

## Not run / not implemented

Go race detector (`-race`) is NOT RUN: no C toolchain. Functional concurrent tests
are not a race detector. Android/iOS/Flutter FFI, OS picker/provider atomic save,
keychain/keystore, recovery-key custody/UX, real phone filesystem history, cloud
permissions/synchronization, device accessibility, sustained fuzzing, independent
cipher audit, live E2EE and production review remain NOT RUN or unimplemented.
No payment entitlement, trusted key pin, device identity, ratchet, delivery or
outbox state is restored. D16/17 automatic Wainak-server content prohibition and
D25's separate voluntary evidence boundary remain unchanged.
