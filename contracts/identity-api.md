# Identity API 0.3.0-sandbox — native and local deletion contract

This is a separate sandbox adapter, not a replacement for phase1.openapi.json.
Only the disposable test harness configures it. There is no persistent server,
real mailbox or production deployment. A separately tested native Flutter auth
adapter exists; the phase3 matching extension is described in `phase3-matching.md`. The additive local
web deletion surface is described in `../docs/phase2-deletion-web.md`.

## Transport and errors

Loopback HTTP is permitted **only for this owned test fixture**. A real deployment
would require HTTPS and separately approved infrastructure. Send JSON (at most
16,384 bytes); unknown authentication fields are rejected. Do not send cookies,
Origin (except the strictly CSRF-checked deletion web branch), query credentials,
Authorization/Bearer, real email addresses or user IDs
as authority. Native sessions use `X-Session-Token` and are never put in URLs.
Every response is `Cache-Control: no-store`. Fake messages exist only in Python
test memory, never through an HTTP mailbox endpoint.

The pinned allauth app API uses `{status, data?, meta?, errors?}`. Login-stage and
unauthenticated successful actions can return **401** intentionally; examine the
flow, not HTTP status alone. A newly issued/rotated token is in
`meta.session_token`; preserve the existing token if that member is absent.
Do not log response bodies or embed real values in test assertion messages.
The application's own domain/identity routes retain direct DTO bodies and use
`{error: {code, message}}` for rejection. Boundary errors use the latter shape
even on an allauth route; clients must handle both. Exceptions inside the request transaction are sanitized JSON500 and roll back
identity/domain changes. A fake-mail delivery failure in an on-commit callback
occurs after that commit: it cannot undo registration, but does not verify the
email or create authenticated access. Durable mail outbox/retry is deferred.

## Framework routes (prefix `/_allauth/app/v1/`)

| Method / suffix | JSON input | Success meaning |
|---|---|---|
| POST `auth/signup` | email, password, birth_date, is_muslim, terms_version, privacy_version | 401 pending verification; not authenticated |
| POST `auth/email/verify` | key (session-bound code from fake mailbox) | 200 authenticated; session rotates |
| POST `auth/email/verify/resend` | empty object | bounded resend; previous code replaced |
| POST `auth/login` | email, password | 200 authenticated, or401 pending email verification |
| POST `auth/password/request` | email | generic200 for known/unknown fixture addresses |
| POST `auth/password/reset` | key (framework link token), password | 401 after reset, without automatic login |
| POST `account/password/change` | current_password, new_password | 401 after change and global revocation |
| GET `auth/session` | none | current authentication flow/state |
| DELETE `auth/session` | empty object | 401 after logout |

Only these method/path pairs are exposed; there is no email-change, phone,
social-login, administrator, MFA or reset-by-code endpoint. A stale/absent pending
verification session can produce410; it must never be treated as authentication.
Verification codes and reset-link tokens are different purposes. Verification
does not establish legal identity, actual age or E2EE device trust.

Canonical fixture emails are trimmed, ASCII lower-case and match
`[a-z0-9][a-z0-9._-]{0,63}@example.invalid`, at most100 characters. No provider-specific
dot/plus normalization or account merging occurs. Passwords pass the framework's
minimum12/common/numeric validators and Argon2 hashing. Eligibility fields use
the phase1 policy version and adult/Muslim declarations, not document checks.

## Identity routes

| Route | Behavior |
|---|---|
| GET `/identity/v1/health` | public fixture metadata; real_email=false, production_ready=false |
| GET `/identity/v1/me` | id (auth UUID), domain_id (usr_*), email, email_verified=true, sandbox mode, email_is_identity_verification=false |
| POST `/identity/v1/reauthenticate` | `{password}`; recent-auth timestamp refreshed by server, never client |
| POST `/identity/v1/logout-all` | empty object; revokes authenticated and account-bound pending sessions/challenges |
| DELETE `/identity/v1/pending-account` | `{password, confirmation:"DELETE"}` plus a current owned unverified framework flow; never arbitrary email deletion |
| DELETE `/identity/v1/me` | `{confirmation:"DELETE"}`; requires auth within5minutes or password reauth |

Deletion returns the phase1 deletion result plus `identity_erased:true`,
`retained_synthetic_records`, `retention_policy` and explicit `limits`.
Auth/profile/consents/sessions are physically erased in the same transaction;
minimal relationship/account tombstones, a deletion receipt, other accounts'
idempotency receipt tombstones and expiring rate counters may remain. Captured
fake-mail snapshots/caller memory persist until fixture/process teardown, not
until this database delete call. This is **not** an approved production retention schedule,
backup erasure guarantee, subscription cancellation or conversation-key recovery.

## Phase1 domain bridge

The non-development `/v1/*` phase1 routes are retained, authenticated from the
framework user→domain link, not a caller-provided actor ID. `/v1/dev/*` and `/health`
are absent. There is **no entitlement/activation endpoint** in the identity API.
DTO field names that contain `dev` or simulation notices remain honest fixture
labels; a successful email proof comes from the framework flow, not a client flag.

- `DELETE /v1/me` uses the same recent-auth identity erasure as above.
- `POST /v1/reports` additionally requires `Idempotency-Key` matching
  `[A-Za-z0-9_-]{8,128}`. Scope is actor + operation + key + canonical payload.
  Same key/different payload gives409; replay of a purged report gives410 rather
  than recreating it. Report receipts contain metadata only; no D25 upload.
- Relationship request keys keep the phase1 8–64-character contract.
- Current persisted policy acceptance is checked before profile/preferences/
  assessment/candidate actions and positive matching relationship mutations. Strict
recipient decline, cancellation and termination remain safety actions without
requiring renewed consent; see the exact phase3 payload/path rules. Reading
relationship lists/details remains available for safety/termination; cards and
communication permissions still fail closed from current eligibility. Missing/stale consent gives403
  `consent_required`. Re-consent UI is not implemented. Safety, termination and
  deletion remain available. Permission checks still run on every current state.

## Local web deletion exception

GET `/account-deletion` renders the unpublished Arabic/English fixture page.
`X-Wainak-Deletion-Web:1` selects only login, email verify/resend, sign-out,
reauthenticate and the two deletion routes. Every mutation requires matching
Origin, the HttpOnly/SameSiteStrict `wainak_deletion_csrf` cookie and a valid
`X-CSRFToken`; other cookies and routes are refused. The initial masked token is
in `meta[name=csrf-token]`. Read refreshed `X-CSRFToken` response headers after
login/verification rotates the secret. This marker is not authentication.
Bearers remain only in page RAM, with pagehide/late-response invalidation; no
URL/localStorage/sessionStorage token persistence. This is not browser E2E,
public HTTPS hosting, password recovery UI, or store-policy acceptance.

## Development limits and deferred integration

Auth requests: per-endpoint IP30/min, email5/(5min for login; 1hour otherwise),
session10/min for non-GET. Reports10/hour/user; relationship requests10/min/user.
429 includes Retry-After. The database counter is atomic across independent
connections; forwarded client-IP headers are ignored. These are conservative
fixture limits, not a tuned production anti-abuse service or timing-enumeration
guarantee. No real mail, public port, push notification or E2EE implementation.

Verification timeout is the pinned framework's600-second comparison (valid
through the boundary, invalid after it); reset links likewise use the framework's
600-second timeout. Session idle30min/absolute24h and reauth5min fail at the exact
boundary. Restart tests preserve harness-parent keys in RAM, not production KMS.

The native identity client/UI was tested separately and integrated in phase2;
tokens remain in memory, not production mobile secure storage. The separate legacy
phase1 Bearer mode must not silently switch to this framework-session API. Phase3
adds auth-backed matching views and current-state direction/action hints; its
acceptance requires the exact phase3 backend/mobile test evidence.
