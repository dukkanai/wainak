# Phase 2 identity sandbox — independent QA results

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

Date: 2026-10-24 UTC. Reviewer: independent QA agent.
**نتيجة محدودة: نجحت الاختبارات المذكورة أدناه على النسخة نفسها؛ ليست موافقة إنتاج أو متجر، ولا اكتمال نظام الحسابات.**

## Exact source and evidence

- Backend branch: `dev/phase2-auth-20261024`.
- Backend worktree: `/home/chatbot/wainak-dev/backend-auth-phase2`.
- Tested commit: **`dee6ec30085e3b3e2a12ea25c912967f27f1dcd7`**.
- HEAD was verified clean before both independent runs and after the final run.
- QA branch/worktree: `dev/phase2-auth-qa-20261024`,
  `/home/chatbot/wainak-dev/qa-auth-phase2`. Only QA files were changed here.
- Final QA test SHA-256:
  `3dfdd62b71179bc3d0e48abbe8d44d2e5c0cfb04e3766b7f5099e0f1caa2134d`.
- QA runner SHA-256:
  `5cd93343b9baf2eed68ad634f1c5794d20ee8dd824e7a9968e142273d55f83d3`.
- The QA commit containing this report also contains the exact tested QA files.
  No developer worktree source was modified by QA.

### Terminal results

| Check | Exact evidence | Result |
|---|---|---|
| Disposable integration + independent adversarial suite | Job `1f5383cf-dcaf-4a58-b015-248c7a79ad81`, 08:17:19.689–08:18:18.148 UTC, exit0 | **66/66 PASS**, unittest52.803s:14 PostgreSQL +30 developer identity +22 independently authored QA cases |
| Backend unit/control regression | Same clean backend HEAD, 08:18 UTC | **57/57 PASS**,0.105s; documented-operation coverage is included, not an extra test count |
| Phase1 OpenAPI artifact | `python3 contracts/build_contract.py --check`, same HEAD | PASS; does not claim a machine-readable phase2 OpenAPI contract |
| Git whitespace | `git diff --check`, same HEAD | PASS |
| Dependency consistency | `pip check`, isolated identity venv,08:11 UTC | PASS |
| Installed-file integrity | SHA comparisons against installed RECORD entries of five named distributions | **5,017 hashed files PASS**; not an independent signed-wheel or vulnerability audit |
| Final resource cleanup | Independent check08:18 UTC, plus harness exact-resource checks | PASS; details below |

The first independent run, job `b1ca0e18-4784-4385-969b-cf64c525ed48`,
08:14:57.145–08:15:52.780 UTC, exited1: **63/64 PASS**.
The failure was a QA fixture error, not an authorization bypass:
the foreign-relationship test sent `{confirm:true}` to cancel, whose documented
input is `{}`. Input validation correctly returned400 before authorization.
QA corrected the payload, added per-route subtests, and added two new tests for
default session-table storage and concurrent report replay. The entire resulting
66-case suite was rerun successfully; the failed run is not relabeled PASS.

## Environment, isolation, and cleanup

Host `ostath` was reconfirmed08:06 UTC. Commands, Git and fixture processes ran
as `chatbot`. CPython3.14.4, PostgreSQL17.11 and psycopg3.3.6 were observed.
Installed packages checked: Django5.2.18, django-allauth65.20.1,
argon2-cffi25.1.0, cryptography50.0.2. Hashing used the actual configured framework
Argon2 cost, not a reduced test hasher.

The reviewed harness created a fresh randomly named disposable PostgreSQL
container/volume from its existing pinned image, `network=none`, no published
ports. Only that new DB received migrations and synthetic fixture data.
Temporary passwords, signing/Fernet/HMAC keys and bearer/reset/verification
values were fixture-only; no production credential or persistent key was created.
The DB password file was inside the owned temporary directory; identity keys
remained in parent Python memory. Nothing secret was put in test reports,
assertion operands, shell arguments or mailbox URLs exposed to a client.

The HTTP restart case used three fresh owned WSGI processes bound to
`127.0.0.1:0`, with proxies disabled, no access log, and stop/join followed by
terminate/kill of that exact owned process if necessary. It proved a session
remained valid across a DB/server restart, then deletion/revocation persisted
across another restart. Keys deliberately survived in the harness parent's RAM:
this is **not** production KMS, process-independent key recovery or disaster
recovery evidence. QA's additional deletion case also restarted the owned DB.

Before the initial independent run and after each independent run, QA checked:
- no containers or volumes bearing `com.wainak.disposable-postgres-test`;
- no chatbot-owned `/tmp/wainak-postgres-test-*` directories;
- after the final run, no `run_identity.py` or `run_auth_independent.py` processes.
The harness additionally verified removal of its exact container, volume and
temporary secret/socket directory even on the failed test run.
No real SMTP, public endpoint, existing DB, staging, deployment, push or merge
was used. No owner memory limit, Mailcow state, permissions or security setting
was changed by this QA milestone. No Flutter compiler ran.

## Reviewed design and contract

Relevant source: `backend/wainak_identity/{bootstrap,middleware,models,sessions,
repository,forms,adapters,signals,views,rate_limits}.py`, the initial migration,
`backend/integration/{run_identity,test_identity,run_postgres}.py`,
`backend/requirements-identity.lock`, `contracts/identity-api.md`, and
`docs/phase2-identity-architecture.md`.

- Native sandbox only: `X-Session-Token`; cookies/Origin/Bearer/query credentials
  rejected. Only listed app endpoints and synthetic normalized
  `@example.invalid` addresses are accepted. No public mailbox or admin route.
- Framework-generated bearer; SHA-256 lookup key in a custom64-character session
  model. Fernet encrypts a digest-bound envelope containing pending verification
  state. This is server-side storage encryption, **not E2EE** or protection
  against an administrator able to alter all DB metadata and application keys.
- Framework auth-hash checks and login rotation are retained. Sync/async session
  paths and model-manager shortcuts were inspected and tested; default
  `django_session` and `EmailConfirmation` tables stayed empty in the storage
  probe. Additional allauth user-session tracking is not installed.
- Auth advisory lock precedes session loading. Django and domain share the same
  psycopg connection and outer transaction, with a fixed auth→domain lock order.
  Cursor-local JSONB decoding avoids modifying Django's global adapters.
- Verification codes are session/purpose-bound,5 attempts,3 resends. Codes and
  reset links use the pinned framework's600-second inclusive comparison;
  values after the boundary fail. Session idle1800s, absolute86400s, and
  recent-auth300s are distinct. Tests below explicitly distinguish tested edges.
- Password reset uses framework password-bound links, not the vendor's
  reset-by-code path that can indirectly verify email. Reset never automatically
  verifies an unverified account or signs the reset subject in. An unrelated
  authenticated actor is not logged out by somebody else's reset.
- Subject-bound pending and authenticated sessions are revoked after
  reset/change/logout-all. Actor identity for domain operations comes only from
  the current framework user, not JSON/header-supplied IDs.
- Report receipts are actor+operation+key+payload scoped. Exact concurrent replay
  creates one report; changed payload conflicts; replay after purge returns410,
  not resurrected content. This does **not** make every POST idempotent.
- Current-consent checks reject protected matching mutations and discovery.
  Relationship metadata may still be read for safety/termination; card
  permission is recalculated from current eligibility. Re-consent UI is absent.
- Global serialization and full domain snapshots are correctness-first sandbox
  choices, not scalable production transaction/query or abuse-control design.

## Findings and limits

### Resolved before/following the reviewed draft

No new open P0/P1 exploit was observed in the exercised final sandbox paths.
This is a bounded finding, not proof of absence of vulnerabilities.

Earlier review/testing identified and closed or accurately bounded:
- Session digest width/raw-key async/manager paths, encrypted pending state and
  row binding; independent tests passed on the final source.
- Shared auth/domain transaction seam; injected registration and deletion
  failures roll back both halves.
- Reset with a pending token must revoke that challenge; resetting B while A
  is authenticated must not flush A. Final independent cases passed.
- Stale consent must be checked after persistence; safety/report/delete remain
  available. Final cases passed.
- Developer smoke initially returned HTML500 for injected failure; final
  boundary sanitizes500 to bounded JSON and marks rollback.
- Developer found a misnamed allauth resend setting that disabled resend rather
  than allowing unbounded resend. Final pinned-framework setting and3→409
  regression passed independently.
- Fake-mail delivery is `on_commit`: a callback failure cannot undo a completed
  registration. Final fault test verifies no false email proof/authentication;
  contract now states the limit rather than claiming impossible rollback.
- Retention metadata/documentation now acknowledges temporary fake-mail
  snapshots and other actors' idempotency tombstones.
- The QA cancel-payload fixture failure is described above.

### Explicit incomplete gates — do not call the whole system complete

1. **Pending/unverified onboarding accounts have no self-service delete flow or
   scheduled cleanup in this contract.** Deletion tests cover verified,
   recently authenticated users. A safe future pending-delete design must not
   let duplicate signup delete an existing account.
2. No auth Flutter adapter/UI, secure native token storage, web deletion flow,
   browser login, Android/iOS/device or accessibility acceptance for this auth
   milestone. Phase1 Flutter results do not transfer to it.
3. No real SMTP, durable provider outbox/retry, HTTPS/public service, production
   DB-role isolation, KMS/rotation, backup deletion or production observability.
4. No timing-enumeration resistance/performance/DoS certification. Body/status
   checks and atomic counters are not a full abuse program.
5. Production retention/legal basis is unresolved. Synthetic deletion removes
   User/password/email/session and private domain rows, while minimal tombstones,
   deletion receipts, other users' idempotency receipts, expiring counters and
   fake mailbox snapshots until fixture teardown/exit can remain. No invented
   retention period or legal-hold behavior is asserted.
6. No E2EE keys/history recovery, message transport, D25 uploads, billing,
   activation entitlement, moderation/CSAE operations, store approval or real
   age/civil-identity proof. The identity API exposes no activation endpoint.
7. Some combinations below remain untested. Passing the named checks does not
   convert PARTIAL/NOT IMPLEMENTED rows to PASS.

## Acceptance matrix, scoped to this commit

PASS means the named scoped evidence passed. PARTIAL explicitly excludes the
remaining part; it is not launch approval. Full test names are catalogued below.

| Gate | Status | Evidence and remaining boundary |
|---|---|---|
| A2-ENV-01 | PASS, sandbox only | Boundary/eligibility tests, fake-delivery fault, reviewed configure/harness; no live provider test |
| A2-REG-01 | PASS, sampled inputs | Normalization, verified/unverified collisions, independent two-connection case-variant signup race; not exhaustive fuzzing |
| A2-ELIG-01 | PARTIAL |17-year-old, false/non-boolean declaration, stale/missing consent, real-email rejection; exact18th-birthday/leap-day matrix not newly exercised here; no actual age proof |
| A2-PASS-01 | PARTIAL | Argon2 storage/check, wrong/reset/change paths, installed framework validators inspected; comprehensive weak/oversize-password and credential-log audit not performed |
| A2-VERIFY-01 | PASS | Cross-session code and wrong-purpose attempts, pending reset does not verify; framework purpose binding inspected |
| A2-EXPIRY-01 | PARTIAL | Code/reset valid at600, expired beyond; idle/absolute fail at exact boundary, stale reauth rejected; exact300-second reauth edge not separately exercised |
| A2-REPLAY-01 | PASS, named flows | Verification replay, reset old links and concurrent distinct links, report concurrent replay; not every possible endpoint race |
| A2-SECRET-01 | PASS, fixture storage | Digest-as-bearer rejected; no raw bearer/code/password in tested session rows; wrong-key/tamper/swap fail closed; no production secret audit |
| A2-RESET-01 | PASS | Pending subject, unrelated actor, expiry/purpose, one winning concurrent reset and old-session revocation |
| A2-LOGIN-01 | PARTIAL | Verified login and pending/deleted/revoked denial, out-of-band password auth-hash invalidation; disabled-user fixture not explicitly exercised |
| A2-SESSION-01 | PASS, native scope | Login rotation, sync/async create/load/cycle/flush, digest lookup, empty fallback tables and rejected alternate auth transport |
| A2-REVOKE-01 | PASS | Logout/logout-all/password change/reset including pending challenges; actual DB and fresh HTTP process restart |
| A2-RACE-01 | PARTIAL | Concurrent signup/reset/delete/report and PG counter/exclusivity controls; not every login/verify/delete ordering. Activation is absent from this auth adapter |
| A2-AUTHZ-01 | PASS, inspected/tested scope | Third actor denied relationship read/cards/respond/cancel/end/exclusivity/report attribution; actors server-derived; not a universal penetration-test guarantee |
| A2-CSRF-01 | PASS, native-only boundary | Host/cookie/Origin/Bearer/query rejection; no browser-cookie authentication acceptance claim |
| A2-ENUM-01 | PARTIAL | Known/unknown signup/reset public response shapes and statuses match; no statistical timing guarantee or exhaustive resend/header matrix |
| A2-LIMIT-01 | PASS | Independent PG connections contend on one bucket; exact accepted count; no Python-only substitute |
| A2-LIMIT-02 | PASS, fixture policy | Case/space/X-Forwarded-For cannot bypass email limit,429+Retry-After, exact counter-window expiry; production tuning deferred |
| A2-REPORT-01 | PASS | Actor/key/payload conflict, concurrent dedup, block replay, purged replay410 with no recreated report |
| A2-REPORT-02 | PASS, metadata only | Target-first block does not prevent report; no evidence upload or automated public penalty path |
| A2-DELETE-01 | PARTIAL | Verified recent-auth deletion and reauth passed; pending/unverified account deletion not implemented |
| A2-DELETE-02 | PARTIAL | Erasure/revocation after DB+server restart, old reset denied, re-register gets new identity/domain without old rights; pending-account lifecycle excluded |
| A2-RETENTION-01 | PARTIAL | Synthetic residual records disclosed and inspected; production schedule/legal basis, pending cleanup and backup behavior unresolved |
| A2-ATOMIC-01 | PARTIAL | Injected signup/delete rollback, shared connection, concurrent reset success and uniqueness; reset failure-injection at every intermediate point not exercised |
| A2-MAIL-01 | PASS, fake fault scope | after-commit failure creates no verified access; process-memory mailbox only. Durable retry/SMTP not implemented |
| A2-PG-01 | PASS | Actual persistence, constraints, rollback, races/restarts, and exact owned-resource cleanup on pass and failure |
| A2-CLIENT-01 | NOT IMPLEMENTED | No phase2 auth mobile adapter/UI; old dev-bearer Flutter cannot silently switch contracts |
| A2-CLAIM-01 | PASS, documentation boundary | Scope/remaining gates explicit; no production/store/real-identity/KMS/E2EE claim |

## Reproduction

Run sequentially as `chatbot`, only with the explicit disposable-fixture approval;
do not point this at an existing database or supply an external DSN:

```sh
/home/chatbot/wainak-dev/auth-tools-phase2/venv/bin/python \
  /home/chatbot/wainak-dev/qa-auth-phase2/qa/phase2/run_auth_independent.py \
  --backend-root /home/chatbot/wainak-dev/backend-auth-phase2 \
  --run-disposable-identity
cd /home/chatbot/wainak-dev/backend-auth-phase2
PYTHONPATH=backend python3 -m unittest discover -s backend/tests
python3 contracts/build_contract.py --check
```

The QA extension receives only private Python callbacks, runs after lazy identity
migrations and the14 legacy PG cases, and never accepts a CLI DSN/key or exposes
an administrative HTTP endpoint. Assert messages avoid secret operands.

## Phase1 immutability and evidence correction

Read-only verification08:18 UTC found these clean, unchanged:
- main `9102af8606277c80412613e46dd7140d3b8fa663`;
- backend phase1 `59a79ea75fe37daf36bf1f7203140dcad66e3c2f`;
- mobile API phase1 `efd0421d559af6ee50ce04b887c7c40481d01aa0`;
- QA phase1 `6ecb205821b4f96919a1c1cd94a1e2d862b0a7b2`.

See `phase1-qa-evidence-erratum-20261024.md`: two historic supplementary
temporary-directory checks used the wrong parent/pattern. Historical exact
tempdir removal was harness-verified, not independently path-verified. No old
report was silently rewritten. Current phase2 independent checks use the actual
`/tmp/wainak-postgres-test-*` path; a later check does not prove an earlier one.

## Exact test-name catalogue

### Independent QA (22)

- `test_async_session_cycle_flush_and_manager_guards_do_not_store_raw_secrets`
- `test_atomic_rate_counter_uses_distinct_connections_and_exact_limit`
- `test_ciphertext_swap_wrong_key_and_digest_as_bearer_fail_closed`
- `test_concurrent_case_variant_signups_create_one_identity_without_password_overwrite`
- `test_concurrent_report_replay_creates_one_receipt_and_purged_replay_stays_gone`
- `test_default_framework_session_table_stays_empty_and_pending_secrets_are_encrypted`
- `test_delete_invalidates_reset_and_session_after_database_restart`
- `test_delete_racing_reset_never_resurrects_a_deleted_identity`
- `test_expired_reset_and_wrong_purpose_do_not_change_password_or_verification`
- `test_failure_after_domain_delete_rolls_back_identity_domain_and_session`
- `test_forwarded_ip_and_email_case_do_not_bypass_login_limit`
- `test_idle_read_refreshes_but_never_extends_absolute_session_cap`
- `test_minor_stale_terms_and_real_email_create_no_identity_or_domain_account`
- `test_policy_rollover_and_missing_consent_block_matching_but_not_safety`
- `test_report_idempotency_is_actor_scoped_and_survives_block`
- `test_reregister_after_delete_gets_new_domain_without_old_relationship_rights`
- `test_reset_enumeration_and_duplicate_signup_do_not_replace_identity`
- `test_reset_of_b_does_not_log_out_unrelated_authenticated_actor_a`
- `test_reset_with_pending_token_invalidates_it_without_verifying_email`
- `test_third_actor_cannot_read_mutate_or_attribute_report_to_foreign_relationship`
- `test_two_outstanding_reset_links_race_has_one_winner_and_revokes_sessions`
- `test_verify_code_is_session_bound_and_expired_code_cannot_authenticate`

### Developer identity cases independently rerun (30)

- `test_async_session_paths_share_digest_encryption_and_revocation_semantics`
- `test_atomic_rate_buckets_across_independent_connections_and_expiry`
- `test_auth_domain_registration_failure_rolls_back_one_transaction`
- `test_current_policy_is_checked_after_persisted_consent_becomes_stale`
- `test_delete_failure_after_domain_erasure_rolls_back_both_halves`
- `test_deleted_user_and_private_domain_data_are_physically_erased`
- `test_digest_manager_and_generic_serializers_refuse_raw_shortcuts`
- `test_duplicate_verified_signup_does_not_replace_password_or_domain`
- `test_eligibility_current_terms_and_native_transport_boundary`
- `test_fake_delivery_failure_after_commit_does_not_falsely_verify_or_login`
- `test_hash_encrypted_payload_no_raw_session_or_verification_code`
- `test_http_email_rate_limit_ignores_forwarded_address_and_expires_atomically`
- `test_known_unknown_public_reset_and_signup_shapes_do_not_enumerate`
- `test_logout_all_invalidates_an_older_pending_login_challenge`
- `test_password_change_revokes_all_sessions_and_pending_challenges`
- `test_password_reset_revokes_sessions_and_old_link_replay`
- `test_read_activity_touches_idle_but_not_absolute_expiry`
- `test_report_key_payload_actor_scope_and_post_block_replay`
- `test_reset_link_expires_after_framework_timeout`
- `test_reset_preserves_an_unrelated_authenticated_actor`
- `test_reset_with_current_pending_token_purges_it_without_verifying_email`
- `test_session_and_delete_survive_database_and_fresh_http_process_restarts`
- `test_session_ciphertext_tamper_wrong_key_and_cross_row_swap_fail_closed`
- `test_sessions_auth_hash_check_catches_out_of_band_password_change`
- `test_signup_verify_domain_bridge_logout_and_old_token_rejected`
- `test_stale_reauthentication_rejected_then_password_reauth_allows_delete`
- `test_two_outstanding_reset_links_are_invalidated_by_one_reset`
- `test_unverified_email_collision_cannot_overwrite_or_inherit_account`
- `test_verification_attempt_limit_and_resend_replace_previous_code`
- `test_verification_expiry_purpose_account_binding_and_replay`
