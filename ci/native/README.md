# iOS native archive recipe — source preparation only

This directory prepares a **manual, unsigned, synthetic-history-only** build. No
Mac/Xcode, XCFramework, iOS application, simulator, signing or cloud build has
been run for this revision. Android remains on the owner's server; its earlier
artifact is unchanged and its results do not transfer to this dependency policy.

## Entry points

- `python3 ci/native/build.py --check` uses only the Python standard library and
  local files. It performs no network, subprocess, compiler or native operation.
- The separately reviewed outer iOS driver may explicitly invoke:

  ```text
  python3 ci/native/build.py --build-ios --parent-owned-group \
    --work-dir <repo>/.ci-work/native \
    --output <repo>/.ci-work/native/Archivebridge.xcframework
  ```

  This is a **real future acquisition/build command**, not a static check. It
  requires a fresh owned work directory, Darwin arm64, preconfigured Xcode
  26.4.1/build17E202 and an explicit verified `DEVELOPER_DIR`. It never accepts an
  Xcode license, runs first-launch setup, installs an SDK, signs, launches a
  simulator/device or triggers a provider workflow. Failure leaves bounded owned
  evidence for inspection; it never deletes an existing attempt automatically.

The caller must create the native process as its owned group leader. Every native
child inherits that group, including Go, gobind, gomobile and xcrun. The native
runner handles TERM/INT and reaps its direct child. The **outer driver** must
TERM the whole owned group, allow at least15seconds, KILL if needed and verify
no surviving members even when the leader has already exited. A native success
message alone is not a proof of whole-group cleanup. No independent standalone
native build mode is provided.

## Acquisition and offline stages

1. Verify the exact official Go1.27.3 Darwin-arm64 tar SHA256/68,196,737-byte size
   before safe extraction/execution. Redirects are rejected before connecting to
   a redirected destination. Extraction rejects links, special files, traversal,
   duplicate names and expanded-size excess. No global PATH/config is written.
2. Acquire **only explicitly locked public module versions**, with official
   `proxy.golang.org` and `sum.golang.org`, `GOTOOLCHAIN=local` and no inherited
   credentials/proxies/Go configuration. The official Go client authenticates
   SumDB records; returned module h1/go.mod h1 and metadata SHA must equal the
   reviewed lock. No private `wainak.local` module identity is sent for lookup.
3. The future acquisition set contains26 input versions **plus net0.60.0** as an
   explicit target-pruning alternative. Historical sys20220715 is metadata-only
   for the pre-Go1.17 esbuild graph. This is not an extra selected dependency root.
   New-version source ZIP/license bytes **have not been acquired in preparation**.
   Per-version license/notice bytes are inventoried only after authenticated
   source acquisition. CCTV/age's reviewed README is an exact module/path/hash
   exception, never a generic README-as-license rule. License provenance is not
   legal clearance. Existing notices are historical authenticated bytes only.
4. Switch all subsequent tool builds, host regressions, upstream binding and
   graph/package inspections to **GOPROXY=off/GOSUMDB=off**, with the isolated
   authenticated cache. Build pinned upstream gobind/gomobile directly; never
   `gomobile init`, `@latest`, a vendor patch or a Go-command interceptor.
5. Run fresh core/facade tests, real upstream CLI interop, vet and two bounded
   public-input fuzz targets using the explicit input26 policy. The one proposed
   test portability change selects private inherited FD3 through `/dev/fd/3` on
   Darwin and `/proc/self/fd/3` on Linux; unsupported hosts fail, not skip. Keys,
   recipients and test plaintext stay in RAM/private inherited descriptors, not
   argv/env/key files. Raw test output is not saved; status and hashes are.
6. Use unmodified upstream `gomobile bind` for `ios/arm64,iossimulator/arm64`,
   minimum iOS15.0, and retain its `-work` generated source/target module records.
   No shared mutable modfile workaround is used. Each generated post-tidy graph
   must select only allowed versions/local replacements, and package-list evidence
   separately records each actual target's imported closure. Any missing metadata,
   unexpected version or source need fails offline; there is no fallback fetch.
7. Inspect both exact XCFramework slices, static ar or bounded static-FAT
   container, arm64 architecture, defined binding symbols, regenerated header,
   exact module-map semantics and actual Mach-O minimum15.0/platform IDs2(device)
   and7(simulator). At least one LC_BUILD_VERSION record is required with no
   conflicting records; members without platform records are not claimed proven. Retain file hashes,
   graphs, commands, tools and license provenance in `result.json` and sibling
   evidence. These checks do not execute the native code or establish E2EE/security
   acceptance. Native binary advisory scanning is a separately unrun gate.

The driver and native runner monitor a shared8GiB logical-byte workspace budget
(`.ci-work`, app `build`, `.dart_tool`, iOS Flutter ephemeral) and4GiB free-disk
floor. Monitoring is not a kernel allocation quota. This recipe is not permission
to expand the already nearly-full Linux tool budget or delete old evidence.

## Why the dependency policy changed

The old Android experiment used an inherited `GOFLAGS=-modfile` to retain its
older graph. Pinned gomobile's Apple builder overrides child GOFLAGS with
`-tags=ios`; Apple slices also tidy concurrently. Reusing that workaround would
be incorrect. The reviewed direction is a coherent unmodified upstream graph:
crypto0.58/sys0.49 are explicit in both local source manifests; age1.3.2 and the
facade/core implementation remain. The known esbuild0.24.2 promoted baseline is
replaced by0.28.2. Existing Android binaries are rollback artifacts, not new-build
checksums.

Keep three records separate:

- **Input26 metadata MVS:** actually passed with official Go and authenticated
  metadata, no source ZIP/package load/build. Result digest is pinned in lock.
- **Per-target post-tidy graph:** NOT RUN for this revision; upstream may prune
  net0.61 to explicitly allowed0.60. Cross-platform policy coherence does not mean
  identical closures.
- **Imported/linked code and advisories:** new platform artifacts need their own
  evidence. The recipe records imported packages and artifact identity; it does
  not claim a comprehensive binary/security audit. OpenPGP remains unsafe and
  unmaintained with no fixed version; its presence in a module graph is not a
  permission to import it. Known SSH/HTTP2 fixes are minimums, not zero-vulnerability
  claims.

## ABI and packaging provenance

The unchanged5ff facade was actually processed by the pinned existing gobind on
Linux, yielding `Archivebridge.objc.h` SHA256
`2ba29fb669cfc99e867fc33168a31f40e14790626ccc429c3d641e516c313ba3`.
This is generated-header evidence, **not** Swift importer or Apple compilation.
The future build requires regenerated header equality.

Pinned upstream builder emits a named module `Archivebridge` with individual
headers `ref.h`, `Archivebridge.objc.h`, `Universe.objc.h`, `Archivebridge.h`, and
`export *`; it is **not** an `umbrella header` module-map declaration. Its separate
umbrella header includes the two `.objc.h` files. Generated code explicitly links
Foundation. Final app link validation is still required.

Upstream deliberately places `MinimumOSVersion=100.0` in its static framework
Info.plist as an SPM workaround. Do not patch that metadata or confuse it with
actual Mach-O minimum15.0. The app must statically link, not embed this framework.
No bit-identical reproducibility is claimed: upstream framework version metadata
contains build time. The recipe records actual newly produced hashes instead.

## Publication and trust limits

The facade is synthetic only: no real account, recovery key, conversation,
identity authority, trust/ratchet state, active outbox or cloud upload exists.
Imported history is marked untrusted and does not authenticate its author.
Public upstream test vectors may contain example keys; these are not generated
user credentials. No real key/content is included in these locks/proofs/notices.
A manually prepared workflow is not permission to run paid builds, publish an app,
change main, push a branch or deploy.


## Host-harness v3 diagnostic correction (source-only; no third run)

Two earlier manual cloud attempts failed. The second reached
`new-policy-host-tests`; its exact failing child command is **not established**.
The source exposed a concrete configuration mismatch: the interop test's512MiB
canary scan was pointed at the entire toolchain/cache workspace. That is corrected
here, but it is not retroactively declared the cause of either observed failure.

- Compile each host test binary with supported `go test -c`, then execute it using
  Go's documented `go tool test2json -t -p <fixed-package> <binary>
  -test.v=test2json -test.count=1 -test.timeout=120s`. Compile+runtime share the
  existing180s per-package wall deadline; this does not raise limits. Host CLI and
  tests useCGO0 consistently; Apple builds remainCGO1. No new host test is skipped.
- Each module has one owned test root containing public copied fixture source,
  runtime cwd, HOME and TMPDIR. CLI children receive exactly the validated HOME,
  TMPDIR, constant PATH/locale, and explicit owned cwd. Their private identities
  still travel only through inherited anonymousFD3. The512MiB canary scan is
  unchanged, and no key/plaintext staging file is introduced.
- Compilation uses explicit separate GOTMPDIR/GOCACHE/GOMODCACHE. The direct
  runtime test environment does not inherit these compiler-cache paths. Their
  before/after byte inventories and CLI/test-binary hashes must remain unchanged
  across non-fuzz test execution, including failure auditing. This is scoped
  filesystem evidence, not an OS sandbox, universal leak proof, paging/core-dump
  control or secure zeroization guarantee.
- Keep actual supported `go test -json -fuzz=... -fuzztime=10s -parallel=1`, not an
  ordinary non-instrumented `-c` binary. Existing60s fuzz limits remain. Fuzz cwd,
  source, HOME and TMPDIR are owned; compiler temp is explicit. Build/fuzz cache
  deltas are recorded separately, and module cache must remain unchanged. Only
  public schema input or ciphertext can enter fuzz corpus; runtime-generated
  identities and interop canaries are never corpus inputs. Mutable fuzz-cache
  evidence is not represented as an immutable-cache test.
- Recursive whole-workspace accounting is no longer done for every tar member.
  Full aggregate/free-space checks occur at command/phase boundaries, at most
  every2s during work, and forcibly after final result/artifact writes. Extraction
  first reserves its512MiB payload bound plus128MiB metadata allowance **inside**
  the existing8GiB cap and4GiB free-space floor; known writes consume that reserve.
  Every cancellation check remains immediate. Unknown child writes remain
  periodically monitored, not a hard kernel quota; no capacity is increased.
- `last_command` projects only nine fixed host-command names, bounded exit/time,
  fixed outcome/failure kind, and trusted top-level Test/Fuzz identifiers captured
  before execution. Go JSON has byte/event/depth bounds, strict UTF8/duplicate
  checks and a required terminal package PASS. Raw Output, argv, paths, child
  exceptions and hashes are **not** included in this public projection. Malformed,
  incomplete or contradictory exit0 streams fail evidence validation. A later
  unlisted command clears the prior host summary rather than mislabeling it.
- Test stdout remains RAM-only. Cleanup or evidence-write failure cannot turn a
  command into PASS or mask its original error. The outer group owner remains
  responsible for whole-group termination/verification.

Reference for the supported separate-binary JSON path:
https://pkg.go.dev/cmd/test2json (Go1.27.3 documentation inspected; no tool run).
The interop test delta is explicit and provenance-pinned. Core/facade implementation,
module versions, artifact target pins,512MiB/8GiB bounds and native deadlines are
unchanged. All v3 runtime/native/cloud checks remain NOT RUN until separately
authorized execution.
