# Mobile foundation verification — 2026-10-24

## Scope and exact state

The handoff identifies the final Git commit; rerun commands below against that commit. This is a development foundation, not store/release acceptance. Only apps/mobile and docs/mobile-design-tokens.md are owned by this slice; main, the existing HTML prototype, database and live services were not modified.

- Flutter 3.47.8 stable, framework 737ba8f885dc774b53b442759999a312c9461e4e; Dart 3.13.7.
- Source: official https://github.com/flutter/flutter.git stable checkout. The official archive manifest returned HTTP 404, so installation used the official repository and its standard artifact bootstrap.
- SDK/HOME/package cache are isolated below /home/chatbot/wainak-dev/mobile-tools, outside Git.
- pubspec.lock is committed. Only Flutter SDK/localizations and Flutter test SDK are direct dependencies.
- Android/iOS/web scaffolds exist. Android release signing is deliberately unconfigured; identifiers remain invalid.example.wainak placeholders.

## Checks actually completed before final handoff rerun

- dart format: all authored Dart source/test files formatted.
- flutter analyze: no issues at the initial full-source pass; rerun on final commit required and reported in handoff.
- flutter test --concurrency=1: **29 passed**, including seven UI/theme checks, ten repository checks, eight contract-client checks and four deferred-response session races.
- flutter build web --debug --no-web-resources-cdn --no-wasm-dry-run --dart-define=WAINAK_DEV_MODE=true: **passed**. Local build artifact only, not served, uploaded or deployed.
- 320 logical pixel width / 200% text scaling covers onboarding, profile, reflection, candidate, activation, dialogue, report/block dialogs, account and delete dialog. This is widget-layout evidence, not device rendering or visual aesthetic acceptance.
- Automated labeled tap-target and Android 48-target guideline pass is sampled on the eligibility screen only, not a comprehensive accessibility certification.
- Static color-pair tests cover the documented core light/dark pairs, not every composed/disabled/focused color.

## Resource recovery, transparent limits

The owner connector's service cgroup is approximately 1 GiB although the host has more free RAM. Initial bootstrap and a test compiler attempt were OOM-killed; these attempts were not counted as passes. No service resource limit, security isolation, OS package or live process configuration was changed.

Bootstrap succeeded with FLUTTER_TOOL_ARGS="--old_gen_heap_size=384 --new_gen_semi_max_size=16". AOT frontend subprocesses do not inherit that setting. The isolated SDK's dartaotruntime launcher therefore adds "--old_gen_heap_size=384 --new_gen_semi_max_size=8" before invoking the unchanged official binary dartaotruntime.official. Official binary SHA-256: 3599c987228070f342c80d29353f496c8efc72c620c75fc4d59e5671666b2f72. A 256 MiB attempt exhausted its own heap and was discarded; the 384 MiB run passed. This wrapper lowers memory demand; it does not change compiler source or disable tests/checks. Reproduce on an adequately resourced unmodified SDK as well before release.

One test-harness SemanticsHandle lifecycle failure was fixed by disposing in try/finally before test return. Independent preliminary review identified session-response races; client epochs/closed guards and four regression tests now reject late registration after close, stale 401, stale delete, and malformed registration account before installing a token.

## Reproduction on this isolated host

Set HOME=/home/chatbot/wainak-dev/mobile-tools/home,
PUB_CACHE=/home/chatbot/wainak-dev/mobile-tools/pub-cache,
PATH=/home/chatbot/wainak-dev/mobile-tools/flutter/bin:$PATH,
CI=true, FLUTTER_SUPPRESS_ANALYTICS=true, DART_SUPPRESS_ANALYTICS=true,
FLUTTER_TOOL_ARGS="--old_gen_heap_size=384 --new_gen_semi_max_size=16".

From apps/mobile, run:
    flutter pub get --offline
    dart format --output=none --set-exit-if-changed lib test
    flutter analyze --no-pub
    flutter test --no-pub --concurrency=1 --reporter=expanded
    flutter build web --debug --no-pub --no-web-resources-cdn --no-wasm-dry-run --dart-define=WAINAK_DEV_MODE=true

Do not run heavy compiler jobs concurrently in the constrained connector service.

## Explicitly NOT verified / NOT implemented

- No Android APK/device build: Java/Android SDK absent.
- No iOS build/signing/device tests: Linux host, no Mac/Xcode.
- No VoiceOver, TalkBack, NVDA or manual screenshot review of this Flutter build.
- No release-mode build, store submission, store compliance approval or deployment.
- No live UI-to-backend integration: screens use DevJourneyRepository. WainakApiClient/native transport are independent preparation with injected transport tests only; no HTTP integration success is claimed.
- UI currently has one synthetic female unmarried profile, sample country input, stated starting preference, one reflection question and one dialogue card. It is not the complete preferences/adaptive assessment/global product.
- No real identity/age assurance, authentication/email, encrypted messaging, payments/restoration, media, exclusivity workflow, marriage spaces, evidence upload or live report operations.
- Session data and reports are in memory only. A report confirmation explicitly states that no administrator received it.
- Full independent security review and full platform accessibility review remain release blockers.
