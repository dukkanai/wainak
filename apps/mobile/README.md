# Wainak mobile — phase 1 development slice

Arabic/RTL Flutter foundation for Android and iOS, with a local-review web target. Development only, not a store-ready application. App identifiers remain `invalid.example.wainak`; no production deployment, purchase or identity verification is configured.

## Explicit modes — no silent fallback

Without `--dart-define=WAINAK_DEV_MODE=true`, the entry point is inert.

- `WAINAK_REPOSITORY=fake` (default): offline in-memory synthetic journey, one reflection/card, local peer/activation simulation. No server or administrator receives its actions. Data disappears when the repository/process ends.
- `WAINAK_REPOSITORY=api`: `ConnectedWainakApp` → `JourneyRepository` → `HttpJourneyRepository` → `WainakApiClient` → `NativeApiTransport`. Requires explicit `WAINAK_API_BASE_URL` with loopback hostname `127.0.0.1`, `localhost` or `::1`. The app refuses other origins in this phase. Unsupported configurations and web API mode fail closed; they never substitute fake data.

Native development example (requires a suitable device/desktop target whose loopback reaches the separately authorized development backend):

```sh
flutter run --dart-define=WAINAK_DEV_MODE=true \
  --dart-define=WAINAK_REPOSITORY=api \
  --dart-define=WAINAK_API_BASE_URL=http://127.0.0.1:8089
```

No server is started by the app. No token is embedded or persisted. An Android emulator's localhost is not the host computer; this example does not configure networking or expose ports. Web has no API transport implementation.

## Connected development journey

Declarations (18+, Muslim, terms and privacy) → generated `@example.invalid` account → explicit development email-verification simulation → synthetic female/unmarried profile, sample country, preferred age range and opt-in discoverability → three adaptive backend reflection questions → actual eligible candidate projection → outgoing request or incoming accept/decline → independent initiator activation simulation → backend card catalogue.

Acceptance must come from the recipient's independent session. The sender cannot simulate their decision in API mode. The recipient waits/refreshes for initiator activation. Changing preferences or navigating back cannot retarget an existing relationship's report/block actions to a different candidate.

The current backend **does not implement exchange/storage of dialogue answers**. API mode therefore has no send button and labels selected card answers as local previews, never delivered messages. Photo/identity disclosure remains unavailable, regardless of acceptance or activation. No purchase occurs.

Report and block are independent and free, including a known target after block. API reports are metadata recorded in a development backend, not evidence uploads or notifications to a live moderation team. Deletion calls the backend, invalidates the session and clears declarations before new registration; it does not cancel store subscriptions or imply a marriage ended.

Do not enter personal information. The sample female/single profile and three countries are not the complete global product. Terms/privacy are development explanations, not approved legal documents. Backend authorization remains authoritative; UI guards never replace it.

## Transport and interruption handling

Tokens live only in the API client. Session epochs reject stale registration/401/delete responses. Busy screens suppress double actions; close disposes the client, while network uncertainty is shown without automatic retries or fabricated receipts. Relationship creation reuses its request idempotency key. Native requests use UTF-8 byte Content-Length, disallow redirects, cap responses at 64 KiB, and have a total 15-second deadline. Each request's client is closed on completion/timeout. HTTP 401 returns to unchecked declarations.

## Checks and accessibility

```sh
flutter pub get --offline
dart format --output=none --set-exit-if-changed lib test
flutter analyze --no-pub
flutter test --no-pub --concurrency=1
# Opt-in real native HTTP integration; launches and cleans a 127.0.0.1 ephemeral server:
WAINAK_BACKEND_ROOT=/absolute/authorized/backend-checkout \
  flutter test --no-pub --concurrency=1 test/native_backend_integration_test.dart
```

The native integration test is skipped unless explicitly supplied an authorized checkout or an authorized loopback fixture URL. It creates two synthetic sessions, exercises actual adaptive questions/request/recipient acceptance/activation/cards/report/block/delete, and terminates the temporary memory-only WSGI server in finally. It does not exercise the optional PostgreSQL adapter.

Noto Sans Arabic/OFL is bundled. Light/dark tokens use body 18, helpers 16 and targets at least 48 logical pixels. Text scale is not clamped; layouts scroll with Arabic framework localizations. Tests include 320-wide / 200% text and cancellation/repeated/late-response flows. See `VERIFICATION.md` for exact executed results and cold-build memory limitations; source test presence alone is not proof of a pass.

Not yet validated: Android APK/device (SDK/Java absent), iOS (Mac/Xcode absent), VoiceOver/TalkBack/NVDA, manual visual review or store acceptance. Not implemented: production authentication/age assurance, real email, billing/restoration, dialogue transport, media/disclosure, complete exclusivity/marriage UI, evidence retention/moderation, durable mobile sessions or production security operations. Independent exact-build security and accessibility review remain release blockers.


## Disposable persistence integration fixture

The optional reviewed backend harness may set WAINAK_TEST_BASE_URL and WAINAK_TEST_CONTROL_DIR instead of WAINAK_BACKEND_ROOT. The native test does not start/own that server. It checks the exact loopback origin, retains tokens only in memory and uses constant active/blocked marker files to coordinate two harness-owned server/DB restarts. The harness must create a fresh private directory and remove all temporary resources in finally. No administrative restart endpoint is added to the API. Results must be recorded separately from the already executed memory-backend journey.
