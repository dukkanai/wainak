# Phase 3 independent findings (development only)

## P1 — same-session stale results restore blocked peer data/actions

Status: **CLOSED on the independently tested final mobile a271d98/backend 3bc638f pair**.
Observed on the early uncommitted Flutter draft, not the accepted main baseline.
Snapshot: `/home/chatbot/wainak-dev/qa-phase3-race-draft-20261024T1248`.

- matching_repository.dart SHA256 `a282e61aae0c6a5f8990c1d926f528aab5c5b84c2a1032c2305e7096d753207f`
- client.dart SHA256 `1416efbd3f46befd7a3a953d538762cf75cc4e8c107c450a3fcace8c25d0876a`
- independent final probe SHA256 `1de4c4259a5e36fc4e19a586a050ebfb654f6a6e4b81be461baf7e65ebb6e1de`

Injected-transport, pure Dart 128 MiB probe job
`fd349cd6-54ea-423b-9fa2-84f4d50b9fc1` at 12:49:42.721–12:49:43.557 exited 1:
1. Deferred relationship-list response restores old peer/actions after block ack: FAIL.
2. Deferred accept response restores accepted peer after block ack: FAIL.
3. Deferred candidate-list response restores blocked candidate after block ack: FAIL.
4. Report tombstone 410 preserves authentication (control): PASS.

The earlier same assertions without diagnostic labels also failed three cases in
job `e8307cd5-c3b4-4ec4-a648-ef74f9f26467` at 12:48:34. This is not four new
failures or a real-server authorization bypass. It is stale client projection and
action restoration because session generation does not change when blocking.
The probe uses no network, DB, Flutter compiler or secret-bearing diagnostics.

Required correction: matching-operation revision/barrier or equivalent serialization,
not session generation alone, with independent re-execution of the same cases on
the exact final candidate. Preserve target/account binding and uncertain intent
keys. The server still must enforce block/role/eligibility on every request.

## Independent closure

The unchanged final probe passed 4/4 on committed 53 core source in job
`76302cd1-f351-4c23-8325-08db3aea73cc` at 13:17:26, and again on exact final
`a271d98e47c63931bd3d43cf2404e0ae0d67ca39` in job
`8932ed86-11ad-44b4-81ab-0f7619abeb6e`, ending 13:38:08.695. The same final job
passed the cold 56-case suite and actual two-actor matching widget→HTTP→allauth→PG
journey. Repository SHA 3865ed344c881b63fa7876220e91ec17553b087be74abc54ea450b79001af35e
and client SHA b577710ca3e56169a9e35df267b1af7eaa6cd578f9c7c342d341a9836415aecc
implement operation/read revision checks and actor-bound contexts; successful block
clears peer projections while older operations are rejected.

See `phase3-auth-matching-qa-results.md` for the separate live-test setup failure,
test-only correction, final source/cleanup evidence and remaining production limits.
This closure concerns the reproduced client race, not a general security guarantee.
