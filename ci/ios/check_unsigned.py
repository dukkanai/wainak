#!/usr/bin/env python3
"""Verify absence of an Apple code signature; never creates or removes one."""
import json
import pathlib
import subprocess
import sys
from unsigned_diagnostics import PREFIX, failure_report, macho_signature, signature_class

MAX_CODESIGN_OUTPUT = 65536


def fail(category, app=None, returncode=None, output=b''):
    print(PREFIX + json.dumps(failure_report(category, app, returncode, output), sort_keys=True))
    return 1


def check(app):
    try:
        if app.is_symlink() or not app.is_dir() or any((app / name).exists() or (app / name).is_symlink()
                for name in ('_CodeSignature', 'embedded.mobileprovision')):
            return fail('bundle_metadata', app)
        result = subprocess.run(['/usr/bin/codesign', '-d', '--verbose=4', str(app)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=15, check=False)
    except subprocess.TimeoutExpired:
        return fail('codesign_timeout', app)
    except OSError:
        return fail('codesign_tool_error', app)
    # The same strict acceptance predicate: no detected signature, plus the
    # explicit unsigned diagnostic. Ad-hoc signatures are not unsigned.
    if len(result.stdout) > MAX_CODESIGN_OUTPUT:
        return fail('codesign_output_bound', app, result.returncode)
    detected = signature_class(result.stdout, result.returncode)
    if (result.returncode == 0 or detected in ('adhoc', 'other_or_unknown_signature')
            or macho_signature(app) == 'present'):
        return fail('signature_present', app, result.returncode, result.stdout)
    if b'code object is not signed at all' not in result.stdout:
        return fail('unexpected_codesign_output', app, result.returncode, result.stdout)
    print('PASS_UNSIGNED_APP')
    return 0


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        return fail('invalid_arguments')
    return check(pathlib.Path(args[0]))


if __name__ == '__main__':
    raise SystemExit(main())
