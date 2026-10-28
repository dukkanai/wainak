# Fourth iOS attempt: bounded diagnostics across the native recipe

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Build `6addcee34a72334e32e4f476` on exact source
`493e7c027d66e66c6bac388313b2753d1e4e11f8` failed on 2026-10-25 at
09:46:57 UTC. The recorded native stage was `unmodified-upstream-apple-bind`,
native duration 176.357 seconds; the outer primary error was
`command_failed_native` / `wait_command`, with no reported cleanup errors.

Source order establishes that the host-policy gate returned before this stage.
It does not identify the failing Apple-stage command: graph inspection occurs
before gomobile bind. The existing console receipt was invalid because both
projection layers admitted only host-test command names, while native code
replaced the last receipt with null for every non-host command. No underlying
compiler/module/SDK error or successful Apple compilation is established.

This patch fixes that diagnostic gap, not a claimed binding root cause. Both
projection layers enumerate every current native command identity, including
module acquisition/graphs, SDK tools, tool builds, Apple binding and artifact
inspection. Unknown command names remain rejected. Only bounded exit/time,
fixed outcome/failure enums, and fixed diagnostic categories are projected.
Error-output matching emits category hints, never matched text, argv, paths,
environment, module identities or credentials; it does not prove root cause.
Unrecognized/oversized output remains UNKNOWN_TOOL_FAILURE. Host test output
continues through the existing source-bound test-name projection only.
Exact, bounded source-authored graph guard messages get GRAPH_MISMATCH; hostile
exception formatting is not invoked. Diagnostic errors cannot replace primary
build errors. No resource, offline dependency, integrity, crypto, toolchain,
signing, publication or acceptance guard changes.

Synthetic Python tests cover all command identities, the exact failed stage,
unknown/malformed values, bounds, secret-bearing fixtures, fixed classifier
families and hostile exception formatting. These are static/mocked checks,
not native compilation or runtime/security acceptance. Full repository gates
must pass on the final development commit before publication. No fifth cloud
run, main merge, billing, signing, deployment or native local build is performed
by this patch. The fourth attempt's missing stderr cannot be recovered by
changing source after the fact.
