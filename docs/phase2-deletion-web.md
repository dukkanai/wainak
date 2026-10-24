# Additive deletion slice — sandbox only

Baseline `dee6ec30085e3b3e2a12ea25c912967f27f1dcd7` remains independently
testable. Baseline QA `c3e1b62063e0fcb1b3b809196682db205550fc0a` does not
automatically approve this addition. No main merge, public hosting, SMTP,
persistent keys, existing-database migration or Flutter build is involved.

## Owned pending registration deletion

`DELETE /identity/v1/pending-account` accepts exactly
`{password, confirmation:"DELETE"}` plus `X-Session-Token`.

The server requires a non-expired, encrypted framework session with a current
email-verification flow, an actual linked User, matching flow email, no
`account_already_exists` marker, and the current password. The address alone,
an invented user ID, a digest instead of a bearer, or a duplicate signup's fake
flow grants nothing. A user with **any verified email** cannot use this route:
the verified/recent-auth deletion flow is required instead. The pending route
shares the atomic IP/session limits and auth→domain transaction lock.

- 200: physical synthetic identity/private-data erasure and session revocation.
- 400: invalid fields/confirmation; 401: missing or non-owned pending flow.
- 403: wrong password; 410: expired pending challenge; 429: shared throttle.
- A verify/delete race has one successful transition, never account resurrection.

This does not establish ownership of an email address. It erases an unverified
registration owned through its password and current pending session. It does
not authorize arbitrary-email deletion or turn a password-reset link into a
deletion capability. Retained metadata/fake-mail limits are the same as the
verified deletion contract.

## Explicit orphan maintenance, not production retention

`wainak_identity.deletion.expire_orphaned_staged_accounts(*, dry_run=True,
after_id=None)` is a **private Python utility**, not an HTTP endpoint, command
accepting a live DSN, background worker or newly scheduled service.

The disposable fixture rule is: registration age **at least 24 hours**, no
verified email, and no currently valid **owned** session. Time comes from the
server, not a request parameter. Validity checks expire_date, 30-minute idle and
24-hour absolute limits; ownership is User FK plus decrypted auth-hash proof or
matching current pending user/email/issuance state. A fingerprint alone or fake
duplicate-signup flow cannot keep another account alive. Reading this state does
not call SessionStore.load and cannot extend activity.

Dry-run is the default and changes **no rows**, including expired sessions and
counters. Explicit `dry_run=False` erases eligible users and prunes expired state
inside the same auth/domain transaction. An injected failure rolls back all
halves. Only the already-owned disposable database is accepted.

Each invocation scans at most 100 candidates in UUID keyset order. Results are
counts plus `next_after_id`, an internal non-auth UUID cursor (no email, password
or bearer). Continue with that cursor; when it is null the current scan is done.
A later sweep starts at None to include candidates added concurrently before a
previous cursor. This is not a claim that one bounded call purges every orphan.

Result keys: `dry_run`, `scanned_candidates`, `eligible_orphaned_accounts`,
`purged_unverified_accounts`, `eligible_expired_sessions`,
`eligible_expired_rate_counters`, `next_after_id`, `policy`, and
`production_retention_approved:false`. The policy label is
`synthetic-orphan-24h-not-production-retention`. A real retention period/legal
basis remains an owner/policy decision; no production retention is inferred.

## Local deletion webpage and browser transport

GET `/account-deletion` renders a minimal Arabic/English page with labels,
fieldset, explicit confirmation, keyboard focus styles and live status text.
It uses the existing allauth login/verification flows, password reauth, and the
verified or pending deletion API. It is not published or accepted by any store.

Web requests explicitly select `X-Wainak-Deletion-Web:1`. This marker is **not
authorization**; it chooses a smaller allowlist with stronger browser checks:
login, verify/resend, sign-out, password reauth, and the two deletion endpoints.
Normal native requests still reject Origin/cookies. The web branch requires:

- Only the `wainak_deletion_csrf` cookie (HttpOnly, SameSite=Strict); no cookie
  authentication or sessionid cookie. Secure=false is confined to this local
  HTTP fixture; a public HTTPS deployment would require separately reviewed
  settings, and is not enabled here.
- A matching Origin and real Django CSRF validation for **every** mutation.
  A deliberately non-exempt sentinel prevents downstream allauth app views'
  csrf_exempt attribute from bypassing this boundary.
- Initial masked token in `meta[name=csrf-token]`, request `X-CSRFToken`, and a
  refreshed masked `X-CSRFToken` response header after authentication rotates
  the cookie secret. Tokens never appear in URLs or application browser storage.
- CSP nonce, connect-src self, frame-ancestors none, no-store, no-referrer,
  and no external assets, analytics, provider or CORS allowance.

The account bearer lives only in the page's JavaScript memory. Logout, deletion
and pagehide clear it. Epoch checks plus owned AbortControllers prevent late
fetch/JSON/reauth responses from restoring credentials or launching a new delete
against a subsequently signed-in account. Confirmation does not transfer across
logins. Browser/password-manager behavior is separate from application storage.

Aborting a fetch does **not** guarantee cancellation of an operation already
received by the server. Uncertain outcomes are not automatically retried; the
user must sign in again to check. pagehide clears client memory but does not
promise server-side logout; server sessions still have idle/absolute expiry.

## Evidence and limits

The addition has isolated server/CSRF/ownership/maintenance tests, a real
loopback HTTP cookie-jar login→reauth→delete test, and a Node test executing the
exact inline script against a **mock DOM/network**. These do not execute a real
browser, mobile app or screen reader. Accessibility and visual UX need real
device/browser review; no such acceptance is claimed.

Web password recovery is not implemented. Real mail, hosting, production
retention/backups, customer support and public store deletion URL requirements
remain unresolved. Final runtime and independent QA results must identify the
exact additive commit, separately from the preserved baseline.

### Author candidate observation

Run `c8e65e49-b439-43db-b398-cf579e4b2f3f` ended2026-10-24 08:44:40 UTC:
**60/60 passed** (14 unchanged PG +30 identity +16 addition cases), in46.460s
on PostgreSQL17.11/psycopg3.3.6. The runner verified container/volume/tempdir
removal. Four exact-script mock-DOM/network scenarios also passed locally on Node24.19.0
with template/test SHA-256 matching the server. Node was unavailable in the
server user PATH; no Node package was installed there and no server Node run
is claimed.
These observations are not a substitute for independent tests on the final
additive commit. Browser/screen-reader execution is still NOT RUN.
