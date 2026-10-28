# Stage6: command-scoped Xcode compilation-cache policy

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Base: 7fcf56b741248e24472bcac8ff0947bbabd3576b. This local candidate is not
authorization to publish or run an eleventh cloud attempt.

## Evidence and uncertainty

In tenth build6adf3bc94a72334e32e54fae, native compilation and all22 artifact
checks passed. Stage5 successfully retired only its five fresh transient entries
and verified retained evidence. It retired883,582,626 logical bytes; work
accounting dropped from1,213,571,903 to329,989,680 bytes. The app device compile
still failed the unchanged workspace_budget gate.

At that failure, work measured27,346,737,882 logical bytes and aggregate usage
27,457,560,781. Free volume space remained134,740,000,768 bytes. The work increase
since settings was25GiB plus45,025,370 bytes, while free volume space decreased
47,951,872 bytes. Free-volume change is not process-specific allocation evidence.

LLVM's historical on-disk CAS implementation reserved8GiB index,16GiB data and
1GiB key/value extents; its mapped arenas can be sparse while live. That supports
a strong mechanism hypothesis, not proof of the actual offending Mac files.
The workflow did not publish those private workspace files. Current upstream
defaults differ and must not be asserted as the selected Xcode's implementation.

Primary sources:
- LLVM original implementation:
  https://lists.llvm.org/pipermail/llvm-commits/Week-of-Mon-20241007/1474177.html
- LLVM mapped sparse arena:
  https://llvm.org/docs/doxygen/MappedFileRegionArena_8cpp_source.html
- Apple compilation-cache setting:
  https://developer.apple.com/documentation/xcode/build-settings-reference
- Apple documents command-line build settings taking precedence:
  https://developer.apple.com/documentation/xcode/configuring-the-build-settings-of-a-target/
- SwiftBuild Clang cache gate and conditional CAS options:
  https://raw.githubusercontent.com/swiftlang/swift-build/main/Sources/SWBCore/SpecImplementations/Tools/CCompiler.swift
- SwiftBuild Swift cache gate and conditional CAS options:
  https://raw.githubusercontent.com/swiftlang/swift-build/main/Sources/SWBCore/SpecImplementations/Tools/SwiftCompiler.swift

These sources establish a supported control and plausible mechanism; they do
not identify the tenth build's actual cache files or prove this candidate works
on the pinned Apple toolchain.

## Narrow policy change

The same xcodebuild argument builder supplies exactly these explicit settings
to both settings inspection and its corresponding compile command:

- COMPILATION_CACHE_ENABLE_CACHING=NO
- CLANG_ENABLE_COMPILE_CACHE=NO
- SWIFT_ENABLE_COMPILE_CACHE=NO

Device action remains build; simulator action remains build-for-testing. The
settings query specifies the matching action, so test targets cannot be silently
omitted from the intended simulator acceptance. Every returned target must have
all three effective values exactly NO. Runner is required; the simulator also
requires RunnerTests. Missing, malformed, duplicate or enabled values fail
closed before compilation. Fixed-label pass/failure receipts never print target
names or arbitrary setting values.

This changes only compilation-result caching for these commands. No global
defaults, module/explicit-module settings, integrated-driver settings, signing,
native checks, test selection, diagnostics policy, memory limit or disk limit is
relaxed. A reported setting is not independent proof that all other kinds of
tool caches are absent. No runtime or production acceptance is claimed.

## Additional bounded failure metadata

Only after the same8GiB logical-byte test has failed, perform a separate,
best-effort metadata scan of the run workspace. Report at most8 regular-file
rows with fixed role/extension categories, logical size, allocated blocks*512,
hard-link count and whether allocation is below logical size. No filenames,
relative paths, file contents, argv or environment values are emitted.

Traversal does not follow symlinks or open regular-file contents. It has bounded
depth64,100,000 entries and a cooperative1second deadline. Incomplete scans,
churn or I/O errors are labeled; the result is not an atomic top-file inventory.
Allocated bytes are diagnostic only: logical accounting and the8GiB/4GiB-free
gates remain byte-identical. Diagnostic errors cannot replace the primary
workspace-budget failure. Allocation below logical size alone is not proof of
sparse holes, and hard links are not deduplicated out of the existing policy.

## Local verification

Job10b00c27-6a8a-48e4-83c0-1d2aa3c7a1b0:
-233 outer CI tests plus68 native tests PASS, zero skips.
-33 new tests cover all three per-command controls, device/simulator-test action
  parity, missing/enabled/malformed target settings, redaction, tiny real sparse
  and hard-linked files, symlink/FIFO exclusion, bounds, descriptor closure and
  primary-error preservation.
-Three static checks and git diff --check PASS.
-No Xcode/compiler invocation, cloud job, tool install or existing-cache deletion
  occurred in these new tests. Largest sparse fixture is1MiB, not25GiB.
-Shared tree_size implementation, strict symbol parser and EPERM cleanup file
  remain unchanged. The cleanup ambiguity from prior runs is not fixed here.

Independent review is tracked separately. Actual Mac cache behavior, application
compile success and resource fit remain unverified. Any future cloud run needs
explicit approval, including the inherited stage5 five-entry transient lifetime
policy; this candidate does not expand its retirement targets.
