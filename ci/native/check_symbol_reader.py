#!/usr/bin/env python3
"""Opt-in tiny real-object regression, using explicit existing LLVM tools only.

No SDK, linker, network, package installation, application code or native object
execution. Linux LLVM output is not proof that a selected Xcode artifact passes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from artifact_diagnostics import ABI_NAMES, strict_symbols_present, symbol_summary
from artifact_static import static_arm64_container, validate_apple_load_commands

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def run(command):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=20)
    require(len(result.stdout) + len(result.stderr) <= 1024 * 1024, 'fixture output bound')
    require(result.returncode == 0, 'fixture tool failed; no fallback')
    return result.stdout.decode('utf-8')

def fixture_source(mode):
    names = ABI_NAMES[1:] if mode in ('missing', 'undefined') else ABI_NAMES
    if mode == 'nontext':
        return '\n'.join('int Archivebridge' + name + ' = 1;' for name in names) + '\n'
    text = '\n'.join('void Archivebridge' + name + '(void) {}' for name in names) + '\n'
    if mode == 'undefined':
        text += 'extern void ArchivebridgeCancel(void);\nvoid PublicReference(void) { ArchivebridgeCancel(); }\n'
    return text

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llvm-bin', type=Path, required=True)
    parser.add_argument('--temp-root', type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() != 0, 'run as an unprivileged user')
    directory = args.llvm_bin.resolve(strict=True)
    tools = {name: directory / name for name in ('clang', 'llvm-nm', 'llvm-ar', 'llvm-objdump')}
    require(all(path.is_file() and os.access(path, os.X_OK) for path in tools.values()),
            'all explicit existing LLVM tools required')
    require(args.temp_root.is_dir(), 'existing temporary root required')
    require(shutil.disk_usage(args.temp_root).free >= 4 * 1024**3, 'minimum free disk')
    before = len(os.listdir('/proc/self/fd')) if Path('/proc/self/fd').exists() else None
    results = []
    with tempfile.TemporaryDirectory(prefix='native-symbol-fixture-', dir=args.temp_root) as temporary:
        root = Path(temporary)
        for variant in ('device', 'simulator'):
            target = 'arm64-apple-ios15.0' + ('-simulator' if variant == 'simulator' else '')
            for mode in ('native', 'embedded', 'bitcode', 'missing', 'undefined', 'nontext', 'wrong_arch'):
                folder = root / (variant + '-' + mode)
                folder.mkdir()
                source, obj, archive = folder/'public.c', folder/'public.o', folder/'public.a'
                source.write_text(fixture_source(mode))
                flags = ['-fembed-bitcode'] if mode in ('embedded', 'missing', 'undefined', 'nontext') else (['-emit-llvm'] if mode == 'bitcode' else [])
                actual_target = 'x86_64-apple-ios15.0-simulator' if mode == 'wrong_arch' else target
                run([str(tools['clang']), '-target', actual_target, '-c', '-x', 'c',
                     *flags, str(source), '-o', str(obj)])
                run([str(tools['llvm-ar']), 'rcs', str(archive), str(obj)])
                static_arm64_container(archive)  # Container only, NOT an object-member claim.
                data = obj.read_bytes()
                native = len(data) >= 32 and struct.unpack_from('<I', data)[0] == 0xfeedfacf
                arm64 = native and struct.unpack_from('<I', data, 4)[0] == 0x0100000c
                load_pass = False
                if native:
                    text = run([str(tools['llvm-objdump']), '--macho', '--private-headers', str(obj)])
                    try:
                        validate_apple_load_commands(text, variant)
                        load_pass = True
                    except ValueError:
                        pass
                raw_default = run([str(tools['llvm-nm']), '-g', str(archive)])
                raw_native = run([str(tools['llvm-nm']), '-g', '--no-llvm-bc', str(archive)])
                default_pass = bool(strict_symbols_present(raw_default))
                native_pass = bool(strict_symbols_present(raw_native))
                expected_symbols = mode in ('native', 'embedded', 'wrong_arch')
                require(native_pass == expected_symbols, 'native reader symbol expectation')
                require(default_pass == (mode in ('native', 'wrong_arch')), 'default reader expectation')
                accepted = arm64 and load_pass and native_pass
                require(accepted == (mode in ('native', 'embedded')), 'combined fixture expectation')
                results.append({'variant': variant, 'mode': mode, 'native_object': native,
                                'arm64': arm64, 'load_commands_pass': load_pass,
                                'default_strict_symbols': default_pass,
                                'native_only_strict_symbols': native_pass,
                                'combined_fixture_accepts': accepted,
                                'default_summary': symbol_summary(raw_default),
                                'native_summary': symbol_summary(raw_native),
                                'object_sha256': hashlib.sha256(data).hexdigest()})
        require(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) < 1024*1024,
                'tiny fixture aggregate bound')
    after = len(os.listdir('/proc/self/fd')) if before is not None else None
    require(before == after, 'fixture descriptor leak')
    print(json.dumps({'status': 'PASS_REAL_SYNTHETIC_OBJECTS_ONLY',
                      'cases': results, 'case_count': len(results), 'fd_delta': None if before is None else after-before,
                      'actual_xcode_artifact_reinspection': False}, sort_keys=True))

if __name__ == '__main__':
    main()
