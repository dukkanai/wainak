# Phase 6: unsigned Android archive-build spike — independent QA

Date: 2026-10-25 UTC. Scope: Linux-hosted synthetic, unsigned arm64 Android
compile/artifact feasibility, not an Android runtime or release acceptance.

## Decision and exact subjects

**The guarded warm APK build and static artifact gates passed.** The initial
build hit its disk budget and is retained as failed; this is not an uninterrupted
cold-build pass. Known dependency advisory matches remain disclosed below.
**Security/release acceptance is not granted.** There is no blanket security,
native-runtime, device, store or deployment approval.

| Subject | Exact identity |
|---|---|
| Mobile build source | `120a0c24970427438af7c693e772b95050b3fcfc`, branch `dev/phase6-native-build-20261024` |
| Go bridge source | `5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff` |
| Archive core | `8155772cf0a006078be433f45353c651d9ffe451` |
| Input AAR SHA-256 | `05a6410ff782676cb656e801c03c16af86ae0175dd7e813ea7be3a8ed4f8d95a` |
| APK SHA-256 | `ce504fa821a36da21b469cd52e305a6889462a4e959caea4a852370b483d9292` |
| APK size | 83,305,322 bytes |
| Unchanged main | `5f3433b23d8a29999c24943414ff1fdbcc40f46d` |

APK path: `mobile-native-build-phase6/apps/mobile/build/app/outputs/apk/debug/app-debug-unsigned.apk`
under `/home/chatbot/wainak-dev/`. Its Flutter output copy is byte-identical.
The source has no tracked modifications. The generated
`apps/mobile/android/gradle/verification-metadata.xml` remains **untracked** and
was a recorded build input/output; do not call the whole worktree clean.

Prior SDK/AAR QA is committed separately as
`247d280d4478a820fea5327e332466a6f17c9654`, in
`docs/reviews/phase6-sdk-aar-qa-results.md`. It contains the SDK license/ZIP
proof, pinned Go/age/mobile provenance, AAR ABI checks, host regression results
and Go advisory limits. This addendum does not silently transfer host tests into
Android execution evidence.
The earlier Flutter scaffold/widget results belong to their recorded baseline
commit; no new full Flutter suite was run in this build continuation. This
milestone's new evidence is the actual Kotlin/Java/native packaging compile and
the checks on the exact unsigned APK, not a new behavioral suite on Android.

## Build controls and result

- Official Gradle 9.3.1 wrapper/launcher/distribution hashes were enforced.
  JDK21.0.13+9, SDK36/build-tools36.0.0/NDK30.0.16248370, minSdk24 and arm64
  target were fixed; automatic SDK downloads were disabled. No adb, emulator,
  KVM, signing key, keystore or device authorization was used.
- Direct guarded Gradle `:app:assembleDebug` avoided Flutter's adb validation
  path. The reviewed guard pins the exact app and Flutter included-build roots,
  AAR/hash, SDK/NDK, source and tool artifacts. Every buildType signingConfig
  must be null. Forbidden device/install/signing/CMake/externalNativeBuild
  tasks fail before task bodies.
- A single exact metadata-only exception permits
  `:app:writeDebugSigningConfigVersions`, of the pinned AGP9.1 class, only when
  all four signing booleans are false, overrides are false/null, config remains
  null and the output is the expected JSON under app build. Independent pinned
  bytecode inspection found boolean serialization, not signing/keystore access.
  AGP's default V2=true at minSdk24 initially failed this gate. Source120a0c2
  explicitly sets the four flags false; the guard was not weakened.
- Approved app50/plugin8 task graphs remained byte-identical. Their SHA-256s:
  `7f7794247d9c4c6967f200222ae4e99d7a84a3bbe2bbb026ac16be087ffa2a82`
  and `2b2bdf5d9e137418a4725c796b54ec8aad89d69020c239aacd144de31603b7a6`.
- The first actual build, job `edc7a70d-d4fe-435a-8514-dc42ae50e51a`, stopped
  at 01:15:10 with `disk_budget`: the combined scoped size exceeded 8GiB.
  It reached packaging output but had no accepted successful terminal result.
  No OOM kill, silent budget increase or automatic cleanup was used.
- After the user's specific 01:32:18 approval, only duplicate Gradle
  `docs/` and `src/` cache trees were removed: 21,850 regular files,
  342,094,466 bytes. QA independently matched every file to the retained official
  full distribution ZIP, with no symlinks/extras and UID1001. Runtime bin/lib,
  SDK, source, APK/AAR and evidence were preserved. Cleanup report SHA-256:
  `a227218333f0f75a96b01de3386a9b8db4105c702184b01c6b0d32a83ae2dad9`.
- Warm build terminal 01:35:00 was exit0: 27.843 seconds,
  `BUILD SUCCESSFUL`, 49 actionable tasks (7 executed, 42 up-to-date).
  APK bytes did not change from the independently inspected artifact.
  Final combined budget 8,526,678,903 bytes (<8GiB), free9,983,381,504 bytes;
  the remaining budget margin is narrow, not permission to raise the cap.
- Private HOME/JVM user.home, bounded heap/workers, no heap dump, owned-group
  cleanup, fixed source/tool hashes, SDK bytes/names and key-file inventories
  were checked. These are trusted-source build controls, not a hostile
  same-UID sandbox or kernel-enforced network isolation.

Warm evidence root, relative to the native tools root:
`apk-builds/build-20261025T013406Z-78c967d2/`.
Result SHA-256 `abc6448ce71f187bba435c4a3c7fe530adb53eddabe5f72d88fe3b43c40fcee3`;
log `35065975b0cc5a4edb1ae58ab02b7c790d8f76bd51b50e5f6a6a3981daeba8e6`.
Independent readback job `3d3c4a76-533b-4916-9aee-96b0e1f5fdb9` verified
these bytes, both graphs, cleanup result, source and identical APK at01:36:11.

Retained earlier failures include exact-root guard handling, a transient `du`
inventory race, Kotlin Gradle DSL Java-package shadowing, and the unsigned
metadata gate. Corrections were narrow and evidence retained. PLAN can compile
the included Flutter plugin during configuration even with `--dry-run`.
The successful build warns of deprecated external Kotlin/AGP DSL settings and
future Gradle10/Flutter incompatibility; future upgrades require new review.

## Independent static APK gates

| Gate | Result and boundary |
|---|---|
| ZIP/unsigned structure | PASS:147 entries, no v1 signature entries and no APK signing-block IDs |
| Official apksigner verify | Expected unsigned rejection:exit1, `DOES NOT VERIFY`, missing META-INF/MANIFEST.MF; interpreted with the independent structural checks, not as a generic exit1 proof |
| Official zipalign | PASS:`-c -P 16 -v 4`, exit0 |
| Native ABI and load alignment | PASS:exactly three arm64/AArch64 ET_DYN libraries, stored uncompressed at16KiB ZIP offsets; each PT_LOAD alignment≥16KiB |
| Go-library lineage | PASS:AAR→merged library byte match; stripped library→APK byte match; program headers and all LOAD bytes beyond the64-byte ELF header match |
| Manifest | PASS:official aapt2 badging/xmltree; min24,target/compile36, debuggable=true, extractNativeLibs=false; development invalid.example package |
| Compiled bridge classes | PASS:DEX class definitions include Archivebridge, GoArchiveEngine, ArchiveEngineFactory, NativeArchiveChannel and MainActivity; this proves packaged class presence, not execution |
| Android/JNI execution | NOT RUN; these are parse/build-time checks only |

The stripped Go SHA-256 is
`0393401808d0527530d48e06f5993f3c974bfee5bfb5f6d3519ad3b2f000e5cb`.
Its unstripped AAR/merged SHA-256 is
`35ce2cbfbfa76910092b6995c6c29502ea976af839eaf75706a9a1428e39f83e`.
Differences in the first64 bytes are only ELF section-table metadata at
offsets40,41,42,60,62; this was checked rather than assuming strip equivalence.
Other native libraries are libflutter.so and libVkLayer_khronos_validation.so.

Manifest INTERNET permission is present: the APK is **not networkless**.
MainActivity is an exported launcher, StartupProvider is non-exported, and the
exported ProfileInstallReceiver requires android.permission.DUMP. The build is
debuggable, synthetic and unsigned, not suitable for distribution or real data.

Independent jobs: structural `13f87215-5156-4920-a717-7f10698e6469`,
lineage `22487195-9fb1-4f35-90d6-74fd39520397`, official read-only SDK tools
`f67faff9-dafa-4c78-9e8b-e561aa6f59f1` (01:21:56). SDK tool bytes were
revalidated before executing verification-only commands. No APK execution,
signing or install command occurred.

An additional read-only DEX parse, job
`1c8a1e16-e49f-4cb1-bb88-fd1c643f79a9` at01:44:46, verified the compiled
Go-backed source-set classes in the same APK. The available-engine source,
not a fake-success fallback, calls the generated Archivebridge methods.
Its historical source comment saying AAR compilation remained pending is now
superseded by this exact build evidence; Android execution is still pending.

## Dependency provenance and advisories

The user specifically approved disclosure of545 public Maven names/versions to
OSV at01:15:35. Only those public coordinates were sent to
`https://api.osv.dev/v1/querybatch`, with redirects/proxies disabled and bounded
pagination/output. No private code, paths, artifacts, module identifiers, keys
or user data were sent. Query helper7 local mock tests passed. A prior denied,
known-unexecuted attempt was retried once after the fresh consent.

Query job `d2b6df8b-2605-4c63-8c6a-d45b1ab63cde` completed01:16:28:
11 requests, complete pagination,26 matched coordinate/version pairs and
53 distinct advisory IDs. Output SHA-256:
`55b83c6a218e8e17b6fc17b1f83df19185e06cfc18a84ee3ef1990058f253def`.
The545 inputs come from a1,122-file cache inventory **superset**, not a selected
runtime graph. The selected runtime report contains47 public coordinate/version
pairs including constraints, no unresolved marker and no OSV matches among
those47. This does not prove database coverage or vulnerability absence.

All53 public advisory records were retained separately at01:37:43,381,757bytes;
manifest SHA-256 `4037890fc05ca485dea7ac9cdddf9b4452836b1ac07544d5ce1e616e3b2094d2`.
Database labels include3 critical,20 high,28 moderate and2 low. These are **not**
53 demonstrated exploitable application vulnerabilities. Matched cache
coordinates include Netty, Bouncy Castle, Commons Compress/Lang, HttpClient,
jose4j, JDOM and several Kotlin Gradle Plugin versions.

Kotlin Gradle Plugin2.4.0 and the other matched versions carry
[GHSA-r937-wjx7-w2jp](https://github.com/advisories/GHSA-r937-wjx7-w2jp)
/ CVE-2026-53914, KAPT incremental-cache unsafe deserialization. The
[upstream fix](https://github.com/JetBrains/kotlin/commit/bf51df6) filters cache
deserialization. No KAPT task appears in the reviewed graphs; independent
inspection found no kapt configuration or apt-cache.bin/java-cache.bin in the
scoped build caches. This limits observed exposure, but is not a whole-program
reachability proof and does not erase a version-range match. No dependency was
silently upgraded to make a scan pass.

Generated Gradle verification-metadata.xml records observed checksums (TOFU).
It is not an independently authenticated publisher baseline. Maven cache hashes,
selected runtime graph, plugin graph and advisory results are separate evidence.
The earlier `:app:buildEnvironment` reported No dependencies because settings
plugin DSL was used; that successful command was **not** counted as complete
plugin coverage.

### Selected plugin/classpath mapping — completed, with findings

A separate guarded `:help --offline` reporter ran against the same source/AAR
and pinned Flutter included build; no APK rebuild or additional external
advisory query was used. The first reporter correctly failed on Gradle's
IllegalResolutionException for normal project configurations. Moving only the
capture into each project's own afterEvaluate callback supplied the managed
project context; no internal lock or error suppression was used. The failed
attempt and source are retained.

Final reporter job `b314afb9-a1a4-4a69-9898-2986e3a90ae4` ended01:48:49,
exit0. Evidence root:
`apk-builds/report-20261025T014817Z-634d3a5a/`; result SHA-256
`877f8c238af96817044d4ae4b71384ec2109b31fd026d80ed15f0eecff2cc317`.
All seven captured configurations were resolvable, with no missing config,
exception, unresolved dependency or artifact failure. Empty buildscript
configurations were recorded as empty, not promoted to extra coverage.

| Captured scope | Components / artifacts | Public Maven coordinate/version pairs | Matched pairs |
|---|---:|---:|---:|
| App settings plugin classpath |119 /125|117|6|
| Included Flutter plugin buildscript |30 /27|29|1|
| Included plugin compileClasspath |31 /60|30|1|
| Included plugin runtimeClasspath |31 /42|30|1|
| App root, app project, included settings buildscript |Each1 /0|0|0|

These scopes contain180 unique public coordinate/version pairs. Every pair
was already in the user-approved545 query; no extra disclosure was needed.
There are8 unique matched build-classpath pairs and9 distinct advisory IDs
within these scopes. Independent job
`150e678a-9d7f-4a89-9fbc-fdf86055a31e` at01:49:52 parsed all five reports,
verified189 distinct artifact files' actual bytes against recorded SHA-256s,
checked query inclusion and mapped the findings below.

| Selected build dependency | Advisory IDs / observed category |
|---|---|
| Commons Lang3 3.16.0 |GHSA-j288-q9x7-2f5v — recursion denial of service|
| jose4j0.9.5 |GHSA-3677-xxcr-wjqv — compressed-JWE denial of service|
| bcpkix-jdk18on1.79 |GHSA-wg6q-6289-32hp — risky cryptographic algorithm|
| bcprov-jdk18on1.79 |GHSA-574f-3g2m-x479, GHSA-9pwp-9qqc-pr26, GHSA-c3fc-8qff-9hwx, GHSA-qp49-qgx5-5m26 — GOST counter mode, certificate name constraints, LDAP and ASN.1 handling|
| JDOM2 2.0.6 |GHSA-2363-cqg2-863c — XML external entity handling|
| Kotlin Gradle Plugin2.4.0,2.2.21,2.0.0 |GHSA-r937-wjx7-w2jp — KAPT cache deserialization|

Thus the results are **not all cache-only**: those versions are selected
build-classpath dependencies. Conversely they are not among the47 selected
application-runtime Maven pairs, and presence alone does not prove execution of
the vulnerable methods. No blanket non-reachability claim is made. Two of the
selected Bouncy Castle advisories carry database critical labels:
[GOST counter-mode issue](https://osv.dev/vulnerability/GHSA-574f-3g2m-x479) and
[name-constraints issue](https://osv.dev/vulnerability/GHSA-9pwp-9qqc-pr26).
Their remediation/disposition remains open for a production build toolchain.
This mapping is not a complete inventory of all shaded, distribution-bundled,
test-only or dynamically loaded tool code.

`qa/phase6_native_build/apk-maven-snapshot-summary.json` records the public
coordinate sets, matched IDs, report hashes and exact source/artifact identities.
The retained full query/raw advisories remain in the native tools evidence root,
not a promise that the external database is immutable.

## Remaining limits and next gate

- Android device/JNI execution, GC/lifecycle/cancellation under Android,
  native ABI loading, synthetic round-trip UI on a device, performance and
  memory pressure on Android remain NOT RUN.
- No signed APK, release build, Play/App Store review, iOS/Mac build or
  distribution acceptance. No main merge, push, deployment or Mailcow start.
- No real key custody, recovery-key import/export, user histories, cloud picker,
  durable plaintext/ciphertext storage, auth/trust/outbox/entitlement restoration
  or E2EE claim was added by this spike. Generic host tests do not establish
  Android platform behavior.
- Known build-tool advisories and graph/coverage limitations require explicit
  remediation or justified disposition before production acceptance. An OSV
  zero-match result is not a penetration test or comprehensive supply-chain audit.
  Maven coordinates do not comprehensively cover Gradle/JDK bundled or shaded
  libraries, SDK executables, Flutter's native engine, or all compiler internals.
  Those artifacts' provenance/compile checks are not vulnerability-clearance
  claims; the prior Go binary/graph scan has its own explicit scope and findings.
- A later device test needs its own authorized device/signing/provisioning plan.
  The current artifact is unsigned and must not be presented as install-ready.

## Final independent state audit

Job `1c8b6770-eb90-4f1f-a32a-f9fc926b4a77` ended01:50:28, exit0:
all270 tracked mobile-file hashes still match the captured build source; only
four Android build/config/ignore paths differ from scaffold eb8d521. Dart,
Kotlin application and test source were not changed in this build continuation.
APK/AAR hashes match the subjects above. Main remains clean5f3433b; QA changes
are confined to its separate development branch. There were no live owned
Java/Dart/Go/native-build processes and no signing/device-key or heap-dump files
in the scoped tools/project inventories. The owner limit remains4GiB, with
oom/oom_kill0; resource-pressure events did occur and are not mislabeled as
OOM kills. All18 Mailcow containers remain stopped. No global setting was
changed by this QA pass.

The final reporter budget was8,529,349,871 bytes (<8GiB), free9,978,998,784.
No further build is requested by this report. The completed milestone is an
audited **unsigned compile-only feasibility artifact with disclosed dependency
findings**, not a production/security approval or device-ready release.
