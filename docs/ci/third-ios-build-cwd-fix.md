# Third iOS CI attempt: preserve the source-relative ABI test

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

## Observed failure

Codemagic build `6adda3ad4a72334e32e4ec63`, commit
`926cda27d30a8fa5eb717e2262db3fb4918ca088`, failed on 2026-10-25 at
06:42:16 UTC. The bounded diagnostic identifies:

- stage `new-policy-host-tests`, command `archivebridge-tests`;
- exit 1 after 6.141 seconds, `NONZERO_EXIT`, category `TEST_FAILURE`;
- failed top-level test `TestExportedABITypesAreNarrow`;
- native step 154.462 seconds; outer cleanup errors empty.

The exact cloud assertion text is intentionally not published. The test name is
established; it does **not** by itself prove unsupported exported types or a
cryptographic failure.

## Reproduced source-path mismatch

The unchanged published test source (SHA-256
`c58856dcf372791b03553924111ae9c403afb0501ceacf3bc230a6ffafdc52a1`)
first parses `bridge.go` relative to its process working directory, before its
AST type/function-count assertions. The runner copied source to
`host-tests/archivebridge/module/bridge.go` but ran the binary from its parent,
`host-tests/archivebridge`. That relative read cannot find the file.

A temporary-directory Python reproduction exercised the actual frozen runner's
orchestration with mocked native commands and confirmed `FileNotFoundError` for
that relative read while the module copy existed. No Go compiler or test binary
was run by this reproduction. This establishes the harness/source-layout defect;
it is not a replay of the full cloud execution.

## Minimal correction and unchanged boundaries

Only the test2json child's working directory changes from the owned test root to
its existing `module` subdirectory. HOME and TMPDIR remain the owned parent's
`home` and `tmp`, the 512 MiB canary scan still covers the **whole parent**, and CLI
children retain their explicitly validated parent cwd. Compiler caches stay
separate with the same integrity checks. No paths outside the owned sandbox are
introduced.

The regression exercises both module orchestration paths and requires every
copied public `.go` source to resolve byte-for-byte relative to the runtime cwd.
It also verifies that HOME/TMPDIR and the scan root remain at their original
parent locations. Reverting only the cwd correction makes this regression fail.

The ABI test and its seven-function/narrow-type assertions are byte-identical.
Core crypto, facade, module graph, tool pins, signing policy, resource limits,
timeouts and workflow triggers are unchanged. No test is skipped or relaxed.

## Evidence boundaries

Local Python static/mocked tests and independent review validate this narrow
source change. The final development commit is checked with 152/152 static/mocked
tests (84 CI/iOS and 68 native), source-provenance gates and publication scanning
before push. These checks do not execute Go or Apple tools. The exact final commit is gated by the full repository's static
suites, publication scan and source-hash checks before development-only push.
No fourth cloud run, Apple compiler execution, device/runtime test, signing,
billing, main change or deployment is authorized by this correction. Existing
security advisory and runtime-acceptance gaps remain.
