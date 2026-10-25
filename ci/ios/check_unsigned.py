#!/usr/bin/env python3
"""Verify absence of an Apple code signature; never creates one."""
import pathlib
import subprocess
import sys


def main():
    app = pathlib.Path(sys.argv[1])
    if app.is_symlink() or not app.is_dir() or (app / '_CodeSignature').exists() or (app / 'embedded.mobileprovision').exists():
        raise SystemExit(1)
    result = subprocess.run(['/usr/bin/codesign', '-d', str(app)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=15, check=False)
    if result.returncode == 0 or b'code object is not signed at all' not in result.stdout:
        raise SystemExit(1)
    print('PASS_UNSIGNED_APP')


if __name__ == '__main__':
    main()
