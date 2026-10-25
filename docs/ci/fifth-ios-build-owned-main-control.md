# Fifth iOS attempt: validate upstream's owned main-module control

## Observed evidence and limits

Build `6adddc764a72334e32e4f795` used exact source
`a249074ef931433bde8b32838b4026c725497046` and failed at 10:43:47 UTC
on 2026-10-25. Native duration was 144.915 seconds. The receipt reports
`GRAPH_MISMATCH` at `unmodified-upstream-apple-bind`, with last command
`target-0-controls` PASS, exit 0, 0.959 seconds, failure kind NONE and empty test
categories. Outer primary error remained `command_failed_native`/`wait_command`;
cleanup errors were empty.

Exact source order proves that upstream gomobile bind returned successfully,
and target-0 module-list validation completed before the controls command.
Remaining checks at that point validate Exclude/Toolchain and replacements.
The cloud control values were NOT recovered. Artifact/header/slice acceptance,
Flutter integration, XCTest, device runtime and production security are NOT
established by command success.

## Source-reproduced incompatibility

Pinned upstream `golang/mobile` commit `197770444867`, file
`cmd/gomobile/bind.go`, Git blob `f942246cc662ed95cfd0548cfa57c34d3930e275`,
function `parseModuleVersions`, preserves versionless original modules with
`AddReplace(mod.Path, mod.Version, mod.Dir, "")`. It does not skip the original
main module. Our original main is `wainak.local/cibinding` in the owned native
`binding` directory. The generated module is `gobind`.

A synthetic fixture representing that precise branch reproduces successful
module/controls commands followed by the old checker rejecting `unapproved
replacement`. This is a source-proven incompatibility consistent with the cloud
failure, NOT a claim that the raw cloud control bytes or exact assertion were
retrieved. The fixture records its upstream provenance and evidence boundary.

## Narrow handling, not dependency relaxation

Only generated target-0/target-1 inspections may recognize the versionless
`wainak.local/cibinding` replacement to the exact canonical owned `work/binding`
directory. The target must be an owned, canonical device/simulator src-arm64
module under work/tmp, with exactly one main module named `gobind`. Links in
path components, traversal/alternate paths, duplicate/versioned replacements,
unknown controls, Exclude and Toolchain remain rejected.

The exception applies ONLY to replacement controls. It does not add a module
to the 26-version selected-module allowlist, the imported-package allowlist,
or either local product source mapping. A selected synthetic harness dependency
is explicitly rejected. Core/facade code, pins, offline acquisition, resource
limits and signing settings are unchanged. No upstream patch or interceptor.

A new fixed graph_reason enum distinguishes individual source guard failures
without outputting controls, paths, argv or exception text. Primary failures
remain preserved. Synthetic regression tests cover original rejection and narrow
acceptance, context/main/path/link/duplicate/version failures and enum redaction.
Full static suites and publication scanning must pass on the final development
commit; none constitutes native/runtime/security acceptance. No sixth cloud
run, local native compile, main change, signing, billing or deployment is part
of this source correction.
