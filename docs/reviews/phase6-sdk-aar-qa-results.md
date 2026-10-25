# Phase 6 — Android SDK and cross-built AAR QA

2026-10-25 UTC. **Scoped compile-only acceptance, with disclosed advisory and
scanner limitations. Not Android execution, APK acceptance or production approval.**

## Exact scope

- Go source: `5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff`, clean; all290 tracked
  source files unchanged during the final independent checks. The24 archive-core
  files remain the previously reviewed8155772 implementation.
- AAR SHA-256: `05a6410ff782676cb656e801c03c16af86ae0175dd7e813ea7be3a8ed4f8d95a`.
- Contained `jni/arm64-v8a/libgojni.so`:
  `35ce2cbfbfa76910092b6995c6c29502ea976af839eaf75706a9a1428e39f83e`.
- Exact effective build modfile:
  `5dcf29a69ea79031e761c9a903fbfd6582dd5944a1c9b2707cd9c0486c88ef6c`;
  corresponding sum: `499f336ff315cb42122c1190e819f3a38050641eedeedbdd3674bcf774c6387c`.
- Go1.27.3, age1.3.2, x/mobile
  `v0.0.0-20261011034528-197770444867`, NDK30.0.16248370, arm64, minimumAPI24.
- Mobile APK preparation commit at handoff:
  `bbd56e561b5bac419f5ec5d09fd00482ee37e708`; no APK result is claimed here.
- Main remained clean `5f3433b23d8a29999c24943414ff1fdbcc40f46d`.

The AAR was cross-built by the implementation agent. QA did not claim a second
native build; it independently inspected its bytes, reviewed actual buildinfo
and Java ABI output, reran17 independent host tests against the effective module
selection, and scanned the actual new binaries. Host tests do not execute JNI.

## SDK license and installation

The initially approved official Android download page displayed the April28,2026
GoogleLLC agreement. The repository XML instead supplied the January16,2019
GoogleInc. agreement. These were not assumed equivalent: installation paused,
and the owner separately approved the actual2019 text on October24 at23:45:42.
The approved extracted text SHA-256 is
`1f8729233617b193fd619213792ae16a41b95d2bbbf525dfe66998252ba68b16`.

The isolated installer sent one acceptance only after exact normalized equality
of the sole displayed license body. Its first two attempts stopped before any
acceptance: an unanchored header expression matched a body sentence, then a raw
CR separator differed from a text-reader's normalized LF. The final parser
normalizes line endings and ANSI formatting, anchors the whole header, and still
requires equality of the complete body; it does not use substring approval.
QA independently checked the two raw captures and changed-party/appended-clause/
second-license negatives. A first QA-only parser probe itself had an overescaped
separator expression; the corrected probe passed. No failed parser attempt is
represented as installation success.

Developer install job `1de046d8-c2e6-433c-9057-33d4a9ddc95d` completed23:57:28.
QA full byte audit `164f43c9-0d20-42f4-afc0-60505ccefe80` completed October25
00:00:37, exit0: **21,144 regular files and39 symlinks** matched the four verified
archives, with path containment, ownership, package/root inventory and no
unapproved extras. Packages: CLI22.0/15859902; platform36 revision2;
build-tools36.0.0; NDK30.0.16248370. No emulator/platform-tools/adb package.

| Archive | SHA-256 | Installed regular files / links |
|---|---|---:|
| CLI22.0 | 4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583 | 141 / 0 |
| platform36-r2 | 37607369a28c5b640b3a7998868d45898ebcb777565a0e85f9acf36f29631d2e | 11,342 / 0 |
| build-tools36 | 5d9ac77fb6ff43d9da518a337b4fcf8f9097113df531d99ccefe80ef7ce8250b | 168 / 0 |
| NDKr30 | 753611f410d002cfcd3f3dc2ef49aad532089d3180b436c060a90bf0fcb64df2 | 9,493 / 39 |

CLI SHA-256 was compared to the official page; the other official XML package
checksums are SHA-1, with local SHA-256 additionally retained. Do not relabel
those local hashes as independently published SHA-256 values.

The installed SDK license fingerprint `24333f8a63b6825ea9c5514f83c2829b004d1fee`
comes from sdkmanager's canonical package text. Its normalized body equals the
approved raw XML text; its differing raw SHA-1 is not a different agreement.
The three sdkmanager-installed package.xml files all contain that approved body.
CLI was safely extracted and does not have a generated package.xml.

SDK evidence under `<tools>/logs/sdk-ipv4-20261024T2342/`:

| File | SHA-256 |
|---|---|
| repository2-4.xml | 13a7a28e4467408860995a32b5c3bc7b0e2f66088c21e42bf7ceabc025afc716 |
| installed-verified.json | 73777e58f03385db64c6cbabeac2168abebb1e7119c2bd21164bf9ffa2ccc98d |
| license-accepted.json | 6baa343365f8ebd09da29a42c2054361dfbf13254d283913af7bca6ff38f3c0c |
| verified-archives.json | 1339445f77369f48affe999cfa103aedf4ad4c33f81ebe5f4f7af375ca0d42c6 |

`<tools>` means
`/home/chatbot/wainak-dev/native-archive-tools-phase6-20261024`.
The independent SDK audit helper is included with this report. The actual
installation was not rerun by QA. A later APK build must recheck this inventory.

## AAR build provenance and failures

Pinned gomobile was built offline from the reviewed x/mobile source. Its SHA-256
is `a1f2470c5834bb22ed6485065d0f2f809e9ecc0ccdb11838daabdbaf6b5d8ff8`.
No `gomobile init` or `@latest` installation was used. The initial bind attempt
failed closed because gomobile promoted the complete module list to root
requirements, activating the unused x/net0.61→x/crypto0.58 edge. Offline mode
prevented that unapproved download; no AAR or source upgrade resulted.

The approved second attempt used an attempt-owned copy of the frozen binding
mod/sum through the supported `-modfile` mechanism, not a vendor patch or new
replace/exclude. Its generated unused target go.mod was retained for diagnosis.
The actual cross-build selected age1.3.2, hpke0.4.0, crypto0.55.0 and pinned
x/mobile, plus the exact local facade/core. Buildinfo records Android/arm64,
CGO_ENABLED=1 and c-shared. The effective module graph selects x/sys0.49 for host
checks; the native shared object's buildinfo does not list x/sys or x/net.

A subsequent complete-graph inspection needed x/net0.57 metadata, not source.
Only the official .info/.mod and authenticated SumDB record were fetched under
separate metadata-only permission. No x/net0.57 ZIP or extracted source appeared.
The .mod record is `h1:KpXc8iv+r3XplLAG/f7Jsf9RPszJzdR0f58q9vGOuEU=`.
An evidence wrapper initially expected an optional GoModSum JSON field that this
query omits; the fetch had succeeded. The corrected offline proof retained the
failure and verified standard Hash1 against the signed record. Source, effective
mod/sum and artifact hashes remained unchanged.

Developer verification report:
`<tools>/gomobile-build-197770444867/attempt2-modfile/verification-result.json`,
SHA `db48e52e79ab3ab638ff32c618b612055c55ae03ea35acd437fbd736c7f7afa0`.
Metadata proof `metadata-only-xnet057/result.json` in that directory:
`c11d31c00e1608000da70ac0d459b359de8e75b1c77234602aa065b6a51f8602`.
Developer's26 host core/facade tests on this effective graph passed; these are
separate from the independent17 below.

## Independent gates

1. **AAR structure PASS:** bounded read-only ZIP/CRC/member hashing; six expected
   entries; one arm64-v8a shared object, AArch64/ET_DYN; all three PT_LOAD segments
   have16384-byte alignment and congruent offsets/addresses. AAR's compressed
   member is not itself an APK zipalignment pass. Android's16KiB guidance requires
   packaging checks as well as ELF checks. [Android page-size guidance](https://developer.android.com/guide/practices/page-sizes)
2. **ABI review PASS:** actual classes.jar/javap output matches the seven public
   generated methods: cancel, close, epoch, exportHistory, historySnapshot,
   importHistory and newSyntheticSession, with primitive long/byte[] shapes and
   declared exceptions. No real-key/owner constructor was added.
3. **Independent host17 +6 subcases PASS; vet PASS:** unchanged QA overlay
   SHA`16175d21a67563803c57b6c14fc0714959a1be4c893bfe48766227359a493603` ran against
   the exact effective modfile, not the older original dependency graph. Covers
   owner/catalog isolation, replay/conflicts, epoch/cancel/close publication and
   import commit races, input/output copies, stale handles and capacity lifetime.
4. **Complete metadata enumeration PASS:**22 entries =19 external public modules
   plus3 local modules; no unresolved node. This count differs from the earlier
   pre-tidy graph and is not inherited evidence.
5. **Actual new binary scans completed:** gomobile has zero findings in this
   snapshot; libgojni.so has three module-only findings, no package/symbol trace.
6. **Source module-only scanner NOT PASS:** first invocation incorrectly supplied
   a package pattern; corrected invocation then requested go.mod updates during
   loading, which readonly mode refused. Neither failure was suppressed or
   converted to success. A separate supported offline query of all19 public
   selected module/version pairs plus Go1.27.3 stdlib/toolchain completed instead.
   This closes advisory-version coverage, not source-loader/callgraph validation.

Final independent run `328f4f08-e337-4229-9252-acd8cd518c14`,00:40:40 exit0.
Earlier failed scanner setup jobs `1cea2fc9-39d8-4f22-a727-46e5276443e2` and
`a8b8c23f-04b6-4151-bed3-12c193736b0a` are retained; their host tests passed but
those runs did not reach final completion. The final run used fresh evidence,
not overwritten logs.

## Advisory findings — not a clean security bill

The exact selected public graph has **eight matching advisories**:

- x/crypto0.55: GO-2026-5932 (unmaintained OpenPGP), GO-2026-6354 and6355 (SSH DoS;
  fixed0.56). The native binary scan reports these only at module granularity,
  with no affected package or symbol trace. [SSH advisory](https://pkg.go.dev/vuln/GO-2026-6354)
- x/net0.57: GO-2026-6603,6610,6611,6612,6617, involving HTTP/2 exhaustion,
  malformed framing or races; fixed0.60. This module is metadata-only in the
  evaluated graph, not listed in either actual gomobile or native buildinfo,
  and its source ZIP was not installed. [HTTP/2 advisory](https://pkg.go.dev/vuln/GO-2026-6603)

These are not eight demonstrated vulnerabilities in the synthetic archive path.
Conversely, absence of symbol traces is not proof that all vulnerabilities are
absent. No silent dependency upgrade was performed. Before production or reuse
with additional imports, reassess these pins, maintained fixes, reachability and
all platform dependencies. This report permits only the next unsigned compile
experiment; it does not approve deployment or general-purpose cryptography.

### Data boundary for scanning

The initial combined test/online-scan operation was explicitly denied before
execution because of possible private module metadata disclosure. Readback proved
its runner absent. QA did not replay it through another writer or route.

The parent approved a materially safer operation: a downloader with a fixed
allowlist of public modules and only public database/GO-ID URLs, no project or
artifact input, redirects, proxy inheritance, request body or private query.
It fetched286 public advisory records plus the complete public module index,
978887 JSON bytes, at00:38:25–00:38:30. Then every scanner used explicit
`-db=file://...`, offline Go/proxy/sum/toolchain settings and disabled telemetry.
The reviewed govulncheck1.9 client maps file:// to filesystem reads. This is a
verified client/configuration boundary, **not a kernel network-namespace claim**.
The public database protocol is documented by Go. [Go vulnerability database](https://go.dev/doc/security/vuln/database)

Snapshot `<tools>/public-go-vulndb-20261025T0038/manifest.json`:
`1370a12bae56c5ebd201d5557887beca94ee57eba66b6ff68042f1dc46656cb7`.
Database modification time: `2026-10-21T00:27:29Z`. The manifest records every
requested public URL, compressed/uncompressed hash and the explicit allowlist.
It is complete for this selected public graph, not all modules in the world.
Raw OSV messages emitted by binary mode include many historical/nonmatching
entries: **do not count OSV-message IDs as findings**. The eight IDs above come
from the version-filtered public queries; the native scan's finding events are3.

Final independent evidence:
`<tools>/qa-aar-offline-20261025T0041/result.json`, SHA
`184cd58be34ccd842c2765b537fb080aa696880b0e6703ba8060d4682c8af79e`.
Runner SHA`0ae1e63818d4bcd2fb8cf1cfb923fed04ed86c33dd9a2ba9a4039ed5818319c4`.

## Cleanup and remaining acceptance gates

Independent audit `28146689-6b82-4527-a740-df96ca0dde9d` at00:40:55: no owned
Go/scanner/compiler/Flutter/Java process, empty attempt tmp, clean source and
main, owner OOM/oom_kill counters0. The4GiB/2560-heap configuration was unchanged;
Mailcow was not started. The resource window was explicitly released to the APK
owner; no parallel heavy work was started by QA.

**NOT RUN / unresolved here:** Kotlin-to-AAR compilation, unsigned APK creation,
APK signature/zipalign/ELF checks, complete resolved JVM/build-plugin advisory
assessment, Android JNI runtime/device tests,16KiB-device tests, cancellation
across a real engine, iOS builds, cloud/file picker, user key custody, zeroization,
release/store approval. Synthetic Go keys and histories stayed in RAM/private
pipes during host tests; no real user data or persistent access was introduced.

No main move, push, deployment, signing key, adb/KVM use or global network change
was performed by QA. Keep the actual APK acceptance in a later exact-artifact
addendum rather than retroactively upgrading this report.
