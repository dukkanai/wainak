# One cloud logical-space experiment

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Base: `1377a9a142abc1532199f76831e568c7a425d9b8`.
This branch prepares a specifically approved **40 GiB logical workspace limit**
for one separately authorized, manually launched cloud experiment. It does not
itself authorize publication or a cloud launch.

## Selection and unchanged protections

- Default `ci/ios/build.py --build-unsigned` and the original
  `ios-unsigned-archive` workflow retain **8 × 1024³ bytes**.
- Only the build-only flag `--logical-workspace-40gib-experiment` selects
  **40 × 1024³ = 42,949,672,960 bytes**. There is no arbitrary limit or environment
  override. `--check`, unknown/abbreviated flags, and numeric flag values cannot
  select the experiment.
- New manual workflow `ios-unsigned-40gib-experiment` passes that flag explicitly.
  Both workflows retain Mac mini M2, pinned Xcode/Flutter, all source and Python
  test gates, and a 45-minute maximum; neither has triggers, publication,
  signing, secret groups, or artifact export.
- Every resource receipt identifies the selected limit/policy. A fresh guard
  precedes any tool command. The original five-root logical accounting,
  **4 GiB free-disk floor**, process cleanup, deadlines, source/ABI/artifact
  checks, and unsigned device/simulator compile requirements remain unchanged.
- The native builder's own bounds, the owner's local **4 GiB memory** limit,
  compiler settings, and existing local **8 GiB aggregate** limit are unchanged.
- Inherited stage5 retirement remains exactly its existing five future-run
  temporary entries after verified native success. No additional deletion,
  cache sharing, cache relocation, mapping-size override, or accounting
  exclusion is introduced.

## Evidence and limits

Eleventh run `6adf4a734a72334e32e554c3` failed at a measured total of
27,459,310,362 logical bytes. Its bounded metadata identified three single-link
files under the device compilation-cache directory: 16 GiB, 8 GiB and 1 GiB
logical, each reporting zero allocated bytes at that sample. The three
compiler-cache settings were reported NO, yet cache initialization still
created those files. This is not evidence of equivalent physical consumption
or memory usage.

The new bound permits that observed sample, not a promise that the full app
will fit. A second live 25 GiB simulator cache, other growth, the unchanged free
floor, or any existing acceptance gate can still stop the run. All data stays
counted. The process guard samples; it is not an OS hard quota.

The workflow can technically be selected again, like any manual workflow;
one-experiment authorization is an operator constraint, not a fabricated
single-use token or automatic permission grant. No automatic retry is added.
Another run or a larger limit needs its own authority.

## Local verification

`ci/tests/test_logical_budget_experiment.py` covers fixed/default selection,
invalid CLI modes and values, unchanged cloud/host gates, exact 8/40 GiB and
one-byte-over boundaries, actual eleventh sample, a hypothetical second 25 GiB
cache, unchanged free floor, cancellation and I/O failures, isolated instances,
a tiny real sparse-file measurement, and both exact manual workflow contracts.
Large boundary values are synthetic numbers; no large file, compiler,
installation, cloud process, or existing cache deletion is used by these tests.

Run both complete Python suites and all static gates before publication.
Actual 40 GiB cloud behavior, app compilation and runtime acceptance remain
unverified until a separately approved run produces evidence.
