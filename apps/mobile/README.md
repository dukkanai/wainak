# Wainak mobile — phase 1 development slice

Arabic/RTL Flutter foundation for Android and iOS, plus a **local-review web target**. This is not a store-ready app. Native application identifiers are deliberately `invalid.example.wainak` placeholders, not a confirmed publisher identity. No deployment or distribution is authorized by this directory.

## Explicit development gate

Without `--dart-define=WAINAK_DEV_MODE=true`, the entry point is inert and explains that real services are not connected. The flag enables a clearly labelled, memory-only synthetic journey. There is **no production authentication, connected UI networking, real purchase, image/identity reveal, persistence, analytics, notification service or live moderation** in this slice. A new repository/process starts empty; browser refresh and app restart discard its data.

Do not enter personal information. The persona is synthetic. Ages 17/18/29/45 permit eligibility boundary review, not production age verification. The profile is female, unmarried, and limited to a small sample of countries; it is not the complete profile/preference model or global launch scope.

## Run and check

Use the Flutter stable SDK recorded in the verification report. From `apps/mobile`:

```sh
flutter pub get
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test --concurrency=1
flutter run --dart-define=WAINAK_DEV_MODE=true
# Compile only, not deploy:
flutter build web --no-web-resources-cdn --dart-define=WAINAK_DEV_MODE=true
```

An installed Android SDK is required for Android device/build validation. iOS build, signing and VoiceOver testing require a Mac/Xcode and a suitable device. Linux widget tests do not replace those checks. NVDA web review is also independent of widget semantics assertions.

## Repository seam and states

`JourneyRepository` in `lib/src/repository.dart` isolates the UI from `DevJourneyRepository`. The mock must **never** become a trusted authorization source. Backend authorization, idempotency, age checks and privacy projection remain server responsibilities.

Development flow: eligibility declarations → sample profile → one self-reflection question (no psychological score) → synthetic candidate → `requested` → `acceptedPendingActivation` → separate simulated activation → `activeCards`.

Decline/cancellation do not open a conversation. Selection is separate from sending. Going online does not automatically claim delivery. Blocking disables further sends and deletes pending outbound answers. Reporting is separate and available before activation and after block. It records a local counter only. D25 evidence preview, explicit consent, upload, retention, moderation and appeal workflows are **not implemented**; no chat evidence is attached.

Account deletion clears this mock session, not server data or store subscriptions. Terms/privacy shown here are a development explanation, not final legal documents.

## UI guarantees to verify, not infer

Noto Sans Arabic is bundled with its OFL license from the existing prototype. Theme tokens use 18 logical pixel body text, 16 helper text, minimum 48 interaction targets and distinct light/dark colors. Text scaling is not clamped. Layout is scrollable, with directional alignment and framework Arabic localizations. The tests cover a 320-wide view at 200% scaling, errors, repeated navigation, offline delivery, cancellation, block/report and deletion. No test result should be claimed until it is recorded against the actual commit.

Still required before release: real API integration and concurrency tests, approved policies and age assurance, store-specific billing/restore flows, account deletion web resource, production report operations, platform screen-reader trials, keyboard focus review, full contrast-state review, and independent security review of the exact integrated build.

## API contract preparation (not UI integration)

`lib/src/api/client.dart` and `transport_io.dart` provide an explicit native-development HTTP client for the backend phase-one contract. They are not instantiated by the app entry point and do not replace the fake screen repository. The client keeps tokens in memory, sends idempotency keys for relationship creation, clears sessions on HTTP 401, does not follow redirects or automatically retry, and rejects unsupported media/identity permissions. Its injected-transport tests are not a live backend integration test. Web has no transport implementation. Connect the UI only after replacing synchronous mock actions with loading/error/stale-state handling and validating real contract scenarios.
