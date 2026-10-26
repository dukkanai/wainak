# Stage5: native-stage lifetime and resource receipts (local candidate)

Base: eacbcf13c0061253bc9366d1b4b1221dfe591eae. This is a local repair candidate,
not permission to publish or start another cloud job.

## Observed ninth attempt

Codemagic build 6adf279d4a72334e32e548bd ran the exact base. The native stage
passed all22 artifact checks: both slices had all7 required native hex-address
text symbols and23 accepted load-command records. Subsequent locked pub,
native Dart tests, iOS opt-in Dart tests, config and device settings passed.
The device compile then failed the unchanged workspace_budget guard after
8.371seconds. The public receipt did not contain numeric usage or component
bytes. No exact excess, physical-disk exhaustion or accounting arithmetic bug
has been established.

The logical-byte guard counts .ci-work, app build/.dart_tool/iOS ephemeral and
positive Flutter SDK growth. Native build tools/caches were retained alongside
subsequent Xcode derived data. The roots are not obviously nested; retained
builder data is a lifecycle cost, not proven double counting.

Three cleanup EPERM errors are separate secondary observations. Apple XNU's
killpg1 filters zombie group members and may return EPERM when no eligible
member remains. A source-faithful model fits the receipt, but it is not actual
Mac reproduction. This stage does NOT change cleanup_process, signal policy,
permissions or its fail-closed uncertainty handling.

Primary reference:
https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sig.c#L1612

## Narrow change

1. Emit fixed-key numeric logical-byte component receipts with command outcomes.
   No paths, command output, environment values or exception messages are added.
   A failed measurement clears the old sample rather than presenting stale
   numbers as the current measurement. The8GiB ceiling and4GiB free-disk floor
   are unchanged. Allocated bytes are not substituted for logical bytes.
2. After native PASS, successful whole-group cleanup, matching command/license
   receipts and validated exact XCFramework inventory/slices, retire only:
   .ci-work/native/go-darwin-arm64.tar.gz
   .ci-work/native/toolchain
   .ci-work/native/gocache
   .ci-work/native/compiler-tmp
   .ci-work/native/bin
3. Keep the framework, result/commands/logs/licenses, module cache, generated
   -work sources/target records, host-test fixtures, binding and tools modules.
   No subsequent application-stage command uses the retired five entries.
   Tool/archive/cache bytes themselves are no longer retained; authenticated
   acquisition/build-info/provenance records remain.
4. An exclusive separate retirement receipt prevents replay and records fixed
   target logical bytes, retained-evidence digest, completed entries and partial
   failure. The original native result is not rewritten. An abruptly killed
   process cannot write PASS: the initial/checkpoint receipt remains FAILED.
5. Preflight all five targets before unlinking. Descriptor-relative no-follow
   traversal checks ownership, types, single-link regular files, same device,
   detected mounts, bounded depth/count/time and inode/metadata drift. No chmod,
   broad cleanup, external cleanup command or fallback is used. Retained
   framework, result, commands, license and log hashes are checked before/after.
   Failure aborts the build; partial removal is not rolled back or auto-retried.

Runtime retirement needs explicit approval in the next cloud-run request. No
existing server tool cache or previous attempt has been removed for this change.

## Verification at this candidate

Local job06f63191-25ed-4b27-bd61-14282720a52b:
-200 ci/tests cases PASS (36 new resource/lifecycle tests).
-68 ci/native cases PASS.
-All three static source/native/iOS checks and git diff --check PASS.
-No skipped cases.
-The existing strict symbol parser and cleanup_process file are byte-identical.

New tests use small private temporary fixtures. They include real symlinks,
hardlinks, FIFO, read-only paths, file/directory drift, evidence preservation,
partial deletion and replay rejection, actual isolated process death,
cancellation, deadlines and FD closure. Foreign-owner/cross-device/detected-
mount controls are injected checks, not real ownership changes or mounted
filesystems. No real compiler, network, cloud run, signing or deployment occurs.

## Limits

The candidate has not executed on Mac or measured actual native cache sizes.
Reclaimed logical entries do not prove an equivalent immediate physical-disk
gain, nor that later Xcode phases will fit. Sampling is not a hard quota.
Deletion is not a cross-file transaction or protection against hostile same-UID
writers/privileged actors injecting same-device mounts. FD/inode checks constrain
ordinary drift; they are not a global immutable-filesystem guarantee.
Independent review is tracked separately and must pass before publication.
