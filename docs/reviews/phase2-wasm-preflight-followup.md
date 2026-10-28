# Wasm preflight follow-up — exact mobile 482f7de

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Date: 2026-10-24 UTC. This addendum supersedes only the open historical Wasm
preflight failure in the mobile QA report; it does not rewrite the earlier run
or grant browser/runtime/authentication/release approval.

## Independently inspected evidence

- Mobile commit: `482f7de35b795c6c9eaf5a96d8a97c1631b0b6c5`.
- UI compiler job `f034f186-4a1f-4624-bcec-11b61ff70e1e`,
  11:39:20.598–11:40:07.655, **exit 0**, compiler duration 46.241 s.
- QA read the terminal job status and inspected its saved command/result/bootstrap.
  QA did **not** run another compiler.
- QA job `d015694e-5f87-4458-8206-f52777356c2f` at11:46:36 independently compared
  all **107 source files** both to the saved SHA-256 manifest and to committed
  `apps/mobile` blobs at482f7de: all bytes matched.
- Bootstrap imports `package:wainak_mobile/main.dart`. The recorded command is
  `dart compile wasm` with Flutter's platform/bootstrap, explicit synthetic
  identity defines and `--extra-compiler-option=--dry-run`.
- The compiler log is empty, the terminal exit is0, and the output executable
  `main.dart.wasm` is absent, as expected for this **preflight-only** check.

Artifacts are under
`/home/chatbot/wainak-dev/mobile-auth-wasm-482f7de/apps/mobile/.verification/wasm/`:

| Artifact | SHA-256 |
|---|---|
| result.json | `8cc75d9d26832c919f6ff7f412908361ef0fde4e4366c42092bf853110ef9498` |
| command.json | `22b3f2abe29a63f84f6c81b72713f27260265c4b544e8d01c5c784bb56adcb97` |
| source-manifest.json | `482149531e45d93256eea73c2d675aa05aa590c2826fcfd9c0d93c53490099ca` |
| compiler.log (0 bytes) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Resource and interpretation correction

The historical failure's **255 was an exit code**, not a255MiB compiler limit.
After explicit later user authorization, the coordinator set persistent owner4GiB
and compiler old-generation2560MiB/young8MiB. The new wrapper SHA is
`1d444483788a88fef0ab11c28e9f0b46c5f40bb65a027fa3afef635ade643978`.
These later settings supersede the earlier temporary rollback instruction: **do
not automatically restore1GiB/384MiB**. Mailcow must remain stopped. This reviewer
changed no service or compiler settings.

The recorded preflight host available memory was5495312KiB. The coordinator/UI
reported no concurrent heavy build and a clean post-run audit. The positive result
closes the old compiler-preflight OOM for this exact source/configuration; it does
not establish emitted Wasm functionality, browser startup, browser authentication,
Android/iOS builds, accessibility readers or production readiness. Native web
identity remains deliberately unsupported. No app source, main merge or deployment
was performed by this review.

A future integration commit requires its own source/provenance and regression
checks. This addendum does not silently certify an untested merged tree.
