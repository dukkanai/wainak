# Phase 2 private identity PIPE fixture — independent QA

Date: 2026-10-24 UTC. Development fixture only; no deployment or production approval.

## Exact source and scope

Backend: `144937a34e88e3b558b0c9a007d36d529c5621a1`, branch
`dev/phase2-auth-20261024`, worktree `/home/chatbot/wainak-dev/backend-auth-phase2`.
The additive change consists only of the five fixture/protocol/probe/document/test
files below. Application baseline `93dd42f2141d551e86ec55861bc66802be247bef`
remains an ancestor; prior identity/deletion results are separately documented,
not silently counted as rerun here.

- `backend/integration/identity_fixture_protocol.py`
- `backend/integration/serve_identity_fixture.py`
- `backend/integration/probe_identity_fixture.py`
- `backend/integration/IDENTITY_PIPE.md`
- `backend/tests/test_identity_fixture_protocol.py`

All server commands were run as `chatbot` on confirmed host `ostath`. A single
reserved PostgreSQL window was used, without a Flutter compiler in parallel.
Owner runtime memory limit remained 1 GiB. No main merge, deployment, existing DB
migration, real SMTP/account, persistent application key or public service was used.

## Isolation review

The fixture requires explicit opt-in and anonymous OS stdin/stdout pipes before
creating a fresh owned PostgreSQL container. It reuses the reviewed pinned-image,
network-none/no-published-port harness and exact owned-resource cleanup. Application
keys and fake-mail values remain in Python/test process memory; the PG fixture's
short-lived private credential file is owned and removed with its temporary dir.

WSGI binds only `127.0.0.1:0`. The same process owns its WSGI thread and committed
fake mailbox; there is no HTTP mailbox/admin route, verification bypass, production
DSN option or access credential in argv/environment/protocol diagnostics. The
private protocol can retrieve a strictly selected synthetic email/purpose event
newer than its cursor. Reset extraction never follows its fixed synthetic URL.

Input, command count, output and time are bounded. Duplicate keys, unsupported
fields/purposes, non-fixture destinations, named FIFO/file redirection and malformed
values fail closed. HTTP probes disable proxies and redirects. Failure text is
fixed and does not echo secret-bearing operands. Normal success requires terminal
cleanup acknowledgement AND process exit 0, not merely a shutdown acknowledgement.

QA identified a draft boundedness defect: a buffered command batch could defer
stop/lifetime checks until the next read and overrun its overall deadline through
multiple bounded writes. The developer fixed it before this exact commit with
per-command stop/deadline checks and remaining-lifetime output budgets; the focused
regression is included in the independently rerun suite. This was a test-harness
control issue, not a production authentication bypass.

## Runtime evidence

Independent job `01502cdc-c1be-4487-ab91-5968a24f9cbd`,
09:29:39.028–09:32:14.630 UTC, exit 0, on the exact clean commit above;
HEAD and clean worktree were checked before and after the run.

- 68 unit/control tests PASS in 0.160 s, including 11 protocol tests.
- Five separate disposable fixture probes: **5/5 PASS**, including normal cleanup
  acknowledgement and the required artifact inventory equality after each case.
- Independent post-run audit job `6a7cf5b6-8fae-4958-a58a-15df11bac46c` at
  09:33:20.971 UTC: **0 labeled containers, 0 labeled volumes, 0 chatbot-owned
  `/tmp/wainak-postgres-test-*` directories, 0 fixture/probe processes**.
  Exact HEAD remained clean and `git diff --check` passed.

Each probe reruns the same 14 legacy PostgreSQL prerequisites. Those repeated
prerequisites are not 70 new unique tests. The five scenarios are normal real HTTP
signup/pending/private-mail verification/profile/second-login/global-revoke/login/
reauth/delete; stdin EOF; SIGTERM during partial HTTP headers; 2-second ready-state
lifetime expiry; and broken protocol stdout. The last cannot acknowledge cleanup,
so its independent artifact inventory is essential.

## Source hashes and reproducibility

| File | SHA-256 |
|---|---|
| protocol | `a23d90761d95c8430219aae110e744cf0ae1c62b73406c6c540a528549df4122` |
| server fixture | `83194285de3d16759536009c9a6ba9ebb73f272291487911d1dcf5930b181177` |
| private probes | `44eaee5ccf719fcea544d61f2ce607a9e580fd6ce9afaa1793c2530bfa3993e5` |
| protocol tests | `c0b1acf035af37388d1f8e56a2989a2e0785a02ca884fc2091af6f4a21172367` |
| fixture documentation | `1292d69899946b9dc23b43bdba8afe629736b586960698236a175c1536239702` |

Commands, as chatbot from the exact backend worktree, with
`PYTHONDONTWRITEBYTECODE=1` and the existing isolated auth venv:

```sh
PYTHONPATH=backend <venv-python> -m unittest discover -s backend/tests -v
<venv-python> backend/integration/probe_identity_fixture.py --run-disposable-fixture-probes
```

The independent audit queried only the fixture Docker label
`com.wainak.disposable-postgres-test`, matching chatbot-owned non-symlink temporary
directories, and exact fixture/probe argv file names. It removed no resource.
The five-file-only diff versus `93dd42f` was independently checked.

## Limits and remaining gates

This result does not prove Flutter widget integration. Flutter auth compilation
under the separate 384 MiB frontend heap failed before assertions; that is NOT RUN
for widget behavior, not a successful functional test. The new Dart bridge and
mobile auth source require separate frozen-source validation. Client-only live
integration, if later successful, must not be relabeled as widget/device E2E.

The fixture's WSGI server is an owned thread, not a fresh-process auth restart
experiment. Earlier identity restart evidence has its own exact baseline. No real
SMTP delivery, TLS, native secure storage, production KMS/key rotation, legal
retention, moderation, browser/device accessibility or store approval is established.
SIGKILL/host loss is not claimed to guarantee resource cleanup; forced termination
requires explicit independent audit. No sensitive PIPE values were printed or saved
by this review.
