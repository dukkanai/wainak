#!/usr/bin/env python3
"""Inspect Git index blobs only; never read ignored runtime secrets or print matches.

A narrow publication guard, not a complete secret scanner or security audit.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {'.runtime', 'backups', '.codex', '.playwright-mcp', 'secrets',
                   'credentials', 'node_modules', '__pycache__', '.dart_tool',
                   '.ci-work', '.ci-github', '.gradle', '.venv', 'build'}
FORBIDDEN_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.dump', '.pyc', '.log',
                      '.apk', '.aab', '.aar', '.ipa', '.xcarchive', '.xcframework'}
PATTERNS = {
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'GitHub token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'AWS access key': re.compile(rb'AKIA[0-9A-Z]{16}'),
    'Stripe secret': re.compile(rb'sk_live_[0-9A-Za-z]{20,}'),
}


def main():
    entries = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT).decode().split('\0')
    errors = []
    count = 0
    for entry in filter(None, entries):
        metadata, name = entry.split('\t', 1)
        mode, oid, stage = metadata.split()
        path = Path(name)
        if (set(path.parts) & FORBIDDEN_PARTS
                or any(Path(part).suffix.lower() in FORBIDDEN_SUFFIXES for part in path.parts)
                or (path.name.startswith('.env') and path.name != '.env.example')
                or name.startswith(('prototype/releases/', 'prototype/qa/results/'))):
            errors.append((name, 'excluded file is tracked'))
            continue
        if mode not in {'100644', '100755'} or stage != '0':
            errors.append((name, 'not a regular resolved source file'))
            continue
        data = subprocess.check_output(['git', 'cat-file', 'blob', oid], cwd=ROOT)
        count += 1
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                errors.append((name, label + ' pattern'))
    for name, reason in errors:
        print(f'FAIL {name}: {reason}', file=sys.stderr)
    print(f'Checked {count} tracked source files; {len(errors)} publication issue(s).')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
