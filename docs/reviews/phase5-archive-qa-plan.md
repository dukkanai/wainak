# Phase 5 synthetic Linux history archive — independent QA design gates

2026-10-24. Baseline main: `5f3433b23d8a29999c24943414ff1fdbcc40f46d`.
Acceptance plan prepared before runtime QA; commit-specific results are recorded separately.

Scope: isolated Linux feasibility of a bounded history-only JSON snapshot in the
standard binary age v1 container, using pinned reference Go age v1.3.2 and scoped
Go 1.27.3. No main change, deployment, native bridge, provider/cloud integration,
real user content, persistent credential/key or live messaging state is authorized
by this prototype. Synthetic generated keys/plaintext stay in RAM/private pipes.

User-controlled local/OS/cloud backup is permitted in the product design, but the
current test uses no cloud destination. D16/17 still prohibit ordinary conversation
content/ciphertext/card IDs/content hashes in automatic Wainak-server storage.
This Linux run is synthetic test data, not a production server archive facility.
D25 remains a separate explicit evidence workflow, never a backup-key store.

## Proposed schema and trusted inputs

Snapshot contains only schema version, opaque owner reference, catalog version and
records with event ID, canonical occurrence timestamp, card ID and response ID.
No SQL, paths, URLs, compressed container, arbitrary text, auth/device/ratchet keys,
tokens, consent/trust status, relationship activation or outbox fields are allowed.
Caps: 1 MiB plaintext, 2 MiB ciphertext, 2,000 records, JSON depth at most 8. These
are prototype limits, not established product limits.

The current owner is supplied independently by the caller, not chosen from the
archive. Matching owner metadata prevents accidental cross-owner merge, not proof
of authorship. Anyone with a recipient public key can create another valid age
file for that recipient. Imported records therefore remain explicitly imported,
untrusted history; they cannot establish identity, historical truth or current
permissions. Timestamps do not prove freshness.

Catalog must be privately/deeply immutable and validated batches must not expose
mutable backing slices. Import must revalidate against the store's trusted catalog
or bind the exact validation scope; equal version text alone must not permit a
batch validated by a divergent same-version catalog.

## Six Linux gates

| Gate | Required evidence |
|---|---|
| L1 Provenance/dependencies | Exact actual artifact/compiler/module graph, checksum chain, go.sum, source/binary hashes, licenses and advisory scope. No silent toolchain update during tests. Offline test/build after reviewed dependency acquisition. Tar checksum is not a ZIP checksum. Safe archive extraction rejects path traversal/duplicates/symlink surprises and bounds input. |
| L2 Format interoperability | Wrapper export decrypts through pinned upstream CLI and CLI output imports through wrapper, with exact plaintext bytes and randomized ciphertext across repeated exports. All private/public recipient/key material and plaintext use anonymous inherited FDs, not argv/env/files/logs. This is same-implementation interoperability, not independent cryptographic algorithm validation. |
| L3 Completion/atomicity | Encryption Write and final Close errors are checked. Decryption quarantines bounded plaintext in RAM and consumes authenticated EOF before schema validation/return/import; no prefix display/callback. Invalid input or commit conflict never partially mutates MemoryHistory. |
| L4 Hostile input/resource bounds | Wrong/malformed key; corrupt header/payload; empty/truncated/final-tag failures around 64 KiB ±1 and maximum bounds; appended bytes/second archive; oversized file/header; invalid UTF-8/depth/trailing JSON/unknown fields/null/wrong types/escaped duplicate keys; duplicate event IDs; invalid catalog/card/response/timestamp/owner. No decompression, plugins, SSH or password-KDF profile. |
| L5 History-only import | Foreign owner and same-version divergent catalog reject; zero/nil/forged or externally mutated batch cannot bypass validation. Existing identical records may be documented idempotent no-ops, conflicting records never overwrite, and any mixed conflict aborts the whole batch. Concurrency preserves atomic imports. No current account, device trust, ratchet, permission or send state can be restored. |
| L6 Interruption/leak truth | Cancellation before/during/after finalization, short write without error, partial write plus error, Close failure and injected ENOSPC cannot claim successful/recoverable export. Do not fill the real disk. CLI child/pipes are bounded and cleaned up on cancellation/failure. Runtime-generated synthetic canaries/keys do not appear in logs/errors/owned temporary artifacts; no plaintext staging file. |

## Semantics requiring explicit limits

A generic blocking Reader/Writer cannot necessarily be interrupted merely by
checking context before a call. Prefer bounded byte inputs/current in-memory sinks;
state precisely which cancellation points are implemented. Real native/provider IO
cancellation and durability are not established by injected memory-writer tests.
Partial ciphertext already written to an external caller's sink is not a successful
archive; the caller must not publish it as recoverable. No fsync/provider/cloud
synchronization promise follows from age.Close.

Go's ordinary JSON decoder does not by itself reject all duplicate object keys.
Duplicate detection must compare decoded keys, including escaped equivalents, at
every object depth. Reject the whole batch, not only offending records. All errors
and test summaries are fixed/sanitized and must not echo secret operands.

Use established age APIs unchanged. Wrapper schema/profile checks are not a new
cipher, KDF or handshake. Single native X25519 profile must be documented and
unsupported profiles fail closed without plugin execution or costly KDF work.
Do not silently expand to live E2EE, device backup or key-trust restoration.

## Evidence labeling and stopping conditions

The race detector needs an appropriate C toolchain; if unavailable, record
`-race NOT RUN`, not passed concurrency safety. Bounded concurrent functional tests
are separate evidence. Fuzzing/test-vector coverage, advisory retrieval gaps and
native/device checks must each have exact PASS/FAIL/NOT RUN scopes. A library's
reputation or a CLI round trip is not a Wainak audit or mobile acceptance.

Keep one coordinated heavy job, permanent owner 4 GiB/compiler settings unchanged,
Mailcow stopped, no production DB access and no real credentials. Preserve failed
runs and fixes in the report; acceptance is bound to final commit/build/inputs and
verified cleanup. Stop on new authorization denial rather than changing executor.

## Primary references checked independently

- Go 1.27.3 is listed as the 19 October 2026 security patch in [Go release history](https://go.dev/doc/devel/release). The [official download index](https://go.dev/dl/?mode=json) lists the linux-amd64 tarball size 70,588,678 and SHA256 `65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40`. Artifact reachability/provenance must still be established for what is actually installed; an observed tar 404 is not a successful download.
- [Official toolchain documentation](https://go.dev/doc/toolchain) describes module-distributed toolchains. An alternate official ZIP requires its own verification; the web fetch of its checksum-DB lookup was unavailable during this review and is not recorded as verified here.
- [Pinned age API](https://pkg.go.dev/filippo.io/age@v1.3.2) requires finalizing the encryption writer; [age v1 format specification](https://c2sp.org/age@v1.1.0) defines header/payload integrity and framing. Reuse those APIs rather than implementing primitives.
- [Pinned release notes](https://github.com/FiloSottile/age/releases/tag/v1.3.2) describe input hardening, not comprehensive clearance of this wrapper or its dependency graph.

The shared archive-selection/TOFU and user-controlled-backup design memos were read.
Their native gates remain separate and unexecuted for this Linux experiment.

## Advisory evidence to assess at final freeze

Official [GO-2026-5932](https://vuln.go.dev/ID/GO-2026-5932.json) marks the
`golang.org/x/crypto/openpgp` family unmaintained and unsafe, with no fixed version
listed. [GO-2026-6354](https://pkg.go.dev/vuln/GO-2026-6354) and
[GO-2026-6355](https://pkg.go.dev/vuln/GO-2026-6355) concern SSH connection handling
before x/crypto0.56.0, listing Dial and connection-construction functions.
Pinned x/crypto0.55.0 therefore is not a zero-advisory graph. Package/symbol
reachability for this exact native-X25519 module and the controlled reference CLI
must be reported separately; no detected call path is not a universal absence of
vulnerabilities or permission to expose SSH/network operations.

The bootstrap public verifier key was independently matched to the
[official Go source](https://go.dev/src/cmd/go/internal/modfetch/key.go).
