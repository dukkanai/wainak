# Phase 6 — independent Flutter native-archive scaffold QA

2026-10-24, ostath. **Headless Flutter scaffold checks PASS; actual Android
native integration remains BLOCKED/NOT RUN.** This report complements, but does
not extend into native execution, `phase6-archive-bridge-qa-results.md`.

## Frozen scope

- Mobile candidate: `eb8d521157597ac114ba905c699ad7ad68185b43`, branch
  `dev/phase6-native-archive-20261024`, worktree
  `/home/chatbot/wainak-dev/mobile-native-archive-phase6`.
- Go adapter, separately reviewed and not embedded into this test engine:
  `5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff`.
- Independent QA tests: `0dc2a61a6c964e9adda3ad50710ab9a90e194234`, branch
  `dev/phase6-archive-bridge-qa-20261024`.
- Independent file `qa/phase6_native_archive/native_archive_independent_test.dart`,
  SHA-256 `04c4d7445b9fe1eb95c351ad1640eb629e33a2ede6e95c58a03b376e06198cf1`.
- Fresh snapshot: `/home/chatbot/wainak-dev/qa-native-archive-cold-eb8d521`.
  Created from the exact Git archive, with no inherited project `build` or
  `.dart_tool` cache. Existing isolated SDK/pub download caches were reused.
  The independent test was copied into that owned snapshot only after the
  candidate's cold suite/entry tests; candidate files were not edited.
- All 270 tracked candidate files and 126 mobile files in the snapshot were
  checked before/after. Main remained clean at
  `5f3433b23d8a29999c24943414ff1fdbcc40f46d`.

This standalone mode accepts only development opt-in. `main.dart` additionally
refuses release, web and non-Android entry. The actual native engine is absent
unless an explicitly supplied local AAR passes the configured digest/path guard.
No successful mock fallback is shipped. Tests explicitly inject synthetic ports
or platform-channel responses; their successful receipts are **not evidence that
Go ran through JNI**. Existing identity/API/network modes remain present outside
this separate mode; this is not a claim that the entire application lacks network
capability.

No keys, plaintext records or ciphertext cross the proposed Flutter channel.
Its small maps contain a random in-memory lifecycle ID, revision and schema;
receipts contain fixed synthetic/untrusted/nonpersisted/nontransmitted flags.
The UI has no real account, backup picker, cloud upload, history restore or
entitlement integration. Clearing references is not secure zeroization.

## Exact results

| Gate | Result |
|---|---|
| Offline pub resolution | PASS; existing cache, no new dependency acquisition |
| Candidate formatting | PASS |
| Flutter analyzer | PASS |
| Cold default candidate suite | PASS: 72 tests; three existing live-backend opt-ins explicitly SKIPPED |
| Actual main with native development opt-in | PASS: two tests; Android-target missing-plugin fail-closed and non-Android refusal in the headless test engine |
| Independent controller/channel/widget tests | PASS: 12 cases, including ten malformed receipt variants in one case |
| Source/pub dependency provenance | PASS: 270 candidate/126 mobile blobs unchanged; pubspec.yaml and pubspec.lock byte-identical to main anchor |
| Retained JDK versus installed tree | PASS: 454 files/symlinks, 361,757,417 regular bytes |
| Runtime/process/signing-file inventory | PASS within the inspected owned roots; no compiler/native process or signing-file matches, runtime metadata unchanged |
| Kotlin/Java/Android Gradle compilation | NOT RUN; SDK acquisition blocked by official-endpoint 404 |
| JNI, AAR, unsigned APK, native loading | NOT RUN; no built artifact exists to validate signing or ABI |
| Real device/emulator, TalkBack/VoiceOver, release/store | NOT RUN |

The candidate's 72 tests contain existing baseline and new fixture checks; this
run does not promote the three skipped live-backend journeys to PASS. The default
suite was cold at the project level. The two opt-in entry tests and independent
12-case suite followed using that same newly generated cache.

Independent cases:

1. A deferred old open cannot retarget or overwrite a completed replacement.
2. A successful probe cannot become completed before close acknowledgement;
   clear during close keeps the view cleared.
3. Late failure after dispose cannot change state or notify the disposed view.
4. Mismatched returned epoch rejects the open and closes that exact lease.
5. Stale callbacks remain invalid after clear and a new acknowledgement.
6. Lost open response times out and closes only the caller-known lifecycle ID.
7. Receipt rejects numeric-type deviations, trust/persistence/transmission flags,
   wrong counts/profile, extra and missing fields (ten variants).
8. Malformed close acknowledgement prevents a successful probe result.
9. Platform exception operands are not surfaced as successful or private details.
10. Hiding/replacing scope invalidates acknowledgement and a captured callback.
11. Back while open is pending clears state; late open closes without crypto.
12. Replacing the port does not silently retarget an existing controller.

These assertions ran against the final candidate. No application fix was needed
for the independent cases. The candidate's own Flutter fixtures also passed its
RTL/text-scaling/lifecycle scenarios; that is not actual screen-reader evidence.

## Static Kotlin findings and limits

Before the final freeze, QA flagged pre-validation `.copyOf()` of native arrays,
an unbounded cleanup executor queue and an uncaught LinkageError in its control
path. The final source checks lengths before extra copies, bounds worker/control
queues to one, retains cleanup admission capacity, sanitizes LinkageError and
fails closed if cleanup is rejected/unconfirmed. These changes were inspected in
source, **not executed as Kotlin**.

Crypto runs on the proposed worker; control cleanup is separate. A successful
native receipt is designed to follow worker-side Go Close. Context invalidation
and close acknowledgement do not promise secure RAM erasure. The native
executor/queue/lifecycle behavior, generated Java names and ABI need separate
compiled/runtime evidence. Source review and Dart mocks cannot close those gates.

The proposed Gradle configuration sets signingConfig=null for every build type
and requires an explicit local AAR path+SHA. No Android Gradle build ran, so absence
of a debug key in this audit is not proof that a future APK build remains unsigned.
Actual APK signing block, manifest/permissions, library ABI and 16KiB ELF/ZIP
alignment must be checked on the future artifact. No signing key was generated.

## Tool and dependency evidence

JDK archive provenance was independently authenticated in the Go report. The
additional read-only verifier compared installed regular files/symlink targets
against that exact tar, rejecting extras/missing files and wrong ownership/type.
Installed-tree manifest SHA-256:
`5b4ad9e44d4089f2c8d5f3f8020192096f9c75ff32bf3f97208526e2a44f8ddd`.
Tar SHA-256:
`d7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c`.
This is content equivalence, not proof of JVM/native application behavior.

The Flutter pub manifests are unchanged. The new Android/gomobile/JVM graph is
not considered vetted by this report because the SDK build was unavailable.
The separate Go report retains three x/crypto module-only advisories rather than
claiming a clean cryptographic stack. Any later binding generation/build must
pin and assess its actual additional graph, without a silent toolchain upgrade.

## Reproduction and evidence

Run as chatbot with the existing isolated SDK:

```
HOME=/home/chatbot/wainak-dev/mobile-tools/home
PUB_CACHE=/home/chatbot/wainak-dev/mobile-tools/pub-cache
PATH=/home/chatbot/wainak-dev/mobile-tools/flutter/bin:/usr/bin:/bin
CI=true
FLUTTER_SUPPRESS_ANALYTICS=true
DART_SUPPRESS_ANALYTICS=true
FLUTTER_TOOL_ARGS='--old_gen_heap_size=384 --new_gen_semi_max_size=16'
```

Permanent dartaotruntime2560/8 and owner4GiB were preserved. All identity/matching
live opt-ins were absent. After a memory preflight of at least4.5GiB available,
commands ran sequentially:

```
python3 qa/phase6_native_archive/verify_jdk_tree.py
flutter pub get --offline
dart format --output=none --set-exit-if-changed lib test
flutter analyze --no-pub
flutter test --no-pub --concurrency=1 --reporter=expanded
flutter test --no-pub --concurrency=1 --reporter=expanded --dart-define=WAINAK_DEV_MODE=true --dart-define=WAINAK_REPOSITORY=native_archive test/native_archive_entry_test.dart
flutter test --no-pub --concurrency=1 --reporter=expanded test/qa_native_archive_independent_test.dart
```

The full run was job `392baa0a-16b5-4456-873f-1ac3b4f5db9e`, terminal
18:02:59, exit0. Cold suite60.394s; opt-in entry17.874s; independent cases5.597s.
Final read-only audit `01b90e65-ed80-4095-b724-0418fba854dd` at18:04:26, exit0.

Evidence root:
`/home/chatbot/wainak-dev/phase6-mobile-qa-evidence/eb8d521157597ac114ba905c699ad7ad68185b43/`

| Artifact | SHA-256 |
|---|---|
| results.json | 6331d99b26d76312568e1e91ad3bb25d43348dc39ff756f586024e4c24a3044c |
| source-manifest.json | 729aaaa8476f58faf671e8fc08353485891208d7bbb90e947bf536e9426511f9 |
| final-audit.json | 0247fa7b834470ee1e6020a3760339026f50b0d15d5ad40d39e8de4cb7144e90 |

The scoped signing-file inventory examined native-tools, the existing mobile HOME,
mobile candidate and owned test snapshot for .keystore/.jks/.p12/.pfx and
key.properties matches. It found none; the JDK's public CA truststore is not a
new app-signing identity. Runtime metadata matched before/after; Mailcow remained
off, main unchanged, owner oom/oom_kill zero. No live owned compiler/native
process remained. The heavy window was released after audit, not while a test
was still running.

## Attempts and authorization boundary

A QA file-transfer/format/local-commit operation was explicitly denied before
execution at17:58:30. It was not substituted or split to bypass the denial. The
parent supplied materially new exact native-binding approval context; one retry
of the same operation succeeded at17:59:21, jobc587c288. The resulting QA commit
is listed above.

Initial snapshot setup `20074846-253d-404e-a980-e005819a84dc` rejected the harmless
Git archive top-level directory `apps` before any compiler/test ran. Its path guard
was narrowed to admit exactly that directory (while retaining traversal/type
checks); the verified empty owned snapshot was then populated. This was a QA
setup error, not a failing application assertion. The author's earlier entry-test
teardown/event-loop fixes are separately preserved in the candidate's own
`docs/phase6-mobile-native-archive.md`; no independent assertion was removed.

## Decision

Accept the exact headless Flutter scaffold evidence and separately the reviewed
host Go facade within their synthetic development scopes. Do **not** claim an
end-to-end Flutter→JNI→Go archive roundtrip, usable backup, unsigned APK, Android
runtime or production/store readiness. No main merge, push, deployment, device
access, cloud provider or persistent credential action is authorized by this
report. Later binding artifacts or source changes require their own exact-version
validation and do not inherit a native PASS from these tests.
