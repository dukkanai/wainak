# Second iOS CI attempt: host-harness correction, not an iOS success

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

## Observed cloud result

The second manually authorized Codemagic run, `6add93a54a72334e32e4e9eb`, tested
commit `430688ac603b35cd9f95f83caf8df38b77df8fae` and failed on 2026-10-25 at
05:49:58 UTC. Xcode selection/version and Flutter identity/source checks passed.
The native command ended after 1147.44 seconds with:

- status `FAILED`, stage `new-policy-host-tests`;
- primary gate `command_failed_native`, operation `wait_command`;
- `cleanup_errors: []`.

The retained cloud log contained no inner command name, test name or raw test
output. Therefore neither a particular failing test nor its underlying cause is
established. This is distinct from the first run's unlocated `PermissionError`.
Apple framework/app compilation had not yet been reached according to this
stage marker. Neither run establishes an unsigned iOS artifact or runtime result.

## Narrow source corrections

1. The old host runner incorrectly pointed a bounded, test-owned 512 MiB canary
   scan at the entire workspace, including Go toolchain/module/build caches.
   This source-level mismatch is corrected, **not asserted as the observed
   cloud failure's proven cause**.
2. Host tests are compiled separately, then run with documented `test2json` in
   an owned root containing their public fixture sources, cwd, HOME and TMPDIR.
   CLI children explicitly receive only the validated owned HOME/TMPDIR and cwd;
   generated identities still use inherited anonymous FD3, not files/env/argv.
   External compiler/module caches and executable hashes must remain unchanged
   across non-fuzz runtime tests. This is not an OS sandbox or universal leak
   proof. The original 512 MiB scanner and crypto assertions remain.
3. Compile plus runtime share the existing 180-second package deadline. Supported
   `go test -json -fuzz` retains its existing 60-second limit and public-schema or
   ciphertext-only corpus scope; mutable fuzz cache deltas are recorded separately.
   Host CLI/tests consistently use CGO0; Apple targets remain CGO1.
4. Extraction reserves its existing bounded payload plus bounded metadata inside
   the unchanged 8 GiB aggregate / 4 GiB free-space limits. Full accounting is
   periodic, at phase/command boundaries and after final evidence writes instead
   of recursively traversing the growing tree for every archive member. This is
   monitored accounting, not a kernel-enforced quota. Cancellation remains checked.
5. Public diagnostics expose only nine fixed host-command names, bounded exit/time,
   fixed failure categories and exact public top-level Test/Fuzz names snapshotted
   from hash-verified source before the child. Runtime subtest suffixes, raw Go
   `Output`, paths, argv, exception messages and arbitrary result fields are never
   projected. Strict, bounded JSON needs a valid terminal package result; malformed
   or contradictory exit-zero streams cannot count as a host-test PASS.
6. Cleanup, final audit and evidence-write failures remain failures without masking
   an earlier failure. A later unlisted command clears the previous host receipt.

Core archive/facade code, dependency versions, artifact targets, tool pins and
resource/time limits are unchanged. The interop test-only delta is recorded in
`ci/native-source-deltas.json`; the original imported-source provenance is retained.
The workflow remains manual, without triggers, publishing, signing credentials or
artifact upload. Android's previous artifact and both main branches are untouched.

## Validation and limits

- Native helper suite: **67/67 Python static/mocked tests passed**, independently
  rerun against the frozen 19-file manifest.
- Outer diagnostic/projection suites: **49/49 passed**, independently rerun.
- Full server checkout: **151/151 Python static/mocked tests passed** (84 CI/iOS
  plus 67 native), with zero skips. Source-provenance, iOS/native `--check` and
  whitespace gates passed at 06:19:54 UTC, job `e5f8acea-f87a-4a55-82af-05dff7f0f416`.
- Additional independent checks: 72 native-to-outer failure-schema combinations
  and five JSON encoding/depth negatives passed. These are not native runtime tests.
- The v3 Go tests, CLI, Apple compiler, XCTest and cloud workflow have **NOT RUN**.
  No third cloud run is authorized by this source preparation.
- Existing dependency advisories and device/runtime/security-acceptance gaps remain.

The first guarded 12-file write was explicitly denied before execution. Fresh
user approval at 06:18:43 UTC authorized the same write; one guarded retry
succeeded at 06:19:24 UTC, job `72b2f2c9-7512-468c-96ee-30187a0c0adb`. No alternate
writer or split retry was used. This report does not authorize another cloud run.
The final commit must pass the publication scan and the same static checks before
its development-only push; no main change, signing, billing or deployment is included.
