# Phase6 Android unsigned archive build spike — QA gates

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Plan only, 2026-10-24. No phase6 tests/builds independently run yet.
Phase5 archive anchor:8155772cf0a006078be433f45353c651d9ffe451.
Its independent Linux report is committed at8f5ee50edf140e9defa3c64ee5f38ed1819626c0.
Main remains5f3433b; phase4/phase5 are not merged into it.

User approved scoped native tools and the Android SDK agreement at17:23:55.
Scope is Android arm64/API24 binding plus AAR and unsigned APK compilation.
No device/emulator/adb/KVM, signing identity/debug keystore, native runtime proof,
cloud provider, picker integration, real history/key custody, main change or deploy.
Tools scope/JDK21/SDK36/NDKr30 and experimental gomobile must use exact published
artifacts/pins, not silent fallback/upgrades. One coordinated heavy window; keep
owner4GiB/compiler2560/8/Mailcow-off settings unchanged. Stop on budget/headroom
or compatibility failure rather than changing shared settings or deleting others'
files. Installation/download/cache budget and free-space floor require readback.

## Gates

| Gate | Evidence required |
|---|---|
| N1 Source/tool provenance | Exact adapter/Flutter/Java/build source commit plus unchanged archive source anchor; full x/mobile pseudo-version; actual Go/JDK/SDK/build-tools/NDK/Gradle/plugin pins, published checksums and licenses. Build graph must not silently select unsupported Go/API/NDK versions. GOTOOLCHAIN=local and controlled dependency acquisition; cached/offline rebuild where possible. |
| N2 Bindable facade | All exported Go signatures use supported scalars/byte arrays/bound objects only; context, key objects, Catalog maps and Batch internals stay private. Generated Java/JNI ABI actually compiles/links into AAR. Any generated warning/skipped API must be inspected, not hidden by build success. |
| N3 Copies and memory bounds | Clone bytes at ingress before asynchronous scheduling and at egress; cap input/output before extra allocations, cap handles/jobs/retained results, reject nil/oversized and integer extremes. Test mutation of caller input/result after return cannot affect retained state. No secret-bearing String/toString/log/exception payload. |
| N4 Scope and lifecycle | Bind owner+catalog+epoch at operation creation. Wrong owner/catalog, stale epoch, clear/dispose/cancel, account switch and handle reuse reject/drop late results. Start/poll/take races must not release previous scope's plaintext or reassign an old operation to a new owner. Explicit cleanup; do not rely on cross-runtime finalizers or reference cycles. |
| N5 Crypto/import semantics | Preserve phase5 authenticated EOF, fixed errors, strict schema and atomic history-only import. Native adaptation must not convert incomplete output/error into success. Cancellation after commit is not rollback. Imported history is untrusted; no identity/trust/ratchet/outbox/entitlement/consent/delivery authority restored. Owner metadata still is not authenticated authorship. |
| N6 Worker and reentrancy | Native crypto/large serialization does not run on the Android UI thread. Bounded worker/queue, no lock-held callbacks, no blocking channel/poll deadlocks; interrupted/repeated UI flows clear projections. Check zero handles, negative/max IDs, calls after close, concurrent cancel/dispose and stale completions with deterministic host tests. JNI/device scheduling still NOT RUN without device evidence. |
| N7 Unsigned artifact | Disable signing before build, not after a debug key is generated. Metadata inventory proves no new .keystore/.jks/private signing material under owned tool/home/build roots. Inspect APK ZIP/signing block and signer verification results to establish truly unsigned but structurally valid artifact. No installation, publication or app-signing setup. |
| N8 Artifact contents | AAR contains expected generated class API and arm64-v8a Go native library; APK contains that exact library (or documented tool transformation) and intended Flutter/Android bridge call path. Inspect ABI/minSdk/targetSdk/manifest and permissions; absence of backend/network/storage/provider integration is explicit. AAR success alone is not Flutter integration success. |
| N9 Dependency reassessment | Enumerate full new Go and Android/JVM tool/application graphs and copied notices. Re-run scoped advisory analysis against final source and built Go shared object if supported; report unsupported binary analysis separately. Preserve phase5 SSH/OpenPGP advisory disclosure rather than transferring old scan clearance to a changed graph. No source upload to third-party audit service. |
| N10 Reproducibility/cleanup | Exact final source/artifact hashes, commands and failed-attempt history. One final frozen-candidate build/review; no stale cached artifact substituted for final source. Child/Gradle daemon cleanup limited to new owned jobs, temp/artifact inventory, no source/main/runtime-service drift. |

## Evidence labels

Separate Linux adapter unit tests, host Java/Dart tests, generated binding checks,
AAR build, unsigned APK build and actual Android runtime. A successful compile
cannot prove JNI loads/calls, Java byte-array alias behavior on a device, GC/heap
lifetime, platform keystore/provider behavior, UI responsiveness, device file
atomicity, accessibility, store acceptance or end-to-end restore.

A registry handle/owner tag is an in-process scope guard, not a new authentication
scheme protecting against malicious code in the same app process. Ephemeral keys
are synthetic and remain in RAM; no durable identity/recovery key is created.
Clearing references is not secure zeroization or protection from OS paging/dumps.
Public deterministic test vectors may exist in source; runtime canaries/private
key material must not enter logs, arguments, environment, fixtures or build assets.

## Primary sources checked

[gobind type restrictions](https://pkg.go.dev/golang.org/x/mobile/cmd/gobind#hdr-Type_restrictions)
limit the cross-language surface; byte slices can be mutable references. Its docs
also warn about proxy reference cycles and exceptions/panics crossing runtimes.
Therefore copies, explicit ownership and ordinary fixed-error paths are tested
rather than assumed from binding generation.

[gomobile bind documentation](https://pkg.go.dev/golang.org/x/mobile/cmd/gomobile)
describes packaging Java wrappers and native libraries into an AAR and selecting
Android architectures. Current docs are not proof of compatibility for our pinned
experimental revision or NDK; inspect that exact source and actual command.

[Android app signing](https://developer.android.com/studio/publish/app-signing#debug-mode)
documents automatic debug-keystore creation and certificate requirements for
installation. The authorized unsigned build must deliberately avoid that path;
no device installation is part of this spike.


## Narrowed synthetic ABI and independent host probes (planned)

The agreed exported constructor is `NewSyntheticSession()` only. It creates a
fresh ephemeral key and fixed private sample owner/catalog in RAM. There is no
public key string, recovery key, real account, catalog injection or key export.
`Cancel(handle, expectedEpoch)` returns the new epoch; unconditional `Close`
remains a cleanup operation because handles are monotonically never reused.
These signatures still require verification against the frozen source.

Planned deterministic host cases, not executed:

1. Invalid/closed/negative/max handles and epoch mismatch fail with fixed errors;
   monotonically allocated handles and epochs fail closed at integer overflow.
2. Concurrent constructors reserve capacity before key generation: at most eight
   live or constructing contexts; failed construction releases its reservation.
3. One operation per handle and two global operations; reject rather than queue.
   A closed context's running operation retains its work slot until its actual
   terminal defer, so close/new-session loops cannot bypass the bound.
4. Pause immediately after copying input, mutate caller bytes, then resume;
   compare exact result semantics. Mutate returned history/ciphertext bytes and
   prove the retained store and subsequent results are independent.
5. Cancel-before-work and cancel-before-return suppress old output; an old
   expected epoch cannot cancel newer work. No success is returned for stale
   scope even when the cryptographic computation itself succeeded.
6. Pause before import commit and race cancel/close. The current-scope check and
   atomic store commit share one linearization point: cancellation first means
   no import; commit first means cancellation does not pretend to roll it back.
7. Same-key internal fixtures with different owner/catalog prove binding beyond
   decryption failure. Invalid schema, decoded duplicate fields, conflict/replay,
   tampering and truncation leave the prior history wholly unchanged.
8. Preserve phase5 history-only imported/untrusted annotations and allowlist;
   no auth, trust, entitlement, outbox or delivery fields are accepted/restored.
9. After every success/error/cancel/close path, reservations and work counters
   return to the expected value. Hooks are unexported and used only by tests;
   production ABI has no callbacks, test override or deterministic private key.

Android-side review must separately enforce bounds before JNI allocation/copy,
retain independent request-generation guards after every await, and execute
Cancel/Close on a control path not queued behind occupied crypto workers. A
correct host Go registry does not prove those Android/Dart properties.

If native artifacts become buildable, inspect ELF LOAD alignment and ZIP native
library alignment for 16 KiB pages using the official Android guidance. Static
alignment is not device execution or a store-policy approval:
https://developer.android.com/guide/practices/page-sizes
