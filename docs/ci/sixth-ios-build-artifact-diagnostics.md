# Sixth iOS attempt: complete bounded artifact evidence

Build `6adde0f94a72334e32e4f8b9` used exact commit
`8c459243ff25cb3239b32a6f90c7107baeefec43` and failed on 2026-10-25 at
11:03:06 UTC. Native duration was 147.998 seconds; failure stage was
`artifact-inspection`, gate category UNKNOWN_TOOL_FAILURE. The last command
`slice-symbols` passed with exit 0 in 1.684 seconds; cleanup errors were empty.

Source order establishes completed target graphs/import closures and entry into
artifact inspection. The first inspected slice's header hash, module map,
container and arm64 checks preceded the successful nm command. The next
acceptance predicate checks seven defined text symbols. Neither raw nm output
nor which symbols were missing/represented differently was available. No
symbol-generation root cause or artifact acceptance is claimed.

Pinned generated Objective-C declarations and upstream implementation naming
agree with the seven required functions. LLVM's official llvm-nm documentation
(https://www.llvm.org/docs/CommandGuide/llvm-nm.html) describes BSD default output
and optional addresses for bitcode. Addressless output is therefore worth
observing, but is NOT established for this artifact. The prior strict acceptance
regex remains unchanged; this patch does not accept new formats. Upstream
framework MinimumOSVersion100.0 remains unchanged, as do actual Mach-O minimum
15.0/platform requirements and every crypto/dependency/resource guard.

## Finite diagnostics across the whole artifact stage

- Fixed check/reason/outcome enums, only device/simulator/unknown variant labels.
- Only seven fixed ABI function names may appear in defined, undefined, nontext,
  missing, hexadecimal-text, addressless-text and unrecognized sets.
- BSD/POSIX/Darwin/other counts are observations, never acceptance decisions.
- Load-command counts distinguish expected platform IDs and matching minimum
  values without emitting unknown platform/version text, paths or raw output.
- Diagnostic parsing is bounded to8MiB,100000lines and4096characters per line;
  tokenization avoids overlapping-whitespace regex cost. Incomplete observations
  are marked incomplete. Existing command output/deadline limits are unchanged.
- Outer projection independently validates all fields/counts/known names and
  discards arbitrary values. Invalid optional diagnostics cannot erase primary
  failure status/stage.

Safe independent semantic checks now finish across both validated slice paths
before an aggregate failure. Malformed metadata/paths or containers skip their
unsafe dependent operations. Any failed check remains sticky and prevents
artifact success and therefore application building. Command/resource/cancel
failures still propagate immediately, unchanged; aggregation does not swallow
those errors. No native binary is executed by inspection.

Synthetic tests exercise ordinary/alternate symbol representations without
relaxing acceptance; missing/undefined/nontext symbols; unknown/private values;
bounds; both-slice independent failures; bad metadata, links/paths and containers;
resource-failure propagation; malformed plists; and projection validation.
Full repository Python gates/publication scanning apply to the final commit.
They are not Apple/native compilation, runtime tests or security acceptance.
No seventh run, signing, billing, main change or deployment is included.

## Resumption validation — October 26, 2026

The owner resumed Wainak development after the freeze. The authenticated server
was verified before work; the clean development base was exactly
`8c459243ff25cb3239b32a6f90c7107baeefec43`. The previously blocked source transfer
had not executed. It is now applied only in the isolated development worktree,
with all preimage/postimage hashes checked and all project writes as `chatbot`.

At 05:41:34 UTC, full offline Python verification passed: 137 CI tests plus
68 native static/mock tests, 205 total with no skips. The 25 artifact-specific
synthetic tests include three new resumption regressions proving that the real
result-file writer and bounded outer reader preserve both-slice evidence,
malformed optional detail cannot hide the primary failure, and a final resource
audit failure cannot leave a PASS result. Source/configuration preparation,
native `--check`, and `git diff --check` also passed.

The strict acceptance predicate, all 26 dependency pins, crypto core, workflow,
resource limits, native targets, and application source remain unchanged.
The 4 GiB owner-service limit and the original 2.5 GiB compiler-wrapper digest
were reverified without modification. The original local and remote main refs
are untouched. The preceding 180-test baseline was separately rerun before edits.

This validates diagnostic source and synthetic behavior, NOT the actual cause
of the sixth failure, Apple linking, an iOS application, device execution,
signing, or security/release acceptance. No seventh cloud attempt was started.
Public development-branch publication and another cloud attempt remain separate
explicit decisions. This report does not authorize them.
