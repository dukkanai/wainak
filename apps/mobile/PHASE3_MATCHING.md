# Phase 3 — authenticated matching and introduction requests

Isolated mobile branch: dev/phase3-mobile-matching-20261024, based on local main b5f63ef0090be2513833a86e22c6c7032514c9f7. Backend contract: contracts/phase3-matching.md from backend3bc638f8884cc9d8da586d649f96c34a53476e1b. Development only; no main merge, publish or deployment is included in this slice.

## UI flow and identity boundaries

1. Existing synthetic signup, email proof, login and profile/assessment remain. A visible synthetic gender selector allows two deliberately declared test profiles; stored marital status, wives count, marriage goal and unedited preferences are preserved.
2. Separate Arabic profile / candidates / requests views. Candidates use only the server allowlist, never photos, verified-identity badges, star scores or invented compatibility. Empty or rejected discovery never silently inserts demo people.
3. Sending an introduction request requires an explicit confirmation tied to the selected actor/target. Incoming and outgoing requests are distinct. Only a recipient with the server's current accept hint receives an accept control; the server still rechecks all permissions.
4. Mutual acceptance stops at accepted_pending_activation. There is no activation, payment, exclusivity editor, freeform/media/card send, card-answer history or conversation-content storage in this identity UI. A legacy active relation can be displayed as an unavailable prior state, not as permission to open dialogue.
5. Decline, cancellation, ending, blocking and reporting remain separate. Redacted peer data stays redacted; the other opaque participant ID is derived only after checking the current actor is exactly one participant. No private rejection reason is inferred.
6. Reports carry category/target/optional relationship ID only. No evidence upload or message text. Feedback says the synthetic server recorded metadata, not that a live moderation team received it. Blocking never silently reports, and reporting never silently blocks.

## Asynchronous state and retry design

- Repository and candidates/relationship/safety contexts are actor- and auth-generation-bound. A dialog captures its originating repository/context; a newer login cannot retarget a confirmation.
- Reads have per-list sequence numbers and a mutation barrier. Mutation start drops stale peer/action projections; reads spanning a mutation or completing during one are rejected. Late accept/read results cannot repopulate a blocked peer. Ordinary mutations do not overlap; block can supersede them, while metadata reporting remains independent.
- A request or report intent retains its actor-scoped idempotency key after an uncertain response. Explicit retry uses the same target/payload/key across navigation; there is no automatic replay. A new target/report intent receives a new key. Confirming a block stops local request retries for that target.
- The retry UI uses a redacted pending target reference rather than resurrecting an old private profile. Successful server receipts—not button clicks—drive status feedback.
- Domain401 invalidates only the current session. Domain410 is a business rejection (including report_no_longer_available), never an allauth verification-flow timeout. Old-generation401/410 cannot clear a replacement account. Pending allauth flow expiry keeps its distinct handling.
- Lists are the complete small sandbox response: candidates cap20 per contract; relationships are not silently truncated or described as production pagination.

## Accessibility acceptance

Keep Arabic RTL and Noto Sans Arabic, existing high-contrast light/dark tokens, helper text≥16 and targets≥48. State is conveyed by text, not color alone. Busy areas exclude keyboard focus and pointer activation; cancellation has no server effect. Sections/status/error notices have headings/live regions. Test320 logical pixels at200% text, long labels, modal cancellation, interrupted navigation and meaningful button labels. Real VoiceOver/TalkBack/device checks remain separate gates.

## Evidence status at first light-check handoff

- Developer12 pure-Dart matching cases PASS12:58:15; analyzer clean. This includes three late-after-block variants, target/session pinning, idempotency, stale hint rejection and domain410 control.
- Independent QA reproduced the original draft's three stale-response failures before the mutation-barrier correction. Independent rerun of the same probes is still an acceptance blocker until explicitly recorded on the corrected source; developer regressions are not a substitute.
- Widget and actual phase3 HTTP/PG journeys are authored but NOT RUN at this handoff. Backend test results do not transfer to UI. No release/store/security acceptance is claimed.

## Reproduction

Use the already approved, isolated SDK/cache as chatbot. Persistent owner4GiB/compiler2560MiB remains; do not auto-lower it or start Mailcow. Coordinate one heavy test window. The source worktree is not main.

Lightweight (no PostgreSQL):

    dart --old_gen_heap_size=128 --enable-asserts tool/check_identity_matching.dart
    flutter analyze --no-pub

Default widget suite keeps all live fixtures opt-in:

    flutter test --no-pub --concurrency=1 --reporter=expanded

Actual two-session matching UI, only in an authorized isolated fixture window:

    WAINAK_IDENTITY_FIXTURE_SCRIPT=/home/chatbot/wainak-dev/backend-matching-phase3/backend/integration/serve_identity_fixture.py WAINAK_RUN_MATCHING_WIDGET=1 flutter test --no-pub --concurrency=1 --reporter=expanded test/identity_matching_live_widget_test.dart

The test starts the reviewed private fixture only inside its test body, after compilation. Two independent allauth sessions are created with synthetic example.invalid identities and RAM-only private-pipe verification. Profile/self-assessment setup is API-driven; matching request/retry/recipient acceptance/report/block are widget-driven. One wrapper intentionally drops a real HTTP request response after the server replies, then verifies an explicit same-key retry creates no duplicate. No fabricated recipient response, admin activation endpoint or conversation content is used. Test logs expose only the fixture script path/hash provenance; no passwords/codes/tokens or real mail. Normal cleanup/stream EOF/child exit are required.
