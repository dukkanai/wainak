# Mobile development verification — 2026-10-24

Status note: this document records its original phase and evidence. For the combined source, current modes and portable test setup, use [README.md](README.md) and [project status](../../docs/STATUS.md). Historical run results do not transfer to later source changes.

## Exact scope

Branch: dev/phase1-mobile-api-20261024. The handoff records the final commit.
Base: 67434304e5c8a7134f3397fee5e8db332dfea87c, preserved clean in mobile-phase1.
Native memory-backend checkout tested: 944e8b9a13275809c8fd0caa007056edf95c5533.
Only apps/mobile changed in this integration delta; main, prototype, live databases and production services were not part of the application change.

Flutter 3.47.8 stable / Dart 3.13.7, official framework 737ba8f885dc774b53b442759999a312c9461e4e. SDK/HOME/pub cache are isolated under /home/chatbot/wainak-dev/mobile-tools, outside Git. SDK came from official flutter/flutter stable and standard artifact bootstrap after the archive manifest returned404. pubspec.lock is committed; direct dependencies are Flutter SDK/localizations/test only. Android/iOS identifiers remain invalid.example.wainak; release signing is not configured.

## Initial connected snapshot results (863b4d5)

- dart format check: 19 Dart source/test files, zero changes at final check.
- flutter analyze --no-pub: **no issues**.
- **Cold test compilation and 38/38 tests passed**, exit0 at 05:37:45 UTC, job 2ea3421b-4724-40b1-b73d-529740cab360. build/test_cache was absent before invocation; the earlier failed/seeded cache was renamed and preserved, not reused. Official SDK and package cache remained installed, so this is a cold project test compile, not a fresh SDK install.
- Of the38: baseline29; seven connected-widget tests using an injected HTTP fixture; one actual native UTF-8 Content-Length loopback test; one HttpJourneyRepository/client → actual Python memory HTTP backend journey with two independent sessions.
- The native journey covered declarations/verification/profile/preferences, three adaptive questions, discovery/request, authenticated recipient acceptance, separate activation, card catalogue, report/block/report and deletion. Temporary WSGI server termination is awaited in finally; subsequent process inspection verified it absent.
- **Web debug build passed**, exit0 at05:39:21, 46.9seconds, job6e94ff43-c652-4b8a-89c4-984c8a502f31. Local compile artifact only, never served/uploaded/deployed. API mode intentionally fails closed on web.
- Native network tests drive the repository/client, **not widget taps against a live server**. Widget-to-repository/client behavior is tested with an injected fixture. These two evidence layers are not a device end-to-end claim.
- Connected regressions cover target pinning after back/preferences/refresh, recipient waiting rather than unauthorized activation, unchecked declarations after delete/401, double submission/disposal, candidate network failure with no fake fallback, cleared peer projection after block, and 320-wide/200% text scaling.
- Baseline coverage includes required declarations/minor rejection, lifecycle races, offline fake answers, cancel/block/report, sampled48-target semantics and static contrast pairs. This is not comprehensive accessibility/security certification.

## Resource limits and failed attempts

The owner connector originally had a1GiB cgroup. Bootstrap/earlier compiler failures are not passes. The integration cold frontend at448MiB and a384MiB attempt seeded with baseline ignored cache both exhausted their own heaps before assertions.

The owner explicitly authorized a **temporary runtime2GiB limit** at05:34:25; the backend worker verified actual2147483648 at05:36:21, with no service restart. Application developers did not alter OS/security/network settings. A single compiler ran at a time. During the successful cold run/build window the observed service cgroup peak was1745375232bytes (~1.63GiB); oom/oom_kill counters were0. This is a service-level observation, not an isolated compiler RSS measurement.

FLUTTER_TOOL_ARGS remains --old_gen_heap_size=384 --new_gen_semi_max_size=16 for flutter_tools. The isolated SDK AOT launcher used --old_gen_heap_size=768 --new_gen_semi_max_size=16 for the successful frontend, wrapping unchanged dartaotruntime.official (SHA2563599c987228070f342c80d29353f496c8efc72c620c75fc4d59e5671666b2f72). The frozen baseline had passed warm at384/8. Do not use768 after rollback to1GiB; coordinate the resource window and restore the bounded launcher before rollback. Reproduce with a suitably resourced standard SDK before release.

All project/Git/build writes now run as chatbot, following a separately approved ownership repair preserving bytes/modes. No ownership/security repair is an application feature.

## Reproduction

As chatbot, set:
    HOME=/home/chatbot/wainak-dev/mobile-tools/home
    PUB_CACHE=/home/chatbot/wainak-dev/mobile-tools/pub-cache
    PATH=/home/chatbot/wainak-dev/mobile-tools/flutter/bin:$PATH
    CI=true FLUTTER_SUPPRESS_ANALYTICS=true DART_SUPPRESS_ANALYTICS=true
    FLUTTER_TOOL_ARGS="--old_gen_heap_size=384 --new_gen_semi_max_size=16"

Within the agreed2GiB/one-compiler window, with frontend launcher768/16, from apps/mobile:
    flutter pub get --offline
    dart format --output=none --set-exit-if-changed lib test
    flutter analyze --no-pub
    WAINAK_BACKEND_ROOT=/home/chatbot/wainak-dev/backend-phase1 flutter test --no-pub --concurrency=1 --reporter=expanded
    flutter build web --debug --no-pub --no-web-resources-cdn --no-wasm-dry-run --dart-define=WAINAK_DEV_MODE=true

Without WAINAK_BACKEND_ROOT or WAINAK_TEST_BASE_URL the native backend test is explicitly skipped (37 runnable tests). The UTF-8 loopback test remains enabled.

The same native journey can be driven by an independently reviewed disposable PostgreSQL harness using WAINAK_TEST_BASE_URL=http://127.0.0.1:<ephemeral> and WAINAK_TEST_CONTROL_DIR=<private-tempdir>. The test writes only constant active.ready / blocked.ready markers and waits for corresponding .resumed files containing 'resumed'. The harness, not Dart, owns DB credentials/restart/WSGI cleanup. Same in-memory client sessions verify active state and blocked state across server/DB restart. The initial snapshot 863b4d5 subsequently passed the native PostgreSQL harness (14 PG regressions + one native journey), and independent real headless widget taps → native HTTP → PostgreSQL (14 PG regressions + one live widget journey) against backend59a79ea. Both tested two DB restarts and three WSGI processes with the same client sessions; cleanup was independently verified. These results belong to that initial snapshot, not automatically to later changes.

## Not verified / not implemented

No Android APK/device build (Java/SDK absent); no iOS/Xcode/Mac/signing/device run; no VoiceOver, TalkBack, NVDA or manual Flutter visual review. No release build/store submission/compliance approval/deployment.

No production auth/age or identity assurance/email, payments/restoration, media/disclosure, full exclusivity or marriage UI, evidence upload/retention/live moderation, durable mobile tokens, or production security operations. Dialogue answer exchange/storage is unavailable in the backend: connected UI has no send/delivered action and labels choices as local previews. API reports are development metadata, not notifications to real moderators. Account deletion is distinct from store subscription cancellation.

Independent exact-build security and platform accessibility review remain release blockers.


## Narrow keyboard/consent correction — final source rerun

Independent QA proved a P2 on863b4d5: with registration pending, real Tab/Space could change the adult declaration true→false even though only one request was sent. Backend authorization was not bypassed, but visible consent diverged from the in-flight request. The connected form now uses ExcludeFocus while busy in addition to AbsorbPointer. A regression includes a positive idle keyboard control, then verifies pending declarations remain checked. Declined text is now neutral about which party refused.

The corrected source was rerun with a fresh absent build/test_cache (previous successful cache preserved):
- **39/39 tests PASS**, including the new keyboard regression and actual memory HTTP journey.
- **20 Dart files formatted; analyzer no issues.**
- **Web debug build PASS**,43.8seconds.
- Combined command job5b3c3206-4498-46e2-a20f-e63854af04a4 exited0 at05:55:46 UTC.
- Memory-backend checkout for this rerun:59a79ea. Full backend commit is recorded in the backend handoff.
- Observed service-wide peak by05:55:31 was2032345088bytes (~1.89GiB), below the temporary2GiB cap; oom/oom_kill stayed0. This peak spans the verification window, not just one process.
- With the opt-in backend fixture omitted,38 tests run and the native backend journey is skipped.

The final corrected commit is frozen for independent native-PG and live-widget-PG reruns; their exact-pair results are recorded in the QA/backend handoff, not assumed here. No release/platform accessibility claims change.
