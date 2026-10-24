"""Bounded independent Go overlay checks, no native/JNI acceptance inference."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path('/home/chatbot/wainak-dev/archive-tools-phase5-20261024')
CORE = '8155772cf0a006078be433f45353c651d9ffe451'

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def manifest(root, commit):
    if git(root, 'rev-parse', 'HEAD') != commit or git(root, 'status', '--porcelain'):
        raise RuntimeError('clean exact candidate required')
    result = {}
    for name in git(root, 'ls-files').splitlines():
        p = root / name
        if p.is_symlink() or not p.is_file():
            raise RuntimeError('regular source required')
        expected = hashlib.sha256(subprocess.check_output(['git', '-C', str(root), 'show', commit + ':' + name])).hexdigest()
        if sha(p) != expected:
            raise RuntimeError('source blob mismatch')
        result[name] = expected
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate-root', required=True, type=Path)
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--evidence', required=True, type=Path)
    ap.add_argument('--run-synthetic-bridge', action='store_true')
    args = ap.parse_args()
    if not args.run_synthetic_bridge or not re.fullmatch('[0-9a-f]{40}', args.candidate):
        raise RuntimeError('explicit synthetic candidate required')
    if args.candidate_root.is_symlink() or args.candidate_root.stat().st_uid != os.getuid():
        raise RuntimeError('owned candidate required')
    candidate = args.candidate_root.resolve()
    qa_head = git(ROOT, 'rev-parse', 'HEAD')
    qa_before = manifest(ROOT, qa_head)
    before = manifest(candidate, args.candidate)
    core_names = git(candidate, 'ls-tree', '-r', '--name-only', CORE, 'archive').splitlines()
    if len(core_names) != 24:
        raise RuntimeError('core scope changed')
    for name in core_names:
        if (candidate / name).read_bytes() != subprocess.check_output(['git', '-C', str(candidate), 'show', CORE + ':' + name]):
            raise RuntimeError('core changed')
    mem = {k: int(v.split()[0]) for k, v in (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())}
    if mem['MemAvailable'] < int(4.5 * 1024 * 1024):
        raise RuntimeError('resource margin')
    if Path('/sys/fs/cgroup/system.slice/onwani-server-admin.service/memory.max').read_text().strip() != '4294967296':
        raise RuntimeError('owner limit changed')
    if not args.evidence.is_dir() or args.evidence.is_symlink() or args.evidence.stat().st_uid != os.getuid():
        raise RuntimeError('owned evidence required')
    resultfile = args.evidence / 'independent-bridge-results.json'
    if resultfile.exists():
        raise RuntimeError('existing evidence cannot be overwritten')
    spec = importlib.util.spec_from_file_location('bounded_archive_runner', candidate / 'archive/run_checks.py')
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    results = []
    own = ROOT / 'qa/phase6_archive_bridge'
    with tempfile.TemporaryDirectory(prefix='wainak-archive-bridge-qa-', dir=TOOLS / 'tmp') as temp:
        env = {'HOME': str(TOOLS / 'home'), 'PATH': str(TOOLS / 'go/bin') + ':/usr/bin:/bin', 'GOPATH': str(TOOLS / 'gopath'), 'GOCACHE': str(TOOLS / 'gocache'), 'GOMODCACHE': str(TOOLS / 'gomodcache'), 'TMPDIR': temp, 'GOENV': 'off', 'GOTOOLCHAIN': 'local', 'GOTELEMETRY': 'off', 'CGO_ENABLED': '0', 'GOFLAGS': '-p=1 -mod=readonly', 'GOMAXPROCS': '2', 'GOMEMLIMIT': '512MiB', 'GOPROXY': 'off', 'GOSUMDB': 'off', 'PYTHONDONTWRITEBYTECODE': '1'}
        go = str(TOOLS / 'go/bin/go')
        cwd = candidate / 'archivebridge'
        code, out, _ = base.bounded_run([go, 'list', '-m', '-json', 'wainak.local/historyarchive'], cwd, env)
        if code or Path(json.loads(out)['Dir']).resolve() != (candidate / 'archive').resolve():
            raise RuntimeError('core import provenance mismatch')
        overlay = Path(temp) / 'overlay.json'
        overlay.write_text(json.dumps({'Replace': {str(cwd / 'qa_independent_test.go'): str(own / 'bridge_independent_test.go.txt')}}))
        commands = [
            ('independent_bridge', [go, 'test', '-json', '-count=1', '-parallel=1', '-timeout=90s', '-overlay=' + str(overlay), '-run=^TestQA', './...'], cwd),
            ('independent_vet', [go, 'vet', '-overlay=' + str(overlay), './...'], cwd),
            ('publication', ['python3', 'scripts/check_publication.py'], ROOT),
        ]
        for label, command, location in commands:
            code, out, seconds = base.bounded_run(command, location, env, timeout=150)
            item = {'gate': label, 'exit_code': code, 'seconds': seconds}
            if label == 'independent_bridge':
                events = []
                diagnostics = []
                for line in out.splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get('Action') in ('pass', 'fail', 'skip') and event.get('Test'):
                        name = event['Test']
                        events.append({'action': event['Action'], 'test': name if re.fullmatch('[A-Za-z0-9_./-]{1,200}', name) else 'nonstandard_name'})
                    # QA assertions contain only fixed labels, but raw compiler
                    # and test output is deliberately not persisted or forwarded.
                item['tests'] = events
                if not any(e['test'].startswith('TestQA') for e in events):
                    code = 1
                    item['exit_code'] = 1
            results.append(item)
            print(json.dumps(item, sort_keys=True), flush=True)
            if code:
                resultfile.write_text(json.dumps({'status': 'FAIL', 'candidate': args.candidate, 'qa_head': qa_head, 'results': results}, indent=2) + '\n')
                raise RuntimeError('independent gate incomplete; raw output withheld')
    if Path(temp).exists():
        raise RuntimeError('owned temporary directory remains')
    if before != manifest(candidate, args.candidate) or qa_before != manifest(ROOT, qa_head):
        raise RuntimeError('source changed')
    result = {'status': 'PASS', 'candidate': args.candidate, 'qa_head': qa_head, 'source_files': len(before), 'core_files_unchanged': len(core_names), 'candidate_manifest_sha256': hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(), 'qa_test_sha256': sha(own / 'bridge_independent_test.go.txt'), 'results': results, 'owned_temp_removed': True, 'scope': 'synthetic host Go only; JNI/AAR/APK/device not run'}
    resultfile.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'candidate': args.candidate, 'qa_head': qa_head, 'result_sha256': sha(resultfile)}, sort_keys=True))

if __name__ == '__main__':
    main()
