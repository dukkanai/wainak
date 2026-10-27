# iOS native archive host — source preparation, NOT native acceptance

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](STATUS.md).

Base: Android spike source `120a0c24970427438af7c693e772b95050b3fcfc`.
This additive iOS host does not change Android, archive crypto, existing auth,
network transports, matching permissions or entitlement. No Mac/Xcode/Swift/
Flutter compiler, simulator, device, signing, cloud workflow or test was run
while preparing these files. Static checks are not a substitute for those gates.

## Implemented source boundaries

- Existing Flutter UIScene / implicit-engine / SPM scaffold retained; iOS minimum
  remains 15.0. AppDelegate registers `NativeArchivePlugin` after the generated
  registrant using the same engine's plugin registry. `publish` permits detach
  cleanup. App and scene inactivity/background/disconnect notifications invalidate
  leases. Detach is terminal; there is no background task extension or restart.
- The versioned `wainak/native_archive_v1` channel keeps the Android wire schema:
  exactly schema/handle/epoch; bool and float are not valid integer epochs.
  Caller-known opaque handles permit cleanup of a timed-out open. A reply carries
  only a lease or fixed synthetic count/untrusted receipt, never keys, JSON
  history, ciphertext, real account identifiers or user content.
- A controller-owned Context identity fences every native result. One worker and
  one separately reserved control operation are admitted before enqueue. Clear,
  close, timeout and dispose invalidate immediately; reservations remain until
  work/control actually return. Old close cannot target a replacement lease.
  Reply validation occurs in the actual main-thread delivery turn, exactly once.
  Up to 64 used caller handles are retained as RAM-only tombstones per engine
  instance. Reuse is denied even at a different epoch; ordinary clear/close/
  background does not erase the fence. At capacity new opens fail closed; only
  a genuinely new engine instance has fresh capacity. This is a stale-callback
  fence, not authentication against malicious same-process callers. Android
  parity for this additional fence is a separate follow-up, not changed here.
- 30 seconds is a publication deadline, NOT a guarantee to kill Go or remove
  memory. `closed:true` acknowledges lease invalidation, NOT native completion or
  secure zeroization. A worker always closes a late-created native handle; the
  contract requires idempotent concurrent close for control + worker-finally.
  Cleanup failure permanently refuses replacement work on that host instance.
- `ArchiveEngine` is the maintainable native boundary. Its production factory is
  **unavailable** without an artifact-derived build condition. A conditional real
  Go engine and private Objective-C scalar shim are source-prepared from the
  generated ABI; they have NOT been compiled against an Apple artifact.
  It never uses XCTest mocks. In addition to the dev/native_archive flags, Dart
  requires `WAINAK_IOS_ARCHIVE_PREVIEW=true` on iOS; release and web remain denied.

## Native integration reservation (not enabled)

Debug.xcconfig optionally includes ignored `NativeArchive.generated.xcconfig`.
The generated file is absent. No framework, linking path or native enable flag
is committed. `WAINAK_ARCHIVE_BRIDGE` selects the actual `GoArchiveEngine` and
Objective-C shim; a missing framework/module or mismatched header must fail
compilation/linking, never silently fall back via `canImport`. The verifier must
set BOTH `SWIFT_ACTIVE_COMPILATION_CONDITIONS=$(inherited) DEBUG WAINAK_ARCHIVE_BRIDGE`
and `GCC_PREPROCESSOR_DEFINITIONS=$(inherited) WAINAK_ARCHIVE_BRIDGE=1` for the
Debug native build, plus validated static framework search/link settings. The
conditional linked-engine test asserts the actual factory is available.

A later reviewed artifact verifier may generate that file only from the exact
XCFramework Info.plist, architecture/platform/deployment metadata, module headers
and hashes. Native adapter source must use the *generated* Objective-C ABI, not
assumed Swift importer spelling. The private C shim exports only scalar status,
handle and count to Swift, using NSError inside Objective-C only. Input records
are the same fixed two records as Android. Every NSData boundary is bounded
BEFORE an actual bytes copy (2MiB cipher, 1MiB snapshot); `copy` alone is not used
as proof of disjoint storage. Snapshot keys/profile/records/imported/untrusted
flags are checked exactly. NSJSONSerialization here validates the snapshot emitted
by the pinned Go implementation; it is not an untrusted archive ingress parser
and does not replace the strict Go archive parser. Failures contain no native
error text or plaintext.
Keep the upstream gomobile/gobind unmodified;
resolve the coherent dependency graph first. Existing Android binary or host Go
success does not establish an Apple artifact or Swift interoperability.

Actual generated Objective-C header evidence: source facade5ff300d / pinned
upstream generator197770444867, header SHA256
`2ba29fb669cfc99e867fc33168a31f40e14790626ccc429c3d641e516c313ba3`.
Pinned `bind_iosapp.go` SHA256
`73d9b079a5627443e7967cf5717dcd1fd068a173f445a90787f15374cc3f10b4`
shows module `Archivebridge` and umbrella `Archivebridge/Archivebridge.h` for
output `Archivebridge.xcframework`. This proves source spelling, not an Apple
compile. The eventual coherent graph must regenerate/check that ABI again.

Upstream framework Info.plist has a `MinimumOSVersion=100.0` SPM workaround.
Do NOT rewrite it or mistake it for Mach-O minimum15.0. A future verifier must
check each actual Mach-O deployment command and architecture, static linkage,
and successful Xcode consumption. Link static code; do not embed that framework
as a runtime payload. Packaging rejection remains a real blocker to diagnose.

Planned initial slices: iOS arm64 + iOS Simulator arm64, minimum15.0. No x86_64
slice or iOS application readiness is implied. There is no recovery-key UI,
OS-picker persistence, cloud SDK, content transmission or E2EE claim here.

## Signing and execution boundaries

All existing project/test configurations explicitly disable code signing and
clear signing identity. No team, provisioning profile, credential or entitlement
was added. These configurations, including Release, are intentionally not
installable/distributable until a separately reviewed signing change. Future CI
must recheck effective settings and binary signatures; the source flags alone
are not proof of an unsigned artifact. Simulator compile does not prove tests
launched, and device compile does not prove installation or device execution.

## Prepared tests (NOT RUN)

`RunnerTests/NativeArchiveTests.swift` contains deterministic executor/deadline
and engine mocks for strict arguments, unavailable/default-off behavior, genuine
worker/close sequencing, stale open delivery, lifecycle reservation retention,
late native open, independent control close, timeout exactly-once replies,
cleanup failure, cross-lease close, queued-receipt invalidation and rejected
control admission, used-handle replay and bounded lifetime capacity and unconfirmed cleanup during open. The mocks are test-target-only
and are not crypto evidence. A separate `WAINAK_ARCHIVE_BRIDGE`-conditional real
factory round-trip/repeated-close test is prepared but NOT RUN; future test
configuration must explicitly include the same verified native build condition.

`test/native_archive_platform_test.dart` enumerates development/release/web/
platform gates and adds an opt-in iOS missing-plugin widget case. Existing entry
tests preserve Android behavior and the new separate iOS preview gate. Future
commands must run both the normal suite and explicit iOS preview flags; skipped
live/native cases remain explicitly NOT RUN until an actual Mac/device exists.

References:
- https://docs.flutter.dev/release/breaking-changes/uiscenedelegate
- https://api.flutter.dev/ios-embedder/protocol_flutter_plugin-p.html
