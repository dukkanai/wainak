# Identity partial-save remediation — stage 2

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

## Scope and status

This isolated branch is based on
`4b0bfafeebaceb7a892e03d39a56533c9eb7e0dc`. It changes the identity profile-save
coordinator and UI feedback plus synthetic test fixtures and regressions. It does
not change backend endpoints, authentication policy, the legacy connected-app
flow, dependency locks, production services or the other remediation branches.

**Local pure-Dart, analysis and real Flutter fixture-widget checks passed.
Independent review accepted this bounded UI-fixture fix.** This is not a
cross-endpoint transaction, a live-backend acceptance test, an iOS/device test,
or evidence that the whole application is ready for release.

## Behavior

The original UI issued profile PUT, preferences PUT and an assessment GET as a
single UI action. A later failure could hide that an earlier write had succeeded.

The coordinator now tracks acknowledgements separately. After an error, it may
read the current profile within the same session. A matching readback value is
reported as an observation, not retroactively claimed as a write acknowledgement.
When readback fails, persistence remains unknown rather than asserted failed.

The UI preserves the draft, clears stale assessment questions for the attempt,
and distinguishes confirmed writes, unconfirmed outcomes and assessment-loading
failure. It neither automatically retries writes nor pretends to roll them back.
Only a later explicit user action starts another save attempt.

Submitted mutable lists are copied before asynchronous work. The entire flow is
bound to the original session generation, authenticated actor and active UI.
Disposal, logout or a replacement session prevents continuation or publication
of the old account's result. Existing client authentication rules are unchanged.

## Verification

- 14 new pure-Dart profile-save contract checks passed.
- Existing 21 identity-client and 12 matching checks also passed.
- Targeted Dart analysis reported no issues.
- The real Flutter runner executed **25 registered cases, zero skips**:
  **6 new widget cases**, **16 existing identity/matching widget regressions**,
  and **3 wrappers** which run the pure checks above.
  The 47 underlying pure assertions are not counted as additional widgets.
- New widget cases cover confirmed partial save and explicit retry, a write
  applied with its response lost, assessment failure after both acknowledgements,
  unreadable readback with draft preservation, repeated clicks/disposal, and
  a session change while partial-save readback is pending.
- Existing UI regressions cover signup/verification/profile/adaptive questions,
  login/logout/delete boundaries, account-generation changes, matching intent,
  uncertain retries, stale responses, and Arabic RTL at narrow width/large text.
- Source, dependency-lock and fixed compiler-wrapper hashes remained unchanged
  during the real Flutter run. No package installation was performed.
- Independent review checked the five source hashes, repeated 14+21 pure checks,
  then verified the real runner, provenance, resource receipt, log hash and all
  25 test registrations/results. No blocking defect was found within this scope.

The initial real Flutter run took 36.813 seconds. Its maximum sampled aggregate
tool/cache usage was 8,548,163,265 bytes below the existing 8,589,934,592-byte cap.
Sampled owner memory peaked at 2,359,021,568 bytes below the unchanged
4,294,967,296-byte limit. The compiler old-generation setting stayed 2,560 MiB.
These are periodic measurements, not continuous filesystem-quota guarantees.

Before running, the operator separately approved removal of exactly three old
generated Android kernel duplicates, totaling 148,977,624 bytes. Their bytes were
verified identical to the retained APK entry; the APK remained unchanged. No
other cleanup, artifact deletion, cap increase or service change was performed.

## Reproduction

With the existing locked SDK/cache available, from `apps/mobile`:

```sh
dart --packages=.dart_tool/package_config.json tool/check_identity_profile_save.dart
dart --packages=.dart_tool/package_config.json tool/check_identity_client.dart
dart --packages=.dart_tool/package_config.json tool/check_identity_matching.dart
flutter test --no-pub --concurrency=1 --reporter=expanded \
  test/identity_profile_save_widget_test.dart \
  test/identity_widget_test.dart \
  test/identity_matching_widget_test.dart
```

Use the host's approved resource-monitoring wrapper for actual execution. The
commands are documentation, not authority to install tools or raise limits.
The mobile tests were executed locally; this change does not add automatic
cloud workflow wiring. The opt-in live-backend widget files were not included
or counted as skipped tests.

## Limits and remaining gates

The two writes remain independent backend operations. Matching values from a
later read do not prove which request persisted them. No live Django/PostgreSQL
fixture suite, native cryptographic acceptance, macOS build, XCTest or physical
device test was run in this stage.

The public build-harness push/eighth cloud-build request is separate and still
requires its specific approval. This local commit does not authorize publication,
integration, merge, signing, payment or deployment. The legacy analogous save
flow and broader production feature gaps are outside this patch.
