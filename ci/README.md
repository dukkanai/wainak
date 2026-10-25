# Native archive preparation and manual iOS validation

This branch prepares a real **manual-only, unsigned iOS compile-validation recipe**. Preparing or pushing it does not execute it. No workflow trigger, schedule, secret group, signing configuration, publishing step or artifact upload is configured. Starting a Codemagic job is a separate action and has **not been performed**.

Android remains on the existing server workflow. The previous Android AAR/APK and rollback branch are not replaced by this preparation. The new Android replay fence and dependency changes have **not** been rebuilt or run on Android.

## Architecture

See [the architecture decision](../docs/ci/native-archive-decision.md). The existing age v1 X25519 archive format and strict history-only import rules remain; the Go core and facade are not rewritten. A coherent, explicitly locked upstream Go dependency policy replaces the Android-only resolver workaround. `gomobile`/`gobind` stay unmodified and pinned; upstream describes this tooling as experimental.

Input module resolution, each generated target's post-tidy module selection, actual imported packages, and actual linked modules are separate evidence. A successful metadata resolver check is not a native build or an advisory scan. Original imported-source hashes remain in `source-provenance.json`; explicit module/test changes are separately recorded rather than rewriting their origin.

The iOS host uses a private Objective-C scalar shim matching the seven generated C declarations. Keys, archive bytes and history do not cross into Dart. The default engine is unavailable; a verified generated configuration explicitly enables the real adapter. Missing or mismatched native code must fail compilation, never fabricate a successful archive operation.

## Current evidence, and what is not evidence

- Official Go metadata selection for the proposed 26-module input passed offline on Linux. Two auxiliary metadata records were authenticated separately. No new module source ZIP was acquired for that test.
- The seven Objective-C declarations were generated from the old audited Go source and pinned generator on Linux. This proves the header shape only, **not** the Apple importer, linker, deployment target or runtime.
- Python configuration/artifact negative controls are executable without Go, Flutter, Swift or Xcode. Their exact final result belongs to the prepared commit report.
- Swift/Objective-C/Kotlin changes, new Dart tests, updated native dependency graph, XCFramework, and iOS app have **not yet been compiled or run** for this branch.
- Seventeen XCTest methods are source preparation, including the conditional real-native roundtrip. A future `build-for-testing` compiles them but does not run them.
- Earlier Android warm-build success and previous Go security findings are not transferred to this branch. Existing selected Android build-tool advisories remain unresolved. Updated source/target/linked advisory coverage is still required before security acceptance.

## Future manually started job

`codemagic.yaml` uses Personal Mac M2, selected Xcode 26.4.1 / build 17E202 and Flutter 3.47.8. The hosted image is a trust boundary: Flutter Git revision, relevant source integrity, engine and Dart versions are checked; this does not independently authenticate every preinstalled SDK binary. The official Mac archive checksum is retained in `ios-host-pins.json`, but is not falsely described as a downloaded-and-verified archive.

The recipe will:

1. Run source/configuration checks and pure-Python negative tests.
2. Bootstrap the pinned Go toolchain from an authenticated official archive, acquire only explicitly public locked modules, record licenses from authenticated module bytes, and then switch Go compilation to offline mode.
3. Build the unmodified native binding for device arm64 and simulator arm64, inspect the actual generated graphs, ABI, static archives, object deployment minima and XCFramework file hashes. No `gomobile init`, latest-version lookup, vendor patch or resolver interception is allowed.
4. Recheck the XCFramework in the Flutter driver and create the ignored Debug configuration only from that artifact. Native headers and all seven signatures must match; static frameworks are linked, never embedded as a runtime bundle. Upstream's framework `MinimumOSVersion=100.0` metadata is not rewritten or confused with the required Mach-O minimum 15.0.
5. Resolve Flutter packages with the committed lockfile enforced; run only the selected archive host tests, plus a separate iOS opt-in entry/platform pass. No backend/PG/live fixture suite is started.
6. Prepare Flutter configuration without a build, inspect effective Xcode settings, and compile unsigned Debug for generic iOS and generic iOS Simulator, one Xcode job at a time. The simulator uses `build-for-testing`, **not** `test` or `test-without-building`. Test bundle and `.xctestrun` hashes are required; no simulator/device is launched.
7. Verify the app bundle has no application signature or provisioning profile. This is not a claim that every vendor-provided Flutter component was originally unsigned.

The generated configuration is removed only if it is still the exact file created by this job. Tracked source or lockfile drift is fatal. No signing identity, developer team, provisioning profile, Apple account, deployment, IPA export or store upload is configured.

## Resource and process boundaries

Fresh `.ci-work` only; no reuse of a partial build. The driver counts that workspace, application build/package data, iOS ephemeral data, and growth of the hosted Flutter SDK against an 8 GiB work budget, while preserving at least 4 GiB free disk. This is a cloud-job guard, not permission to change the server's existing limits or delete its caches.

The native child must run with `--parent-owned-group`: its PID is the process-group ID, and its compiler descendants inherit that group. The outer driver owns TERM, a 15-second cleanup grace, KILL and survivor verification. No unrelated process/service is killed. This is process ownership, **not kernel network/process isolation**, nor a guarantee that Xcode's system-managed services are private to the job.

The native recipe is not independently runnable in an unowned shell build mode. `--check` remains pure static. Download, build, runtime, signing and publication outcomes are separately reported; failure at any stage must remain a failure.

## Product/privacy boundaries

The demo is synthetic and memory-only. It does not add cloud backup, a file picker, real account/key custody, persisted chat, delivery/history synchronization, device trust, payment entitlement or E2EE transport. Imported records are untrusted history, not authenticated authorship or restored authority. A lease's epoch is lifecycle coordination, not authentication.

Both hosts keep a bounded lifetime replay fence of 64 synthetic caller handles. Clear/close/background do not erase it. Exhaustion asks to restart the experimental app for a new engine; this is not a production backup quota. Cancellation invalidates publication and requests cleanup; it is not forced native termination or secure memory zeroization.

## Official references

- [Codemagic YAML](https://docs.codemagic.io/yaml-basic-configuration/yaml-getting-started/), [manual versus automatic starts](https://docs.codemagic.io/yaml-running-builds/starting-builds-automatically/), [selected Xcode image](https://docs.codemagic.io/specs-macos/xcode-26-4/).
- [Dart lockfile enforcement](https://dart.dev/tools/pub/cmd/pub-get).
- [Apple build-for-testing versus running tests](https://developer.apple.com/library/archive/technotes/tn2339/_index.html).

No device usability, accessibility reader, production security, store-readiness or successful iOS build claim is made by this source-only preparation.
