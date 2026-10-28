# First manual iOS build: failure and diagnostic-only follow-up

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

## Observed result

One authorized Codemagic Mac M2 build ran against `7add32fbe30ba3f0e299a63fa557206dff18a34d`:

- Build ID: `6add878e4a72334e32e4e82c`.
- Terminal: **FAILED**, completed 2026-10-25 04:59:22 UTC.
- Source/configuration gates passed; the manual unsigned compilation step exited 1 after approximately 20 minutes 9 seconds. Total UI duration was 21 minutes 40 seconds.
- The expanded step log and its downloaded 142-byte file contain only `iOS preparation/build gate failed: PermissionError`, followed by the failed-step message. No operation, path or traceback was exposed.
- Personal billing showed 21/500 free Mac minutes used, 479 remaining; no paid subscription was enabled.

**The root cause is unknown.** The elapsed duration resembles an existing 1200-second command deadline, but does not prove a timeout. A child/compiler failure would normally be converted to an outer gate error; a later process-group or file-cleanup exception could have replaced it. This is a source-based hypothesis, not a diagnosis of the cloud host or a successful compilation claim. No additional cloud run was started for this follow-up.

## Narrow source change

This follow-up changes diagnostic/error handling only. It does not change native code, dependency versions, resource budgets, timeouts, signing, credentials or application behavior.

- Emit fixed command-stage start/end markers and allowlisted error type / errno / gate-code projections. Never print exception messages, filenames, environment, argv, native test output, keys or archive bytes.
- Keep the original exception and traceback as the primary failure. Collect signal/probe/wait/FD/log/manifest failures separately; one cleanup failure must not prevent attempts to reap and close other owned resources.
- Permission errors do not mean the process group is gone. An unverified group remains a failure. Cleanup still targets only the process group created by the driver, with the existing bounded TERM/KILL/reap policy and no elevated permissions.
- Read only an opened, no-follow, nonblocking regular native result descriptor with a maximum-plus-one byte cap; reject duplicate/nonfinite/deep malformed JSON without masking the primary exception, and project fixed status/failed-stage values. Unknown, malformed or unreadable summaries are explicitly unavailable/invalid; raw child logs remain private.
- Preserve the primary error during final owned-config cleanup and source-integrity checks. Publish the final success result only after cleanup succeeds.

The first build remains failed. These changes improve evidence for a future separately authorized run; they do **not** claim to fix its unknown root cause.

## Validation boundary

The diagnostic tests use mocked processes, signals, clocks and controlled filesystem errors. They exercise timeout preservation, PermissionError branches, fail-closed cleanup and redaction with a synthetic canary. They do not send a signal, launch a compiler, access the network, reproduce macOS permissions or validate the native/iOS runtime. Exact integrated test counts and commit identity are recorded in the development handoff; previous source-preparation results remain in `preparation-verification.md`.

No new cloud build, signing, device/simulator run, artifact publication, main update or deployment is included in this patch.

## Exact integrated static result

At 2026-10-25 05:18:48 UTC, job `c8a0f294-4a74-4fc4-a573-f06219c923d9` passed all **109 tests**: 70 CI/iOS cases (35 existing +35 diagnostic cases) and 39 native static cases. Both recipe `--check` paths, source provenance and diff checks also passed. Independent reviewers additionally exercised output-bound/metadata-write/nonzero-child failures and unchanged depth/encoding bypass probes without real subprocesses or signals.

One initial integrated diagnostic test failed because the server Python parsed deeply nested JSON that raised RecursionError locally. The reader now imposes its own 64-level quote/escape-aware bound, independent of interpreter recursion behavior. Review then found UTF-16/32 autodetection could disagree with the byte scanner; strict UTF-8 decoding and text-only JSON parsing closed that concrete bypass. Four encoding negatives, escaped-string controls, depth64/65 boundaries, file growth, symlink/FIFO and canary redaction checks now pass. These are fixes to the new diagnostic reader, not evidence about the first cloud failure.

Frozen tested source SHA-256:
- `ci/ios/build.py`: `e8e75f481df32fbaaeef8f65f7eeaf4abf3c4921e2929a87364d77b932c886cc`
- `ci/ios/diagnostics.py`: `9e16aa8afc4e2f561c77312f72c32f0e52c127a7167fdd495aa85d7e1fc998e0`
- `ci/tests/test_ios_diagnostics.py`: `de322f0b683635545931d6cd973ae273199a852ee392d6a0afa7af13937e9a68`

The Codemagic workflow, module locks, native implementation, application sources, existing limits and deadlines are unchanged. Publishing this development patch does not authorize or start another build.
