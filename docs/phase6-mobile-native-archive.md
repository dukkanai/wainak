# Native archive mobile spike — 2026-10-24

## Scope and evidence boundary

Mobile branch `dev/phase6-native-archive-20261024` starts at main
`5f3433b23d8a29999c24943414ff1fdbcc40f46d`. Archive/core source is not copied or
changed on this branch. The separately owned adapter is
`5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff` in `archive-bridge-phase6`, based on
archive `8155772cf0a006078be433f45353c651d9ffe451`. Phase4 remains separate.
No main merge, push, deployment, account, cloud provider or real device access.

This slice is a standalone synthetic RAM probe. It does NOT export/import a
user's actual history, implement a document picker, transmit conversations,
provide E2EE, persist keys, or restore trust/ratchets/outbox/entitlements. Archive
integrity does not prove the author of imported history. The first Kotlin probe
uses exactly two fixed records and returns only a count and fixed safety flags;
no keys, plaintext records or ciphertext cross the Flutter channel.

## Development entry

`WAINAK_DEV_MODE=true` and `WAINAK_REPOSITORY=native_archive` are both explicit.
Dart rejects release/web/non-Android; Android additionally requires DEBUG and a
verified locally supplied AAR. Existing fake/api/identity modes remain separate.
There is NO successful fake fallback when the native bridge is absent. Test
fixtures are injected only by tests and do not prove native execution.

## Typed channel v1

Channel `wainak/native_archive_v1`:
- `open`: exact map `{schema:1,handle:"probe_"+32 lowercase hex,epoch:positive int}`.
  A random in-memory lifecycle ID is generated before requesting open, so a
  missing/malformed reply can still close the intended request. It is not a
  login credential or a Go handle. Native has one context; open is synchronous
  on the platform thread and does not create keys.
- `probe`: same exact map, matching the live context. Reserve one worker slot
  before scheduling. Go creates its own synthetic session/key, exports the fixed
  records, authenticates/imports, checks the complete snapshot, then closes.
- Receipt: exact `{schema:1,profile:"age-x25519-history-v1",records:2,
  imported:true,authenticated_author:false,synthetic:true,persisted:false,
  transmitted:false}`. No private exception message/details may pass through.
- `close`: same exact context tuple; idempotently invalidates only that context.
  Reply `{closed:true}` means the lifecycle handle is invalidated, not proof of
  RAM zeroization. Native work retains capacity until it returns. The successful
  probe reply is produced only after its native Go session has been closed.

Worker crypto is separate from the control executor. Background/Activity stop,
route cover/back, clear, disposal and replacement-view callbacks invalidate
publication. Old callbacks hold owner-bound Dart revision tokens and cannot
fetch a new capability at execution time. Clear during an already committed
native import is not described as undoing a commit: this probe simply drops its
RAM-only session and suppresses obsolete results. No actual auth/safety module
is wired to these lifecycle test hooks.

Go facade names expected from `archivebridge`:
`NewSyntheticSession`, `Epoch`, `ExportHistory`, `ImportHistory`,
`HistorySnapshot`, `Cancel`, `Close`. Expected Java facade
`archivebridge.Archivebridge` remains UNVERIFIED until gomobile generation.
All gobind byte arrays are copied at ingress/egress. The Kotlin adapter uses
only the fixed synthetic catalog `sample_v1` / `sample_card` and responses
`sample_yes` / `sample_defer`. No free text or card history goes to any server.

## Android artifact guard

This branch pins compile/target36, minimum24 and NDK30.0.16248370 in its app
Gradle file. Every build type is configured with `signingConfig=null`, including
debug/profile; no signing key is authorized. Default source set reports native
unavailable. Enabling the real source set requires BOTH:
`-PwainakArchiveAar=libs/wainak-archivebridge.aar` and
`-PwainakArchiveSha256=<verified lowercase digest>`.
The path is fixed under the app, symbolic-link traversal is rejected, and the
AAR checksum is checked before adding it as a dependency. No remote AAR lookup.

No Android Gradle task has run yet. The unsigned configuration must still be
verified on an actual artifact: inspect manifest, META-INF and APK Signing Block;
`apksigner verify` must not report a signed APK. A filename is not evidence.
Inspect all ELF LOAD/RELRO and APK ZIP alignment for16KiB compatibility; neither
NDK30 nor successful compilation proves execution on a16KiB device.

## Tool preparation and current blocker

All commands/files are chatbot-owned, private tools root:
`/home/chatbot/wainak-dev/native-archive-tools-phase6-20261024`.
User approved preparation17:14:15 and Android SDK agreement17:23:55 after the
Google terms link was disclosed. `approval.json` records that user approval;
no sdkmanager license action or SDK package installation has occurred.

Temurin JDK21.0.13+9 Linux x64 was downloaded from the official Adoptium release,
SHA256 `d7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c`,
207858352 bytes. Official release API job4143c3eb; bootstrap job1ff953b1 verified
hash/size, bounded member paths/types/expanded sizes and extracted with Python3.14
`tarfile` data filter. Verification job13f84404 confirmed java/javac21.0.13.
The retained tar was independently authenticated by QA job2af5d5c9.

Google's live page publishes `commandlinetools-linux-15859902_latest.zip`
(SHA256 `4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583`),
but its official GET and HEAD on ostath return HTTP404. The official new Android
CLI installer and SDK repository XML also returned404. No mirror/downgrade was
used. SDK platform36, build-tools36.0.0, NDK30, gomobile AAR and APK remain
BLOCKED/NOT RUN. The SDK404 is not a failed Go/Dart test or a license denial.

The tool tree after JDK preparation was569622519 bytes; free disk18338185216
bytes. Enforce tools/cache<=8GiB and free disk>=4GiB before every subsequent
package/cache expansion. JDK is project-local, no global PATH/packages/services
changed. No adb/KVM/device grant/debug.keystore/release key. Permanent owner4GiB
and existing Dart2560/8 remain unchanged; Mailcow remains off.

## Verification matrix

- Author first cold project compile:70 PASS /3 explicit live skips (job406e9a76,17:48:47).
- Final source:72 PASS /3 explicit live skips, analyzer clean; actual main entry with explicit native opt-in:2 PASS (jobf2ab4803,17:55:40). These final reruns used warm project caches; the added two entry tests were not present in the first cold run.
- Default-off, Android absent-plugin fail-closed and non-Android refusal are headless Flutter test-engine evidence, NOT Android/JNI execution.
- Kotlin, generated Java, JNI, AAR/APK: BLOCKED by SDK tooling.
- Android/iOS device, picker/provider, key custody, TalkBack/VoiceOver, release:
  NOT RUN. iOS additionally requires Mac/Xcode and its license.
- No baseline Linux/archive result is promoted into native acceptance.

## Primary sources

- https://pkg.go.dev/golang.org/x/mobile@v0.0.0-20261011034528-197770444867/cmd/gobind
- https://pkg.go.dev/golang.org/x/mobile (experimental support)
- https://developer.android.com/studio#command-tools
- https://developer.android.com/studio/terms
- https://developer.android.com/ndk/downloads
- https://developer.android.com/studio/publish/app-signing#debug-mode
- https://developer.android.com/guide/practices/page-sizes
- https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.13%2B9
- https://developer.android.com/training/data-storage/shared/documents-files

## Reproduction and failed-attempt history

As chatbot, use the existing isolated Flutter SDK:
HOME=/home/chatbot/wainak-dev/mobile-tools/home,
PUB_CACHE=/home/chatbot/wainak-dev/mobile-tools/pub-cache,
PATH=/home/chatbot/wainak-dev/mobile-tools/flutter/bin:$PATH,
CI=true, FLUTTER_SUPPRESS_ANALYTICS=true, DART_SUPPRESS_ANALYTICS=true,
FLUTTER_TOOL_ARGS='--old_gen_heap_size=384 --new_gen_semi_max_size=16'.
The permanent dartaotruntime launcher remains2560/8; do not lower it.
Coordinate one compiler and current memory/disk preflight. Leave all live
identity/matching/backend fixture opt-ins unset.

From apps/mobile:
- flutter pub get --offline
- dart format --output=none --set-exit-if-changed lib test
- flutter analyze --no-pub
- flutter test --no-pub --concurrency=1 --reporter=expanded
- flutter test --no-pub --concurrency=1 --reporter=expanded
  --dart-define=WAINAK_DEV_MODE=true
  --dart-define=WAINAK_REPOSITORY=native_archive
  test/native_archive_entry_test.dart

Retained author logs and tested source manifests:
native-archive-tools-phase6-20261024/logs/flutter-author-20261024T1747/
and flutter-author-entrywait-20261024T1754/.
The full suite contains16 new native-scaffold tests plus56 existing tests;
three existing real-backend opt-ins are explicitly skipped.

Two added entry tests initially failed the Flutter foundation invariant because
addTearDown restored a test platform override after the invariant check. A
test-only try/finally fixed that lifecycle cleanup, preserving assertions.
The opt-in missing-plugin assertion then ran before the real test-engine reply;
a bounded runAsync event-loop wait with positive consent/button controls fixed
the harness, without injecting a native success or changing application code.
Jobsccdd3eba and68535e49 retain these failures. One subsequent shell quoting
error951b26a4 failed Python parsing before file writes or test execution.
The corrected final jobf2ab4803 passed both entry tests and full72 suite.

Kotlin worker/control queues each have capacity1. Cleanup retains admission
capacity; rejected cleanup or native close failures poison new work rather than
silently claim success. Each context is one-shot. Size limits are checked before
copying native-returned arrays. These are source-reviewed protections pending
actual Kotlin/Android execution; they are not promoted by Dart tests.
