# Prototype packaging containment remediation — stage 3

## Scope and status

This separate local branch is based on
`4b0bfafeebaceb7a892e03d39a56533c9eb7e0dc`. It changes only the synthetic
prototype packager, its stdlib regression tests and their existing CI unit-job
wiring. It does not include the separate build-harness or identity-save fixes.

**Local packaging checks and independent review passed.** This is not browser
runtime acceptance, application security certification, deployment or an iOS
build. No public publication or cloud run is part of this stage.

## Input boundary

- Normalize and validate every relative asset path, including OFL notices,
  downloadable licenses, README and ZIP inputs.
- Anchor all directory components with no-follow descriptors. Open and validate
  each regular input once, then consume that same descriptor.
- Reject symlinks (including internal ones), FIFOs and other special inputs.
  Enumeration failures are errors, not silently omitted files.
- Bound each asset read to 16 MiB, including growth after the initial stat.
- Preserve the existing optional missing-README behavior.

## Output boundary

Independent review of the initial input-only candidate demonstrated that an
existing output symlink could overwrite an external fixture and an output FIFO
could block. The revised candidate also closes these output defects:

- Require an owned output directory which is not group/world writable.
- Reject existing output symlinks, FIFOs, devices, foreign-owned files and
  multiply-linked files. The hardlink check prevents refreshing an output which
  shares an inode with another path.
- Preserve normal reruns: safe existing owned regular single-link outputs may
  be replaced. Never truncate an old output before checking its type.
- Stage exclusive temporary files, write and verify bytes through their opened
  descriptors, then use descriptor-relative atomic replacement.
- Revalidate directory and target identity around publication, publish the
  manifest last, and clean up only staging names still matching created inodes.
- Leave unrelated output files untouched.

Atomicity is **per file**, not across the three outputs. A later replacement
failure may leave a mixed old/new set, returns failure and does not publish the
new manifest. This is not a lock against arbitrary hostile same-user concurrent
filesystem mutation, a filesystem snapshot, or a guarantee of input immutability.

## Verification

As an unprivileged user, all **29 packaging tests and 21 existing ops unit tests
passed with zero skips**. Packaging tests cover normal HTML/ZIP/license content,
manifests, input links and ancestor swaps, same-descriptor reads after a swap,
unused unsafe inputs, FIFOs, permissions, invalid paths, size limits, external
CSS URLs and optional README behavior.

Output cases exercise each of the three named outputs as a symlink, FIFO and
hardlink; owned safe reruns without truncating an old open descriptor; unrelated
file preservation; writable-directory rejection; target drift; directory and
leaf swaps; replaced staging names; staging failure; and failure after the first
successful replacement.

An actual-prototype comparison against the base produced identical HTML and
identical contents for all seven ZIP entries. HTML was 1,211,893 bytes with SHA-256
`563971cc6b4b27cfca656a51712a22c797189a7cae4ba1508f2530fa55245dc7`.
Two further safe reruns succeeded and the manifest matched the output bytes.
These checks used isolated temporary outputs; no retained release artifact was
replaced. ZIP container metadata itself is not claimed byte-identical.

Independent review repeated the 29+21 cases, ran all nine unsafe-output cases in
bounded subprocesses, verified actual content parity and reruns, checked old
descriptor preservation and zero FD growth, and verified staging/second-replace
failure behavior. No blocker was found within the stated static-prototype scope.

Reviewed source hashes:

| File | SHA-256 |
| --- | --- |
| `prototype/package_preview.py` | `5ab0011aff9670806bbcd338e173df5798f342c68a3acc4684ae89c82af3db44` |
| `prototype/test_package_preview.py` | `d30c2a7acd1c0fafa76e106f96d104008b90b85794e857f8e6ae88fee7df3870` |
| `.github/workflows/ci.yml` | `11a4fd741e460e4ee1cef0b49040424fd180a1f86cb0b8bbf285134d34921dc8` |

## Reproduction

Run as an unprivileged user: the permission test deliberately fails for root,
rather than skipping the boundary.

```sh
PYTHONDONTWRITEBYTECODE=1 timeout 90 python3 -m unittest discover -s prototype -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ops -p 'test_*.py' -v
python3 scripts/check_publication.py
git diff --check
```

The publication check is only the repository's narrow index/blob guard, not a
comprehensive credential scan. No Docker recovery drill, browser test, native
build, dependency upgrade, signing, payment or production operation was performed.
