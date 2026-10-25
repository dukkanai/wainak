# iOS / native archive preparation verification

Date: 2026-10-25 UTC. Scope: the development commit containing this report, based on `120a0c24970427438af7c693e772b95050b3fcfc`. **Source/configuration preparation only; no cloud job was started.**

## Exact integrated checks

At 04:20:26, independent server job `f4c8cc36-0e59-4dcc-a46b-dcb7e41610b8` completed with exit 0:

- `python3 ci/check_preparation.py`: PASS; 16 iOS files, 7 Android/Dart parity files, 22 imported native files/deltas and 23 original Android paths anchored.
- `python3 -m unittest discover -s ci/tests -p 'test_*.py' -v`: **35/35 PASS**.
- `python3 ci/native/build.py --check`: PASS, pure static.
- `python3 -m unittest discover -s ci/native -p 'test_*.py' -v`: **39/39 PASS**.
- `python3 ci/ios/build.py --check` and `git diff --check`: PASS.

These 74 Python checks use structural/negative fixtures. They are not Go, Kotlin, Dart, Swift, Xcode, JNI or device tests. All native recipe files were SHA-checked after source-only transfer; no recipe build mode was invoked.

Frozen key inputs:

| File | SHA-256 |
| --- | --- |
| `codemagic.yaml` | `e3674c1a43815cdd4a923f119850c6bc016b654ca4c1e432436c7a48766f865c` |
| `ci/ios/build.py` | `0a72f0c4792c8b1bc0c2077e6ca379499b5e722d892f50c4cfcfe0658d6b569e` |
| `ci/native/native_runtime.py` | `8f131c89840f77653ad10552e58d2ff940007e9c3640853c78a47d2d851919b5` |
| `ci/native/lock.json` | `01f3a9c7c2e468303243fa563c01962bda0264c3110fbf76d69d56c573df5d33` |
| `archive/archive.go` | `20ed943c8e8a4c4c8f1b3c19c422c3530678302b408884c8c311b71efa0d639e` |
| `archivebridge/bridge.go` | `3cf7dcf2f25454bcf3c16dd3a6189382babcb93fe7fb2913a60383aeb48df415` |

Original imported-source hashes and explicit module/test deltas remain separate in `ci/source-provenance.json` and `ci/native-source-deltas.json`. No private development history, generated AAR/APK/XCFramework, signing material, runtime key or private fixture is imported. Retained old-version notices describe the audited source origin; they do not certify licenses of new, unacquired versions. Future acquisition records version-specific legal evidence separately and does not self-certify legal clearance.

## Earlier evidence, narrowly reused

- Official Go **input metadata** resolution selected the proposed 26 public modules offline: job `913e4f93-a857-4804-ac26-a6f509396b02`, 03:47:06, exit 0. Result SHA-256 `e8c00c209d791c6fcf58385e4c8371b5ea6f6855f1e7e10ec9298459e6ebfa2e`. Two auxiliary metadata records were authenticated; zero ZIP/source acquisition or export-data compilation occurred. The first attempt correctly stopped for missing historical metadata; it is not counted as a pass.
- Pinned old-graph Linux Objective-C generation succeeded, yielding header SHA-256 `2ba29fb669cfc99e867fc33168a31f40e14790626ccc429c3d641e516c313ba3`. All seven normalized declarations are checked. This is not Apple compilation or Swift importer proof.
- Source/proof bytes and signatures were reviewed separately. A checksum/static lock check alone is not a fresh online authenticity check.

## Deliberate safeguards

One manual Mac M2 workflow is prepared with pinned Flutter/Xcode and no push trigger, schedule, publishing, artifact upload or secret group. The future build is unsigned Debug, device arm64 plus simulator arm64; simulator `build-for-testing` compiles tests without executing them. Seventeen XCTest methods are currently **source-only / NOT RUN**. No simulator launch, application signing, Apple account, entitlement restoration or release export is configured.

The real native adapter is conditional on a verified generated artifact configuration; the default reports unavailable. It is synthetic, memory-only and count-only across the Dart boundary. Both hosts enforce bounded lifetime replay fences. Timeout/cancellation means publication invalidation and requested cleanup, not forced native termination or memory zeroization.

The clean upstream graph removes reliance on the old Android resolver workaround, but actual target tidy/import/link graphs must still be recorded and validated. The recipes fail closed on unexpected versions, wrong platform/minimum/ABI, source drift, resource overflow or uncertain cleanup. They do not patch upstream or use `latest`/`gomobile init`.

## Outstanding gates — not waived by preparation

- Fresh authenticated source acquisition and version-specific license inventory for the updated graph.
- New-graph host Go regression/fuzz/advisory checks and actual Apple target tidy, compilation, linkage and artifact inspection.
- New Dart/Kotlin/Swift/Objective-C tests; the old Android warm-build result does not apply to this changed source.
- Actual Mac/Xcode execution, unsigned iOS compilation, compiled XCTest bundle, and any simulator/device runtime. None has been performed here.
- Updated source/build-tool/imported/linked advisory coverage. The previously selected **nine Android build-tool advisories across eight package/version pairs, including a database-critical Bouncy Castle finding, remain unresolved**. Metadata upgrades are not a blanket security clearance; `golang.org/x/mobile` remains experimental.
- Product key custody, cloud/file-picker integration, real user backups, production access controls, store signing/distribution and on-device usability/accessibility are outside this synthetic preparation.

This report accepts only the documented preparation/static-check scope. It does not declare the app build-ready, production-safe, installable on an iPhone, or successfully built on Codemagic.

## Publication review

At 04:22:21, independent audit job `1483445a-5cac-4ed1-90dd-9ffc85c9954a` inspected 339 current source/asset files (30 existing font/image binaries) and 343 reachable inherited-history blobs. Defined secret/key/token/credential-URL, unexpected native artifact, private new host-path and symlink checks reported zero findings. No active Git hook was present. This is a bounded source/history audit, not a guarantee against every possible secret. Ignored runtime files were not selected for publication.

The unchanged GitHub workflow remains main-push-only (plus explicit manual/PR events); no pull request or workflow dispatch is part of this preparation. Codemagic YAML has no automatic trigger. Public development-source publication is authorized; main and the old Android rollback branch remain separate.
