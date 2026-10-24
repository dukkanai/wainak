# Phase 3 independent findings (development only)

## P1 — same-session stale results restore blocked peer data/actions

Status: **OPEN, developer fix in progress; not yet independently validated**.
Observed on the early uncommitted Flutter draft, not the accepted main baseline.
Snapshot: `/home/chatbot/wainak-dev/qa-phase3-race-draft-20261024T1248`.

- matching_repository.dart SHA256 `a282e61aae0c6a5f8990c1d926f528aab5c5b84c2a1032c2305e7096d753207f`
- client.dart SHA256 `1416efbd3f46befd7a3a953d538762cf75cc4e8c107c450a3fcace8c25d0876a`
- independent final probe SHA256 `1de4c4259a5e36fc4e19a586a050ebfb654f6a6e4b81be461baf7e65ebb6e1de`

Injected-transport, pure Dart128 probe job
`fd349cd6-54ea-423b-9fa2-84f4d50b9fc1` at 12:49:42.721–12:49:43.557 exited1:
1. Deferred relationship-list response restores old peer/actions after block ack: FAIL.
2. Deferred accept response restores accepted peer after block ack: FAIL.
3. Deferred candidate-list response restores blocked candidate after block ack: FAIL.
4. Report tombstone410 preserves authentication (control): PASS.

The earlier same assertions without diagnostic labels also failed three cases in
job `e8307cd5-c3b4-4ec4-a648-ef74f9f26467` at12:48:34. This is not four new
failures or a real-server authorization bypass. It is stale client projection and
action restoration because session generation does not change when blocking.
The probe uses no network, DB, Flutter compiler or secret-bearing diagnostics.

Required correction: matching-operation revision/barrier or equivalent serialization,
not session generation alone, with independent re-execution of the same cases on
the exact final candidate. Preserve target/account binding and uncertain intent
keys. The server still must enforce block/role/eligibility on every request.
