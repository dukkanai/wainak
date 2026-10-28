# Native symbol reader selection — stage 4

> سجل تاريخي لنسخة محددة: النتائج والحدود أدناه تصف وقت إعداد هذا التقرير، ولا تمثل تلقائيًا النسخة الحالية. المرجع الحالي: [حالة المشروع](../STATUS.md).

## Scope and status

This isolated change is based on stage 1 commit
`9ee256dd9c5e857dc75c3971a564d800d1fd4fba`. It adds `--no-llvm-bc` to the existing
`xcrun nm -g` inspection command. The strict symbol parser, native sources,
upstream tool/source pins, compiler flags, archive/architecture/load-command
checks, resource limits and manual cloud workflow are unchanged.

**Local regression checks pass. The failed eighth artifact has not been
re-inspected, and the selected Xcode executable has not run this changed
command.** No public push or ninth cloud build is part of this local work.

## Evidence and causal limit

The eighth run on the base commit reached artifact inspection. Both slices
reported all seven required names as text definitions, but all were addressless.
The unchanged acceptance expression requires a hexadecimal address with a text
symbol type, so the symbol gate failed. Other successful observations do not
establish complete artifact acceptance.

The pinned gomobile source `cmd/gomobile/env.go` adds `-fembed-bitcode` for both
iOS and simulator targets (lines 217 and 223). Its local verified SHA-256 is
`0a8be58a499bc36f8fe0dd8da7a44f5c4388d000f12b041d95158d29a359285b`.

A real, tiny arm64 Mach-O fixture compiled with that flag reproduced the failure:
the default LLVM reader showed dashed-address text symbols, while native-only
reading of the exact same bytes exposed the native hexadecimal addresses.
A pure-bitcode-only archive remained rejected. This establishes a reproducible
reader-selection defect consistent with the cloud observation, not proof of the
complete contents or eventual acceptability of the failed cloud artifact.

Primary documentation supports the choice:
- Apple's [nm manual](https://github.com/apple-oss-distributions/cctools/blob/main/man/nm.1#L38)
  identifies llvm-nm as the default since Xcode 8.
- [LLVM's nm documentation](https://llvm.org/docs/CommandGuide/llvm-nm.html)
  describes addressless bitcode symbols and the native-only reader option.
- LLVM's [option declarations](https://github.com/llvm/llvm-project/blob/main/llvm/tools/llvm-nm/Opts.td)
  specify the double-dash spelling `--no-llvm-bc`.

The change does **not** accept addressless symbols or change compilation to
remove embedded IR. If the selected tool rejects the option, its command fails;
there is no fallback to a less restrictive reader or parser. If a required
definition exists only as bitcode, its absence from native output fails the
unchanged symbol gate even when nm itself exits successfully.

## Regression coverage

- **232 Python tests pass, zero skips:** 164 CI cases and 68 native harness cases.
  Three new cases check the exact native-only command for both slices, rejection
  of absent/addressless/undefined native evidence, and propagation of an
  unsupported-option failure without retry/fallback.
- Preparation, native recipe and iOS recipe static checks pass.
- The opt-in fixture checker passes **14 real synthetic object cases**:
  device and simulator crossed with native, embedded-bitcode, pure-bitcode,
  missing symbol, undefined symbol, non-text symbols and wrong architecture.
- Native and embedded-native arm64 fixtures pass native-symbol, architecture and
  load-command checks. Pure bitcode, missing/undefined/non-text symbols and wrong
  architecture do not pass the combined fixture check.
- The wrong-architecture control deliberately has valid symbol addresses; this
  demonstrates why symbol evidence alone is not architecture acceptance.
- Fixture outputs total less than 1 MiB, use existing LLVM 21 tools without
  installation or network, are never executed, and are removed from their owned
  temporary directory. Descriptor count is unchanged.

The real-object checker is opt-in and requires explicit existing tools. It is
not silently skipped during unit discovery, and it is not presented as an
automatically executed cloud gate. Its local LLVM result does not replace
validation on the selected Apple toolchain.

## Reproduction

Run as an unprivileged user in an approved environment:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/tests -p 'test_*.py' -q
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s ci/native -p 'test_*.py' -q
PYTHONDONTWRITEBYTECODE=1 python3 ci/check_preparation.py
PYTHONDONTWRITEBYTECODE=1 python3 ci/native/build.py --check
PYTHONDONTWRITEBYTECODE=1 python3 ci/ios/build.py --check
PYTHONDONTWRITEBYTECODE=1 python3 ci/native/check_symbol_reader.py \
  --llvm-bin /approved/existing/llvm/bin --temp-root /approved/temporary/root
git diff --check
```

The fixture checker requires clang, llvm-nm, llvm-ar and llvm-objdump. It compiles
only public synthetic C definitions to objects; it does not link or execute them,
install an SDK, or build the application's native implementation.

## Remaining acceptance

A later explicitly approved Mac run must still satisfy every existing artifact
and application build gate. The eighth artifact's actual native definitions,
the selected Xcode option behavior, unsigned iOS application compilation and
runtime/security acceptance remain unverified by this local change. The other
two local remediation branches have not been integrated here.
