#!/usr/bin/env python3
"""Portable Linux host checks for synthetic archive/bridge; no mobile native build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from ci_process import run_bounded

ROOT = Path(__file__).resolve().parents[1]


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def cache_inventory(env):
    """Hash owned compiler caches outside the runtime canary-scanned directory."""
    inventory = {}
    files = size = 0
    for name in ('GOCACHE', 'GOMODCACHE', 'GOTMPDIR'):
        root = Path(env[name])
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError('Owned Go cache boundary changed')
        rows = {}
        for path in sorted(root.rglob('*')):
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise RuntimeError('Unexpected special file in owned Go cache')
            files += 1
            size += info.st_size
            if files > 100000 or size > 3 * 1024 ** 3:
                raise RuntimeError('Owned Go cache inventory exceeded its bound')
            rows[str(path.relative_to(root))] = digest_file(path)
        inventory[name] = rows
    return inventory


def validate_go_events(output, code):
    started, finished = set(), set()
    skipped = failed = package_pass = 0
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise RuntimeError('Malformed Go test JSON') from exc
        if not isinstance(event, dict):
            raise RuntimeError('Malformed Go test event')
        action, name = event.get('Action'), event.get('Test')
        if name:
            if action == 'run':
                if name in started:
                    raise RuntimeError('Duplicate Go test execution')
                started.add(name)
            elif action in ('pass', 'fail', 'skip'):
                if name not in started or name in finished:
                    raise RuntimeError('Go outcome has no unique execution')
                finished.add(name)
                skipped += action == 'skip'
                failed += action == 'fail'
        elif action == 'pass':
            package_pass += 1
        elif action in ('fail', 'skip'):
            failed += 1
    if code or not started or started != finished or package_pass != 1 or skipped or failed:
        raise RuntimeError('Go tests failed, skipped, or did not execute')
    return {'passed': len(finished), 'skipped': skipped, 'packages': package_pass}


def make_cli_module(path, lock):
    path.mkdir(mode=0o700)
    required = ''.join('\t' + row['path'] + ' ' + row['version'] + '\n' for row in lock['input_modules'])
    (path / 'go.mod').write_text('module wainak.local/ciagetool\n\ngo 1.27.3\n\nrequire (\n' + required + ')\n')
    sums = []
    for row in lock['input_modules'] + lock['auxiliary_modules']:
        sums.append(row['path'] + ' ' + row['version'] + '/go.mod ' + row['go_mod_sum'])
        if not row.get('metadata_only'):
            sums.append(row['path'] + ' ' + row['version'] + ' ' + row['sum'])
    (path / 'go.sum').write_text('\n'.join(sorted(set(sums))) + '\n')


def run(command, cwd, env, seconds=300):
    result = run_bounded(command, cwd=cwd, env=env, seconds=seconds)
    if result.returncode:
        # Source test names/exit are enough to select a local reproduction. Never publish CLI payloads.
        print(json.dumps({'command': str(command[1]), 'status': 'FAILED', 'exit_code': result.returncode}), flush=True)
        raise RuntimeError('Go command failed; raw output withheld')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--go', default=shutil.which('go'))
    args = parser.parse_args()
    if not args.go:
        raise SystemExit('Go executable is required')
    go = Path(args.go).resolve(strict=True)
    lock = json.loads((ROOT / 'ci/native/lock.json').read_text())
    env = dict(os.environ, GOTOOLCHAIN='local', GOENV='off', GOWORK='off', GOTELEMETRY='off',
               GOFLAGS='-mod=readonly -p=1', GOMAXPROCS='2', GOMEMLIMIT='1GiB',
               GOPROXY='https://proxy.golang.org', GOSUMDB='sum.golang.org',
               GOPRIVATE='', GONOPROXY='', GONOSUMDB='')
    version = run([go, 'version'], ROOT, env).stdout.strip()
    if ' go1.27.3 ' not in version:
        raise SystemExit('Go must match the reviewed 1.27.3 module toolchain')
    with tempfile.TemporaryDirectory(prefix='wainak-go-ci-') as temporary:
        work = Path(temporary)
        for name in ('GOCACHE', 'GOMODCACHE', 'GOTMPDIR'):
            cache = work / name.lower()
            cache.mkdir(mode=0o700)
            env[name] = str(cache)
        cli_module = work / 'cli-module'
        make_cli_module(cli_module, lock)
        age = work / 'age'
        run([go, 'build', '-trimpath', '-o', age, 'filippo.io/age/cmd/age'], cli_module,
            dict(env, CGO_ENABLED='0'))
        age.chmod(0o700)
        age_hash = digest_file(age)
        overlays = {
            'archive-independent-bound': {'Replace': {str(ROOT / 'archive/qa_independent_bound_test.go'):
                str(ROOT / 'qa/phase5_archive/bound_internal_test.go.txt')}},
            'bridge-independent': {'Replace': {str(ROOT / 'archivebridge/qa_independent_test.go'):
                str(ROOT / 'qa/phase6_archive_bridge/bridge_independent_test.go.txt')}},
        }
        cases = [
            ('archive', ROOT / 'archive', None, None),
            ('bridge', ROOT / 'archivebridge', None, None),
            ('archive-independent', ROOT / 'qa/phase5_archive', None, None),
            ('archive-independent-bound', ROOT / 'archive', 'archive-independent-bound', '^TestQABoundedCopyProbe$'),
            ('bridge-independent', ROOT / 'archivebridge', 'bridge-independent', '^TestQA'),
        ]
        for label, directory, overlay_name, pattern in cases:
            binary = work / (label + '.test')
            flags = []
            if overlay_name:
                overlay = work / (overlay_name + '.json')
                overlay.write_text(json.dumps(overlays[overlay_name]))
                flags.append('-overlay=' + str(overlay))
            run([go, 'test', '-c', '-race', *flags, '-o', binary, '.'], directory, dict(env, CGO_ENABLED='1'))
            run([go, 'vet', *flags, './...'], directory, env)
            runtime = work / (label + '-runtime')
            runtime.mkdir(mode=0o700)
            for source in directory.glob('*.go'):
                if source.is_symlink():
                    raise RuntimeError('Source symlink is not allowed')
                (runtime / source.name).write_bytes(source.read_bytes())
            for leaf in ('home', 'tmp'):
                (runtime / leaf).mkdir(mode=0o700)
            runtime_env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C',
                'HOME': str(runtime / 'home'), 'TMPDIR': str(runtime / 'tmp'),
                'GOENV': 'off', 'GOTOOLCHAIN': 'local', 'GOTELEMETRY': 'off', 'GOWORK': 'off',
                'GOPROXY': 'off', 'GOSUMDB': 'off', 'GOMAXPROCS': '2', 'GOMEMLIMIT': '1GiB',
                'WAINAK_ARCHIVE_INTEROP': '1', 'WAINAK_AGE_CLI': str(age),
                'WAINAK_AGE_CLI_SHA256': age_hash, 'WAINAK_ARCHIVE_SCAN_ROOT': str(runtime)}
            args = [go, 'tool', 'test2json', '-t', '-p', label, binary,
                    '-test.v=test2json', '-test.count=1', '-test.timeout=120s']
            if pattern:
                args.append('-test.run=' + pattern)
            cache_before = cache_inventory(env)
            binary_hash = digest_file(binary)
            result = run(args, runtime, runtime_env, seconds=150)
            summary = validate_go_events(result.stdout, result.returncode)
            if cache_before != cache_inventory(env):
                raise RuntimeError('Compiler caches changed during runtime tests')
            if digest_file(age) != age_hash or digest_file(binary) != binary_hash:
                raise RuntimeError('Go runtime binary changed during tests')
            print(json.dumps({'gate': label, 'status': 'PASS', 'race_detector': True,
                              'cache_unchanged_during_runtime': True, **summary}), flush=True)
    print('PASS: synthetic Linux archive/bridge tests, CLI interoperability, independent overlays and race detector. No mobile runtime claim.')


if __name__ == '__main__':
    main()
