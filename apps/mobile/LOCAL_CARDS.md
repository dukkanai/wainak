# Phase 4 — local-only card preview, not a messaging channel

Base: local main `5f3433b23d8a29999c24943414ff1fdbcc40f46d`. Isolated development branch `dev/phase4-local-cards-20261024`; no main merge, deployment or new provider is included.

## Agreed boundary before implementation

This is a standalone default-off development mode, `WAINAK_DEV_MODE=true` and `WAINAK_REPOSITORY=local_cards`. Release mode is rejected. It is not opened from an authenticated relationship and receives no account, relationship, entitlement, API or persistence dependency. Existing fake/API/identity modes remain separate and unchanged. A local preview does not earn activation or simulate a partner's acceptance.

The sample contains four newly drafted Arabic-fusha cards and predefined responses, including deferral. These are illustrative editorial samples, not reviewed final product content or a compatibility/psychological assessment. They do not implement the planned library of thousands of cards or dialect variants in `docs/content.md`. The sample limits (1–12 cards, 2–5 responses per card, ar only) are validation bounds for this slice, not permanent product decisions. Unsupported locales fail closed; future dialect catalogues require explicit reviewed copy and versioning, not silent fallback or remote loading. Card IDs and response IDs have separate namespaces; card IDs are unique, and response IDs are globally unique across cards. Version format is checked; no remote version loader exists.

The static source catalogue is not conversation content. A user's selection is potentially sensitive and must stay in RAM in this slice. There is exactly one current card and response, no answer history. No text input, disguised free-text “other,” scores, clipboard/share/export, serialization, database, preferences, restoration, analytics, crash payload, HTTP, push, mailbox, outbox or server-history integration is added. There is no send API and no claim of end-to-end encryption, transmission, delivery, reading or partner typing. Every preview says **معاينة محلية — لم تُرسل**.

## State and lifecycle contract

`catalog.dart` and `controller.dart` are pure Dart with no Flutter/IO/network/storage dependency. All validation runs at runtime, not only through assertions. Final model classes and copied unmodifiable collections prevent later mutation. Invalid IDs/copy/limits fail with fixed exceptions without echoing values.

Stages: locked → catalogue → choosing → preview. Start requires explicit local-boundary acknowledgement. Every start/open/choose/preview/return operation receives a capability captured at render time, bound to the controller object, catalogue version, view revision and current card. Unknown/mismatched IDs are rejected atomically. Cross-controller or stale callbacks cannot select an answer, reopen a reset gate or restore an old view. State changes invalidate earlier capabilities. The controller is synchronous and has no clock, timer or async work.

Changing card removes the prior choice. Returning to the catalogue retains only the current local-boundary acknowledgement, never the answer. Clear/invalidate remove card, response and acknowledgement and return to locked. Dispose is terminal. Privacy clearing is not conditional on a valid token and is idempotent.

The host clears on system Back, cancellation, route cover/pop, explicit host visibility/scope changes, non-resumed lifecycle and disposal. Returning does not restore an old draft. A future embedding must pass accurate visibility/scope changes; disposal alone cannot detect every hidden IndexedStack tab. Session/safety invalidation enum values are unit-testable boundary hooks only, **not implemented wiring to real login/logout/block APIs**. This standalone mode has none of those APIs.

Clearing drops application references; Dart/OS memory may retain bytes. No secure-zeroization, OS-screenshot prevention, background snapshot, secure device storage or device screen-reader guarantee is claimed. Secure local persistence and any future encrypted transport require a separate reviewed design before content is written to files or sent.

## Accessibility

Reuse existing Noto Sans Arabic, RTL, high-contrast light/dark tokens, helper text ≥16 and targets ≥48. No fixed-height answer rows or response-dependent animation. Headings, selected controls and local-only notices have semantic labels; meaning is not color-only. Test narrow320 logical pixels at200% text, keyboard/focus interruption, Back, clear, repeated navigation, stale callbacks and host lifecycle. Real VoiceOver/TalkBack/device/release checks remain separate, not inferred from widget tests.

## Reproduction and evidence boundaries

As chatbot, use the existing project-owned Flutter/Dart SDK and caches. Persistent owner4GiB/compiler2560/8 settings stay unchanged; Mailcow stays stopped. Coordinate a single heavy job; no PostgreSQL fixture is required for this mode.

    dart --old_gen_heap_size=128 tool/check_local_cards.dart
    flutter analyze --no-pub
    flutter test --no-pub --concurrency=1 --reporter=expanded

All existing live tests remain opt-in; do not start their backend fixtures as part of local-only verification. Test diagnostics use fixed case labels and boolean predicates, not draft values. At initial authoring handoff, checks are **NOT RUN** until a result is explicitly recorded for an exact source snapshot. No production readiness follows from this sample.

Explicit entrypoint check (no API base URL, no backend fixture):

    flutter test --no-pub --concurrency=1 --dart-define=WAINAK_DEV_MODE=true --dart-define=WAINAK_REPOSITORY=local_cards test/local_cards_entrypoint_test.dart

At the first core handoff, developer15 checks and analyzer passed; independent22 controller checks passed on catalog4db0a07b/controller407c19b4. These are source-hash-scoped results, not widget or actual release-build evidence. The default suite skips the explicit-entrypoint check unless its compile flags are enabled.
