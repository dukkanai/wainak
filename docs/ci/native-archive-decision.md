# Native archive architecture decision

Status: proposed implementation direction, 2026-10-25. No cloud build,
Apple signing, device execution, release or production acceptance has occurred.

## Decision

Keep the existing age v1 archive format, strict history-only schema and bounded
Go facade. Replace the experimental Android-only module-file workaround with
one fully resolved, checksum-locked upstream dependency graph for Android and
iOS. Use unmodified, explicitly pinned `gomobile` / `gobind`; do not intercept
their tool commands, patch their dependency resolver, or implement cryptography.

The selected graph must reach a fixed point even when gomobile promotes all
selected modules to root requirements. It must be verified before a native
build recipe is described as ready. Go core behavior, format and capacity limits
remain unchanged unless a separately reviewed change is recorded.

The prior Android artifact remains a rollback/reference artifact. A new graph
requires fresh tests and artifacts on both platforms; its validation is not
inherited from the old AAR or APK.

## Why this direction

| Option | Assessment |
| --- | --- |
| Coherent dependency update, upstream Go bindings | Preferred: preserves the reviewed age implementation and schema, while removing the platform-specific build workaround. Requires new graph/advisory, ABI and runtime evidence. |
| Own per-slice Go C-archive / XCFramework build system | Possible but not preferred: adds custom build and ABI maintenance without solving a product requirement. Not implemented. |
| Replace age with Rust/Dart/native crypto integration | Not justified by this build issue alone: expands implementation, format-compatibility and FFI review. No replacement dependency is selected or installed. |
| Keep Android pins and hide the Apple failure | Rejected: neither a production design nor a reproducible cross-platform build. |

`golang.org/x/mobile` is explicitly experimental. “Upstream” here does not mean
a stable API or vendor support guarantee. The native adapters remain small and
replaceable so the archive core is not coupled to platform UI lifecycle.

## The diagnosed problem

The old Apple gomobile path sets child `GOFLAGS=-tags=ios`, overriding the
inherited `-modfile` flag used in the Android spike. Its generated module also
promotes the selected graph to direct roots. Previously pruned tooling edges
then select newer crypto/net/term/text modules. Simply copying the old effective
module file or preserving only its direct roots does not solve that behavior.

No silent upgrade, vendor patch, tool-wrapper interception or guessed Apple
binding is an acceptable fix. Candidate versions must be resolved and reviewed
as a complete graph, not as a list of individually recent libraries.

## Security and product boundaries retained

- Static trusted catalog; strict bounded schema and owner/catalog binding.
- Authenticate the complete age stream before validating or committing import.
- Reject malformed/duplicate/trailing JSON, conflicting records and replay.
- Imported history remains untrusted; it cannot restore identity, sessions,
  ratchets, trusted devices, entitlements, pending sends or an outbox.
- Prototype sessions and synthetic keys remain in native process memory.
- No automatic chat-content persistence, cloud upload, notification or delivery
  claim. Recovery-key custody and real user archive UX are separate work.
- Cancellation/close invalidates stale results. Bounded work capacity is held
  until the actual native call finishes, not merely until a UI callback ends.

## Platform plan

Android continues to build on the owner's Linux server. iOS compilation is
prepared for a manually started Codemagic Mac M2 workflow, with no push trigger,
schedule, signing credentials, public artifact publication or deployment.

iOS minimum deployment target is 15.0, matching the pinned Flutter template.
Device `ios/arm64` and simulator `iossimulator/arm64` are separate slices in an
XCFramework, never merged into one universal device/simulator library. An
unsigned simulator or device build is not evidence that installation, runtime,
key custody or App Store requirements work.

## Acceptance gates

1. Exact public source/checksum/license provenance for every newly selected
   module and host tool; no private source or identifiers sent to advisory APIs.
2. Fixed-point module graph, no unapproved dependency/toolchain downloads during
   compilation; distinguish complete module graph from linked package closure.
3. Fresh core/facade hostile-input, cancellation/race and archive interoperability
   regressions under the new graph; old artifact results do not transfer.
4. Generated Java/Objective-C ABI checks, bounded host adapters, stale-owner and
   lifecycle tests; no missing-plugin fallback may pretend to be native success.
5. Android AAR/APK and iOS device/simulator XCFramework/unsigned app compilation
   on their actual hosts, with exact provenance and fresh advisory findings.
6. Separately authorized on-device runtime and user-key/recovery design before
   any production backup capability or security acceptance.

Known Android build-tool advisories from the previous spike remain unresolved.
Preparing iOS does not clear them. No blanket security or reachability claim is
made from successful compilation or the absence of symbol traces.

## Primary references

- [Go mobile source and experimental status](https://go.googlesource.com/mobile/)
- [Upstream binding command](https://pkg.go.dev/golang.org/x/mobile/cmd/gomobile)
- [age implementation and v1 format](https://pkg.go.dev/filippo.io/age)
- [Codemagic manual/YAML configuration](https://docs.codemagic.io/yaml-basic-configuration/yaml-getting-started/)
- [Codemagic pricing and Personal M2 minutes](https://docs.codemagic.io/billing/pricing/)

Account eligibility/remaining minutes and actual Mac tool versions must be
checked before the first separately authorized cloud run. This document does
not authorize a build, charge, signing setup, main merge or deployment.
