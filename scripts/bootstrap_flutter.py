#!/usr/bin/env python3
"""Install the pinned official Flutter source in a fresh, caller-owned CI directory."""
import argparse
import json
import os
from pathlib import Path
from ci_process import run_bounded

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools-root', required=True, type=Path)
    args = parser.parse_args()
    root = args.tools_root.absolute()
    if root.exists() or root.is_symlink():
        raise SystemExit('Flutter tools destination must be new')
    pins = json.loads((ROOT / 'ci/ios-host-pins.json').read_text())['flutter']
    root.mkdir(mode=0o700)
    for leaf in ('home', 'pub-cache'):
        (root / leaf).mkdir(mode=0o700)
    sdk = root / 'flutter'
    run_bounded(['git', 'clone', '--depth', '1', '--branch', pins['version'],
                 'https://github.com/flutter/flutter.git', str(sdk)], cwd=ROOT, check=True)
    head = run_bounded(['git', '-C', str(sdk), 'rev-parse', 'HEAD'], cwd=ROOT, check=True).stdout.strip()
    if head != pins['framework_revision']:
        raise SystemExit('Flutter tag does not match the reviewed framework commit')
    flutter = str(sdk / 'bin/flutter')
    env = dict(os.environ, PUB_CACHE=str(root / 'pub-cache'), CI='true', FLUTTER_SUPPRESS_ANALYTICS='true')
    run_bounded([flutter, 'config', '--no-analytics'], cwd=ROOT, env=env, check=True)
    run_bounded([flutter, 'precache', '--linux'], cwd=ROOT, env=env, check=True, seconds=600)
    version = json.loads(run_bounded([flutter, '--version', '--machine'], cwd=ROOT, env=env,
                                    check=True, seconds=120).stdout)
    if (version['frameworkRevision'] != pins['framework_revision']
            or version['engineRevision'] != pins['engine_revision']
            or version['dartSdkVersion'] != pins['dart_version']):
        raise SystemExit('Flutter/Dart runtime differs from reviewed pins')
    print(json.dumps({'flutter': version['frameworkVersion'], 'framework': head,
                      'dart': version['dartSdkVersion'], 'tools_root': str(root)}))


if __name__ == '__main__':
    main()
