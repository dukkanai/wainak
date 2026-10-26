# Build-harness review remediation — stage 1

## Scope and status

This change follows the independent review of commit
`4b0bfafeebaceb7a892e03d39a56533c9eb7e0dc`. It changes CI orchestration and
regression coverage only. Application, archive/bridge source, dependency locks,
artifact acceptance rules, signing policy and resource limits are unchanged.

**Local verification passed; macOS/native artifact acceptance remains unverified.**
This is not a release, device-runtime test, security certification or evidence
that the sixth build's artifact-inspection failure has been resolved. The seventh
build stopped earlier during host tests. Its exact cloud root cause was not
established; a local filesystem-race defect capable of producing the same bounded
failure signature was independently reproduced.

## Six reviewed defects addressed

1. **Disappearing cache entry:** both budget readers use a shared descriptor-based
   traversal. Only ENOENT retries the complete scan, at most three times. Repeated
   churn fails rather than being silently ignored. Optional roots not yet created
   count as zero.
2. **Unreadable subtree undercount:** directory traversal no longer relies on
   os.walk/rglob's implicit error suppression. EACCES/EIO and other errors fail
   closed. File payload and directory/link metadata are counted; links are not
   followed. This remains periodic accounting, not an atomic snapshot or OS quota.
3. **Incomplete compiled-source inventory:** native source directories reject
   additional unreviewed inputs, whether tracked or untracked. The existing
   notices directory is non-compiler input for these pinned sources. Host copies
   come only from the reviewed hash allowlist, with source and destination checks.
   Inventory is rechecked before binding and during final audit.
4. **Fixed five-second EOF wait:** closing stdout is not child completion. Both
   drivers retain the original remaining command deadline, resource checks and
   cancellation while waiting for actual exit.
5. **Omitted native suite:** the manual workflow now includes ci/native test
   discovery in addition to ci/tests. The exact configuration checker requires
   both; no trigger, signing, publishing or paid provider configuration was added.
6. **Package-only pass proof:** Go JSON evidence must contain run and pass for the
   expected top-level tests. Full test binaries require all pinned declarations;
   each fuzz command requires its named target. Missing execution, skipped tests,
   incomplete/malformed output or failure events cannot produce proof PASS.

Native primary diagnostics now preserve only finite operation/type identifiers
and known numeric errno. No exception text, filename, arbitrary test/subtest name,
command argument or raw host-test output is added to the public projection.
A guard failure during the post-EOF wait is currently labelled wait_child or
wait_command rather than its more specific inner resource-check operation; errno
and failure status remain preserved.

## Verification on the candidate

- **229 Python tests passed, zero skips:** 161 ci/tests and 68 ci/native.
  This includes the prior 205 cases plus 24 added cases.
- Preparation checks, native recipe --check and whitespace/diff checks passed.
- Real unprivileged filesystem tests exercised an unreadable subtree, an actual
  unlink after enumeration, bounded repeated disappearance, EIO, symlink/FIFO
  boundaries and extra/missing source inputs.
- Real harmless child processes in both drivers continued for 5.4 seconds after
  stdout EOF and completed successfully within their original deadline.
  A short native deadline still terminated its child.
- Independent verification repeated all 229 cases and the static checks.
- An independent offline, stdlib-only Go fixture verified actual test2json output
  for full tests, subtests and fuzz seeds, plus actual fuzz JSON. This verifies
  event-schema compatibility only, not the application's cryptographic suites.
- Independent adversarial checks rejected a directory-to-symlink replacement,
  observed zero FD growth over 100 scans, retained errno 13 after post-spawn
  permission failure and child termination, and cancelled a child after EOF.

## Reproduction commands

Run as an unprivileged build user; the permission-boundary regression deliberately
fails if run as root rather than skipping that check.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/native -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 ci/check_preparation.py
PYTHONDONTWRITEBYTECODE=1 python3 ci/native/build.py --check
PYTHONDONTWRITEBYTECODE=1 python3 ci/ios/build.py --check
python3 scripts/check_publication.py
git diff --check
```

The publication checker is a narrow index/blob guard, not a comprehensive
credential scan or application security audit.

## Remaining gates

No macOS execution, new XCFramework inspection, iOS application compilation,
XCTest/device runtime or current-dependency cryptographic acceptance was performed
by this local remediation. Backend/mobile/operations/prototype findings are
separate stages and were not changed here. Any public push and another manual
cloud build require their own explicit approval; no merge, signing, payment or
release is implied.
