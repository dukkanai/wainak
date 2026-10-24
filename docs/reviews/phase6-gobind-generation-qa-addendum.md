# Phase 6 — gobind source-generation QA addendum

2026-10-24. This follows `phase6-native-scaffold-qa-results.md` without changing
its mobile/Go candidates or promoting source generation to native execution.

## Exact artifacts reviewed

- Go facade: `5ff300d48b38e98212ff8b5a7333dd92f8c1c3ff`.
- Mobile: `eb8d521157597ac114ba905c699ad7ad68185b43`.
- Main unchanged: `5f3433b23d8a29999c24943414ff1fdbcc40f46d`.
- Tool: `golang.org/x/mobile v0.0.0-20261011034528-197770444867`, full upstream
  commit `19777044486779222400e9ca16c4306f9c6dbfa9`, module checksum
  `h1:rav73cdd7OQUPgt1aIFbZQTiPNnjfueKXvfOiLCY0Ss=`.
- Tool binary SHA-256:
  `90a5ff9cc0a7c3502342c1dec515ef00877794aa77beb37eb66d12c9c2d8a083`.
  Buildinfo records Go1.27.3, CGO_ENABLED=0, Linux/amd64, trimpath and pinned
  x/mod0.42.0, x/sync0.24.0 and x/tools0.52.0 dependencies. No automatic Go upgrade.
- Tool root:
  `/home/chatbot/wainak-dev/native-archive-tools-phase6-20261024/gobind-197770444867`.
- Developer generation-manifest SHA-256:
  `415c4b0e8e75f7636174c0623f7d64a3965508052cff4c29c69ac2b6a2bc9589`.
  It retains exact command, source heads, module/ZIP/license manifests, buildinfo,
  generation diagnostics and all17 generated-file hashes.

Developer executed, and QA independently inspected the artifacts from:

```
# cwd: <tool-root>/binding
<tool-root>/bin/gobind -lang=java,go -outdir <tool-root>/generated wainak.local/archivebridge
```

QA did not claim a second independent generation run. It rehashed the tool,
all17 outputs and retained provenance artifacts, verified module caches, read the
actual Java source and matched the Kotlin-facing signatures. Generated
`java/archivebridge/Archivebridge.java` SHA-256:
`602ea690eec67ca31348732242a93b12a9f8a40fc9cb397e1487fb3aff9e56e6`.

Verified public native methods, each declaring `throws Exception`:

```
long cancel(long handle, long expectedEpoch)
void close(long handle)
long epoch(long handle)
byte[] exportHistory(long handle, long epoch, byte[] recordsJSON)
byte[] historySnapshot(long handle, long epoch)
void importHistory(long handle, long epoch, byte[] ciphertext)
long newSyntheticSession()
```

The actual Java class is `archivebridge.Archivebridge`; names and primitive/array
shapes match the proposed Kotlin calls. There is no key-string, real owner or
caller-catalogue constructor. Generated `go.Seq` imports Android Context, so JDK
availability alone cannot compile the complete generated binding.

## Independent advisory assessment

Pinned govulncheck1.9.0 used official database modification time
`2026-10-21T00:27:29Z`; no application source was uploaded to an audit service.

- Actual gobind binary symbol scan: completed, zero findings in that scan.
- Proposed binding facade source+test graph: completed, three module-only
  x/crypto0.55.0 findings (GO-2026-5932, GO-2026-6354, GO-2026-6355), no package or
  symbol trace. The existing report's risk disclosure still applies.
- Complete binding module graph: completed module-level scan of22 external
  modules; the same three findings.
- Tool graph: its nine exact external module/version pairs were independently
  proven to be a subset of that complete scanned binding graph. None matched a
  reported finding. This is an explicit module-level inference plus the separate
  actual binary scan, not a claim that a standalone tool-root module scan passed.
- `go mod verify` passed for both tool and binding module roots.

The pinned x/mobile code-generation graph selects x/sys0.49.0. The previously
tested facade/core module retains x/sys0.47.0 unchanged. That difference is
explicit, not a silent application upgrade. Source generation is not runtime
regression evidence for the newly selected graph; future linking/execution must
validate its exact dependency graph. No native binary scan is possible before a
native binary exists.

## Failed scanner setup attempts retained

An initial module-only invocation supplied a package pattern; govulncheck refused
it. The corrected complete binding scan omitted the pattern and completed.
The standalone tool root has no Go files, so its module-only scan failed package
loading. A temporary empty-package comparison attempt did not complete and is
not counted as a pass. All temporary files were cleaned. The final exact module
subset proof above closes the module-coverage question without inventing a
successful standalone scan. Original error artifacts and terminal jobs remain
available; no product or dependency source was changed to suppress findings.

## Evidence and cleanup

Evidence:
`/home/chatbot/wainak-dev/phase6-mobile-qa-evidence/eb8d521157597ac114ba905c699ad7ad68185b43/gobind/`

| Artifact | SHA-256 |
|---|---|
| independent-gobind-review.json | 38b1ff95062b00ee0fade2d4d0da2d829748bf831a3002327545a47e595b1f23 |
| gobind_binary_advisory.json | 1111c4820d22d6474a78429675220aae901ecb213575479ceae4ab84f555f035 |
| binding_facade_advisory.json | 6aa6836e3f2bb2c441da54250b023751f72feba5fd226749e13995c601d91371 |
| binding_all_modules.json | 5e0cee8b11a5951d7bdfa80a0fc73d2de9636a19f15ce18b4262e38c481fe8a2 |

Readback jobd6121834; initial completed binary/source scans and module verifies
in jobf22886fd; complete binding module scan in job70d13e38. Final module-set
proof/audit job `4c636cd6-e943-4fe8-a5d0-d0343513ea17`, terminal18:15:12 exit0.
All17 generated outputs/provenance artifacts and source heads stayed unchanged;
Go/mobile/main were clean, owned temporary directory empty and no live owned
compiler/scanner/native process remained. Resource settings and Mailcow were not
changed. The single heavy window was explicitly released after this audit.

## Updated gate status

Source generation and actual Java API-name/type matching now have evidence.
Java/Kotlin compilation, JNI linking/loading, NDKr30 compatibility, AAR, unsigned
APK, signing/alignment inspection, device/GC/array-lifetime behavior and real
Flutter→JNI→Go execution remain BLOCKED/NOT RUN. No stub Android classes were
introduced to fake compilation. SDK acquisition still requires resolution of the
official-endpoint404 blocker. This addendum does not authorize a merge or deploy.
