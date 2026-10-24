# Phase-one contract — development only

Version `0.1.0-dev`, authored 2026-10-24. Primary machine-readable contract:
[`phase1.openapi.json`](phase1.openapi.json), OpenAPI 3.1; regenerate with
`python3 contracts/build_contract.py`, verify with `--check`.

This is a shared Flutter/backend boundary, **not a production service**. The mobile
fake repository may implement these DTOs without a network connection. Use only
synthetic fixtures; show «نموذج تجريبي ببيانات مصطنعة». No seed accounts are created
automatically. A client never supplies its acting user ID: it is derived from the
ephemeral bearer session. Fake email verification is explicitly `dev_email_verified`,
never `identity_verified`.

## Common conventions

- JSON `snake_case`; opaque `usr_…`, `rel_…`, `rpt_…` identifiers.
- JSON errors: `{"error":{"code":"relationship_unavailable","message":"…"}}`.
  Map stable codes to accessible Arabic copy; do not display raw internal details.
- All mutations use `application/json`, even `{}` for cancellation. Unknown fields,
  duplicate JSON keys, non-finite numbers, unsupported query filters, and bodies
  over 16 KiB are rejected. Use HTTPS in any eventual real transport; this prototype
  is loopback-only and never intended for real devices over the public network.
- 401 = missing/revoked session; 403 = actor not allowed; 404 = unavailable resource
  (also used for someone else's relation or hidden candidate); 409 = stale/forbidden
  transition or idempotency conflict; 400/413/415 = input issue. No automatic retry
  should turn a 409 into a new relationship or consent.
- Request creation requires `Idempotency-Key: [A-Za-z0-9_-]{8,64}`. Scope is actor
  plus operation. Same key/different candidate fails; replay returns **current**
  permissions and state, never a stale pre-block activation result.
- No numerical compatibility/beauty/health score. New ratings display
  `{"state":"insufficient_data"}`. Matching only applies reciprocal age, declared
  marital-status and country preferences. Optional medical data and health filters
  are deliberately not accepted in this phase; absence must never mean healthy.

## Onboarding and reflection

`POST /v1/dev/accounts`: synthetic `email`, `birth_date` (calendar date),
`is_muslim: true`, `terms_version` and `privacy_version` both `dev-2026-10-24`.
Returns an ephemeral `access_token` once; do not log it. This is NOT delivery of a
real verification email. `POST /v1/dev/verify-email {simulate_verified:true}` is an
explicit simulation. Exact age 18 is required by the server; neither this declaration
nor email simulation is real age/identity assurance or store-policy compliance.

`PUT /v1/me/profile` replaces all fields: `gender` (`male|female`), `country`
(two uppercase ASCII letters; catalog validation deferred), `marital_status`
(`single|married|divorced|widowed`), `declared_wives` (0–4; 1–4 only for married men),
`marriage_goal` (`build_family|companionship`), `discoverable` (explicit boolean).
Public aliases are generated stable labels, not real names.

`PUT /v1/me/preferences`: `min_age`, `max_age`, `countries` (empty = any),
`marital_statuses` (nonempty list). Both people's hard preferences must pass before
discovery or a new request. Married women and men declaring four wives cannot search,
independently of app link count. Profile/consent/verification are required first.

`GET /v1/me/assessment`, `POST /v1/me/assessment/answers {question_id,option_id}`:
three illustrative multiple-choice questions with one adaptive branch. Initial
`family_plan=children` leads to `parenting`; other choices lead to `life_priorities`;
then `communication`. Changing the first answer clears downstream answers.
Only the current or already answered question can be submitted. The answers are
private matching-account data, **not** dialogue answers. Assessment completion does
not force discovery, purchase, diagnosis, or a claim of validated compatibility.

## Candidate and relationship DTOs

Candidate allowlist: `id`, `alias`, `age`, `country`, `marital_status`,
`marriage_goal`, `rating`, `synthetic:true`. No email, birth date, wife count,
assessment answers, contact details, health information or photo is sent.

Relationship fields: `id`, `initiator_id`, `recipient_id`, `status`, `peer`
(allowed Candidate or null), `exclusive_requested_by` (user ID or null),
`permissions`, `activation_mode:development_simulation_only`.

State transitions:

```text
requested --recipient accept--> accepted_pending_activation
requested --recipient decline--> declined
requested --initiator cancel--> cancelled
accepted_pending_activation --explicit DEV entitlement simulation--> active_cards
active_cards --proposal + other participant accepts--> exclusive_cards
other active relationship during exclusivity --> frozen (effective state)
accepted/active/exclusive --either participant ends--> ended
any known pair --either participant blocks--> blocked
account deletion --> ended + peer private projection removed
```

Two accepted exclusivity proposals competing for one account have only one winner
inside the single-process development store. Ending/blocking the exclusive relation
releases the exclusivity lock but does not reopen any ended relation. New requests
cannot bypass a prior declined/cancelled/ended pair; authorized reopening and the
limited termination inquiry are deferred, not silently replaced.

`permissions` contains `can_send_cards`, `can_send_text`, `can_send_media`,
`can_disclose_identity`. **Only cards can become true in phase one.** Mutual acceptance,
simulated payment and exclusivity never grant photo, identity, engagement, marriage,
free-text or media consent. A frozen or blocked state always has card permission false.
Permissions are authorization examples, not proof of an implemented message channel.

`GET /v1/relationships/{id}/cards` returns two free sample library questions, never
participant answers. No send-message, photo upload, disclosure, engagement/marriage,
real billing or cryptography endpoint exists; these fail closed.

## Safety and deletion

`POST /v1/blocks {target_id}` works before payment, disables both directions, and
does not alter a marital declaration. After either party blocks a known candidate,
both can still report without regaining profile access or communication permission.
The target cannot silence a safety report by blocking first. No unblock/reopen action
is provided in this slice.

`POST /v1/reports {target_id,category,relationship_id?}` accepts categories
`harassment|threat|impersonation|child_safety|other_safety`. It stores only metadata
in memory and returns `recorded_development_only`. There is no live moderation team,
no public penalty and no evidence upload. D25 conversation attachment remains
approved product scope, deferred until explicit preview/consent, isolated evidence
storage, reviewer authorization and retention/deletion are implemented. The API
rejects free text, screenshots, conversation bodies and unknown evidence fields.

`DELETE /v1/me {confirmation:"DELETE"}` erases this synthetic account's private
in-memory data/reports and invalidates its session immediately. Other participants
keep a minimal ended relationship with a null peer. This is not production deletion,
legal retention policy, store-subscription cancellation, or a statement that a real
marriage ended. No partner approval or payment is required.
