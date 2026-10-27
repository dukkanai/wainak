# Strict unsigned simulator compilation — stage8

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Base: `cf4a5e9c8872b79de568bbeae342b3c8dc27e9af`.
This local repair preserves compile-only acceptance; it does not authorize
signing, publication, another cloud run, simulator execution, or app release.

## Observation and causal limit

Run12 `6adf519a4a72334e32e55727` compiled device and simulator targets.
The device unsigned check passed. The simulator unsigned helper failed after
successful compilation, with no resource or cleanup failure. Its original
helper suppressed codesign's reason, so this is **not proof of the exact
signature class or tool output in that cloud artifact**.

Apple's [linker source](https://github.com/apple-oss-distributions/ld64/blob/main/src/ld/Options.cpp)
defaults to ad-hoc signatures for arm64 simulator outputs, but not arm64 iOS
device outputs. [Apple DTS](https://developer.apple.com/forums/thread/791270)
documents automatic linker ad-hoc signatures and the `-no_adhoc_codesign`
control. LLVM's [Mach-O regression matrix](https://github.com/llvm/llvm-project/blob/main/lld/test/MachO/adhoc-codesign.s)
covers executable, dylib and bundle variants.

An independent tiny real LLVM21 fixture reproduced this platform distinction:
device/default and device/no-adhoc had no LC_CODE_SIGNATURE;
simulator/default had it; simulator/no-adhoc did not. These Linux-hosted
synthetic outputs were inspected, never executed, then their owned temporary
directory was removed. They are not the selected Apple binary or cloud artifact.

## Narrow change

Only the simulator command appends `-Wl,-no_adhoc_codesign` to the existing
`OTHER_LDFLAGS=$(inherited) -framework Archivebridge -framework Foundation`.
Settings and compilation use the same command policy. Reported flags are
checked on every planned target, including RunnerTests; contradictory,
missing, duplicate or malformed controls fail. The device linker setting
remains identical. No project/SDK files or generated binaries are rewritten.

The unsigned helper still rejects every codesign-detected signature, including
ad-hoc signatures, and requires its existing unsigned message for success.
A positive LC_CODE_SIGNATURE observation also rejects a contradictory unsigned
tool message and remains positive even if a later load command is malformed.
Explicit signature/authority/code-directory metadata rejects independently of
the tool return code or an accompanying unsigned phrase. Unknown or malformed
metadata is labeled honestly, not treated as proof of absence; the existing
strict codesign-plus-unsigned-message predicate is still required when no
positive signature evidence was observed.
Dangling signature/provision metadata symlinks are rejected.
There is no post-build stripping, re-signing, fallback acceptance or credential
operation.

## Bounded diagnostics

Failure output contains only fixed enums, the numeric codesign return code,
an unsigned-message-seen boolean, a signature class and bounded thin-Mach-O
load-command presence. No raw codesign output, paths, identities, entitlements
or arbitrary exception strings are exported. `codesign -d --verbose=4` remains
read-only with a 15-second timeout. Captured output over64KiB is rejected;
this is a post-capture/output policy, not a subprocess memory hard quota.

Mach-O metadata reads at most a32-byte header and1MiB of load commands through
no-follow descriptors; it never reads signature identities or executes the
binary. Unsupported, malformed and unavailable metadata are explicit. This
presence diagnostic is not cryptographic signature validation.

The outer runner projects only an exact bounded helper schema into
`command_end.unsigned_result`; malformed/duplicate/extra-field/raw output is
not exported. The old success sentinel remains unchanged. Private logs contain
the bounded helper result, not the raw codesign response.

## Preserved limits and remaining acceptance

Logical accounting, default8GiB/explicit40GiB experiment,4GiB free-disk floor,
all native/artifact/source gates, prior five-item retirement,45-minute workflow,
and process cleanup are unchanged. The inherited40GiB workflow remains an
explicit experiment needing separate launch authority; no13th run is authorized
by this change.

An unsigned arm64 simulator binary may not execute on Apple Silicon. This
pipeline deliberately compiles tests but never launches them. Future runtime
testing needs a separately reviewed signing/acceptance policy; ad-hoc signing
must never be silently relabeled as unsigned.

Local unit, negative, filesystem and real-child projection tests do not replace
selected-Xcode validation. Both full Python suites, static checks, publication
scan and independent review are required before proposing a new run.
