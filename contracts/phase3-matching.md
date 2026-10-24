# Auth-backed matching extension 0.3.0-sandbox

This additive identity-adapter contract starts from integrated main `b5f63ef`.
It uses the existing `X-Session-Token` native transport and synthetic-only fake-mail
fixture. It does not change the phase1 Bearer API, public deployment, or payment.

## Existing account and matching routes

All routes authenticate the framework session and derive the acting domain account
on the server. Never send an actor ID as authority. Session expiry/global revocation
is 401; discard client account/relationship state as well as the token. Do not treat
the allauth pending-verification 401 flow as a domain-authenticated session.

- GET `/v1/me`: own profile, preferences, consent versions and eligibility only.
- PUT `/v1/me/profile`: replace gender, country, marital_status, declared_wives,
  marriage_goal, discoverable. Discovery is an explicit boolean, not assumed opt-in.
- PUT `/v1/me/preferences`: replace min_age, max_age, countries, marital_statuses.
- GET `/v1/me/assessment`; POST `/v1/me/assessment/answers` with question_id/option_id:
  these are private, restorable **matching assessment** answers, never dialogue.
- GET `/v1/candidates` and `/v1/candidates/{usr_id}`: reciprocal eligible projections;
  no email, date of birth, health, contact, assessment answers, photos or hidden reasons.
- GET `/v1/relationships`: own incoming and outgoing items together, no caller actor filter.
- POST `/v1/relationships` with `{candidate_id}` and Idempotency-Key of8–64 ASCII
  alphanumeric/underscore/hyphen characters:201, one pair/request per intent.
- GET `/v1/relationships/{rel_id}`; POST `.../respond` with decision accept/decline;
  POST `.../cancel` with `{}`; POST `.../end` with `{confirm:true}`.
- POST `/v1/blocks` with target_id; POST `/v1/reports` with target_id, category and
  optional relationship_id. Reports require actor-scoped Idempotency-Key8–128.

Input, response fields, assessment branching and error shapes otherwise remain as
specified in identity-api.md and the phase1 contract. Unknown fields are rejected.
No client-supplied purchased/subscribed/permission value has authority.
Candidate lists cap20 without a total; relationship lists currently return all
own records without pagination. This is a small synthetic sandbox limitation, not
a scalable bounded-list claim. Do not silently truncate safety access in the UI.

## Identity-only relationship projection additions

Every identity relationship response (list, detail, mutation and idempotent replay)
retains the existing fields and adds:

```json
{"direction":"incoming","available_actions":["accept","decline","block","report"]}
```

`incoming` means the current actor is the recipient; otherwise `outgoing`.
Actions appear in fixed order accept,decline,cancel,end,block,report, filtered as follows:

| Action | Current server condition |
|---|---|
| accept | requested, recipient, both participants currently discoverable/eligible |
| decline | requested, recipient; stale policy acceptance does not trap someone in a request |
| cancel | requested, initiator |
| end | stored accepted_pending_activation/active_cards/exclusive_cards, including effective frozen |
| block/report | known nondeleted peer under existing safety addressing rules, including after blocking/ending |

These are **UI hints, not grants**. Each mutation rereads membership, role, state,
block/deletion and eligibility inside the same auth/domain transaction. A stale
hint never overrides the result. No private reason explains a missing action.
Missing/stale consent denies positive matching actions with403 consent_required;
relationship reading and strictly validated safety actions stay available.
Other participants' stale policy consent already excludes them from candidates
and hides their relationship peer projection in the identity adapter.
Blocked/deleted peers remain null. Third-party relationship IDs give404.
Underage or unverified/inactive peers are also redacted, without a reason field.
The identity service snapshots active accounts with a matching verified allauth
EmailAddress under the request transaction; the older domain verification mirror
alone is insufficient. This snapshot is recreated per request, not cached across
requests. A verified email proves mailbox control only, never age or identity.
The small-sandbox snapshot queries all active verified domain IDs, not a scalable
production query design. Direct identity-service construction without this snapshot
fails closed for discovery/acceptance and peer projection.

Both initiator and recipient use their own verified sessions. A recipient accept
ends this slice at `accepted_pending_activation`, with all communication permissions
false. Existing activation_mode is a legacy synthetic label, not a purchase or an
activation capability. There is no activation/payment action in this contract.

Repeated request keys return current relationship state/actions, never a cached
pre-block snapshot. Different payload with the same key gives409. A new key cannot
reopen a declined/ended/cancelled pair. Response loss is handled by retrying the
same intent/key or refreshing, never by silently creating a new intent.

## Strict no-content boundary

D16/D17 prohibit automatically persisting conversation content, including selected
dialogue card IDs, answers, results or ciphertext queues, in DB, logs, analytics,
jobs, push or backups. No send/history/answer/outbox route is added. The static
publisher-authored card library is not a transcript. Matching-assessment answers
are a separately declared account-data purpose and must not be used to submit
partner dialogue. D25 evidence upload stays disabled.

Production activation remains locked pending verified store/provider entitlement.
No synthetic entitlement is added to HTTP. If a later transport experiment needs
activation, it must be an explicitly isolated Python-only fixture, not an app
payment button or production permission. Actual device outbox, authenticated E2EE,
live relay, recipient ACK, replay/block-before-delivery and key recovery are deferred.

## Client interruption requirements

Pin authenticated actor, target and intent throughout async operations; invalidate
late results after logout/revocation/account switch/navigation. Clear profile,
candidate, relationship and assessment state on account boundary changes. Reuse a
request/report key only for the identical actor/operation/payload. Show loading,
empty, unavailable, waiting, declined and rate-limited states distinctly without
exposing hidden eligibility details. Block/report never require payment or acceptance.

Native-loopback tests with fake mail are not physical-device, release, real-mail,
production-entitlement or messaging acceptance. No new main merge is authorized by
this development slice.
