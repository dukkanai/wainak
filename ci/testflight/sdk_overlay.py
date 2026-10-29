"""Reviewed analyzer-only source overlay; never modify the provider's Flutter SDK."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import re
from urllib.parse import urljoin, urlparse, unquote

from ci.testflight import policy as p

ROOT = Path(__file__).resolve().parents[2]
DELTA = ROOT/'ci/testflight/sdk_delta'
SOURCE_PATHS = ('packages/flutter_tools', 'bin/internal', 'bin/flutter', 'bin/dart', '.gitattributes')
TARGET = 'packages/flutter_tools/lib/src/dart/analysis.dart'
OLD = '''  Future<bool?> dispose() async {
    await _analyzingController.close();
    await _errorsController.close();
    return _process?.kill();
  }
'''
NEW = '''  Future<bool?> dispose() async {
    final process = _process;
    try {
      await _analyzingController.close();
      await _errorsController.close();
    } finally {
      if (process != null) {
        await stopAnalysisServerOwnedProcess(process);
      }
    }
    return process == null ? null : true;
  }
'''


SAFE_POLICY_REASONS = frozenset({
    'sdk_base_changed', 'sdk_delta_after', 'sdk_delta_base',
    'sdk_delta_before', 'sdk_delta_helper', 'sdk_delta_lock_archive',
    'sdk_delta_method', 'sdk_delta_schema', 'sdk_existing_overlay',
    'sdk_flutter_missing', 'sdk_generated_config_missing', 'sdk_generated_file',
    'sdk_generated_role', 'sdk_git_attributes', 'sdk_inventory_case_collision',
    'sdk_inventory_entry', 'sdk_inventory_incomplete', 'sdk_inventory_path',
    'sdk_overlay_drift', 'sdk_overlay_inventory', 'sdk_overlay_symlink',
    'sdk_package_config', 'sdk_package_config_changed', 'sdk_package_duplicate',
    'sdk_package_graph_changed', 'sdk_package_library', 'sdk_package_missing_tool',
    'sdk_package_tool_root', 'sdk_package_uri', 'sdk_package_version_changed',
    'sdk_regular_file', 'sdk_source_drift', 'sdk_source_revision',
    'sdk_source_symlink', 'sdk_stage_identity', 'sdk_tool_lock_changed',
    'sdk_tool_lock_hash', 'sdk_tool_lock_missing',
})
STAGES=frozenset({"source_inventory","source_snapshot","provider_dependencies","source_copy","tool_dependencies","package_config","final_verification"})


def safe_reason(error):
    reason=error.args[0] if isinstance(error,p.PolicyError) and error.args else None
    return reason if type(reason) is str and reason in SAFE_POLICY_REASONS else "OTHER"


@contextmanager
def step(stage):
    p.require(stage in STAGES, "sdk_stage_identity")
    print(json.dumps({"event":"SDK_OVERLAY_STAGE","stage":stage,"outcome":"START"}),flush=True)
    try:
        yield
    except BaseException as error:
        print(json.dumps({"event":"SDK_OVERLAY_STAGE","stage":stage,"outcome":"FAILED",
            "safe_reason":safe_reason(error)}),flush=True)
        raise
    else:
        print(json.dumps({"event":"SDK_OVERLAY_STAGE","stage":stage,"outcome":"PASS"}),flush=True)


def digest(data):return hashlib.sha256(data).hexdigest()


def read_regular(path, maximum=8*1024*1024):
    p.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum, 'sdk_regular_file')
    return path.read_bytes()


def delta():
    manifest = json.loads(read_regular(DELTA/'manifest.json'))
    p.require(manifest.get('schema') == 1 and manifest.get('term_timeout_seconds') == 5 and
              manifest.get('kill_timeout_seconds') == 2, 'sdk_delta_schema')
    helper = read_regular(DELTA/'stop_analysis_server.dart.txt')
    p.require(digest(helper) == manifest['helper_sha256'], 'sdk_delta_helper')
    p.require(digest(OLD.encode()) == manifest['old_method_sha256'] and
              digest(NEW.encode()) == manifest['new_method_sha256'], 'sdk_delta_method')
    pins = json.loads((ROOT/'ci/ios-host-pins.json').read_text())
    p.require(manifest['framework_revision'] == pins['flutter']['framework_revision'] and
              manifest['target'] == TARGET, 'sdk_delta_base')
    p.require(manifest['tool_lock_archive_sha256'] == pins['flutter']['archive_sha256'], 'sdk_delta_lock_archive')
    return manifest, helper


def patch_source(before):
    manifest, helper = delta()
    p.require(digest(before) == manifest['before_sha256'] and before.count(OLD.encode()) == 1, 'sdk_delta_before')
    after = before.replace(OLD.encode(), NEW.encode()) + b'\n' + helper
    p.require(digest(after) == manifest['after_sha256'], 'sdk_delta_after')
    return after


def inventory(raw):
    result = {}
    folded = set()
    for entry in raw.split('\0'):
        if not entry:continue
        meta, name = entry.split('\t')
        mode, kind, oid = meta.split()
        path = PurePosixPath(name)
        p.require(mode in {'100644', '100755'} and kind == 'blob' and len(oid) == 40 and
                  all(c in '0123456789abcdef' for c in oid), 'sdk_inventory_entry')
        p.require(not path.is_absolute() and '..' not in path.parts and str(path) == name and
                  name not in result and any(name == x or name.startswith(x+'/') for x in SOURCE_PATHS), 'sdk_inventory_path')
        p.require(name.casefold() not in folded, 'sdk_inventory_case_collision')
        folded.add(name.casefold())
        result[name] = oid
    p.require(TARGET in result and 'packages/flutter_tools/bin/flutter_tools.dart' in result and
              'packages/flutter_tools/pubspec.yaml' in result, 'sdk_inventory_incomplete')
    return result


def snapshot(base, entries):
    result = {}
    for name, oid in entries.items():
        path = base/name
        p.require(path.resolve().is_relative_to(base) and not any(
            parent.is_symlink() for parent in path.parents if parent != base and parent.is_relative_to(base)), 'sdk_source_symlink')
        data = read_regular(path)
        canonical = data
        # Git explicitly checks these Windows scripts out as CRLF. Verify the
        # pinned attributes too; preserve their actual bytes in the baseline.
        suffix = path.suffix
        if suffix in {'.bat', '.ps1'}:
            attributes = read_regular(base/'.gitattributes').decode()
            p.require(re.search(r'^\*'+re.escape(suffix)+r'\s+text eol=crlf$', attributes, re.M) is not None,
                      'sdk_git_attributes')
            canonical = data.replace(b'\r\n', b'\n')
        p.require(hashlib.sha1(b'blob '+str(len(canonical)).encode()+b'\0'+canonical).hexdigest() == oid, 'sdk_source_drift')
        result[name] = digest(data)
    return result


def package_config(raw, original, package_root):
    config = json.loads(raw)
    p.require(config.get('configVersion') == 2 and type(config.get('packages')) is list, 'sdk_package_config')
    seen = set()
    for entry in config['packages']:
        p.require(type(entry) is dict and entry.get('packageUri', 'lib/') == 'lib/', 'sdk_package_library')
        name = entry['name']
        p.require(type(name) is str and name not in seen, 'sdk_package_duplicate')
        seen.add(name)
        uri = urljoin(original.as_uri(), entry['rootUri'])
        parsed = urlparse(uri)
        p.require(parsed.scheme == 'file' and not parsed.netloc and not parsed.query and not parsed.fragment, 'sdk_package_uri')
        resolved = Path(unquote(parsed.path)).resolve()
        if name == 'flutter_tools':
            p.require(resolved == original.parent.parent, 'sdk_package_tool_root')
            uri = package_root.as_uri()+'/'
        entry['rootUri'] = uri
    p.require('flutter_tools' in seen, 'sdk_package_missing_tool')
    return (json.dumps(config, sort_keys=True)+'\n').encode()


def optional_generated(path):
    return read_regular(path) if path.exists() or path.is_symlink() else None


def bytes_fingerprint(data):
    return {'state':'absent' if data is None else 'regular',
            'sha256':None if data is None else digest(data),'bytes':None if data is None else len(data)}


def generated_matches(path, expected, role):
    p.require(role in {'provider_package_config','provider_package_graph','provider_version'},'sdk_generated_role')
    actual=None
    try:
        if path.is_symlink():info={'state':'symlink','sha256':None,'bytes':None}
        else:
            actual=optional_generated(path)
            info=bytes_fingerprint(actual)
    except (OSError,p.PolicyError):info={'state':'unreadable','sha256':None,'bytes':None}
    matches=info['state'] in {'absent','regular'} and actual==expected
    if not matches:
        print(json.dumps({'event':'SDK_GENERATED_FILE_CHECK','file_role':role,'outcome':'FAILED',
              'expected':bytes_fingerprint(expected),'actual':info}),flush=True)
    return matches


class Overlay:
    def __init__(self, base, destination, entries, baseline, config_bytes, files, *, graph_bytes=None, version_bytes=None, initial_config_bytes=None):
        self.base, self.destination, self.entries = base, destination, entries
        self.baseline, self.config_bytes, self.files = baseline, config_bytes, files
        self.graph_bytes, self.version_bytes, self.initial_config_bytes = graph_bytes, version_bytes, initial_config_bytes

    def verify(self):
        p.require(snapshot(self.base, self.entries) == self.baseline, 'sdk_base_changed')
        generated=self.base/'packages/flutter_tools/.dart_tool'
        p.require(generated_matches(generated/'package_config.json',self.config_bytes,'provider_package_config'),'sdk_package_config_changed')
        p.require(generated_matches(generated/'package_graph.json',self.graph_bytes,'provider_package_graph'),'sdk_package_graph_changed')
        p.require(generated_matches(generated/'version',self.version_bytes,'provider_version'),'sdk_package_version_changed')
        p.require(digest(read_regular(self.base/'packages/flutter_tools/pubspec.lock')) == delta()[0]['tool_pubspec_lock_sha256'],
                  'sdk_tool_lock_hash')
        found = set()
        for path in self.destination.rglob('*'):
            p.require(not path.is_symlink(), 'sdk_overlay_symlink')
            if path.is_dir():continue
            name = path.relative_to(self.destination).as_posix()
            p.require(name in self.files and digest(read_regular(path)) == self.files[name], 'sdk_overlay_drift')
            found.add(name)
        p.require(found == set(self.files), 'sdk_overlay_inventory')

    def command(self):
        return [self.base/'bin/cache/dart-sdk/bin/dart', '--disable-dart-dev',
                '--packages='+str(self.destination/'package_config.json'),
                self.destination/'flutter_tools/bin/flutter_tools.dart', 'analyze', '--no-pub']

    def report(self):
        manifest, _ = delta()
        return {'event': 'TESTFLIGHT_SDK_DELTA', 'scope': 'analyze_only',
                'base_revision': manifest['framework_revision'], 'before_sha256': manifest['before_sha256'],
                'after_sha256': manifest['after_sha256'], 'helper_sha256': manifest['helper_sha256'],
                'base_source_inventory_sha256': digest(json.dumps(self.baseline, sort_keys=True).encode()),
                'provider_sdk_source_modified': False, 'provider_dependencies_initialized': True,
                'provider_config_before': bytes_fingerprint(self.initial_config_bytes),
                'provider_config_baseline': bytes_fingerprint(self.config_bytes),
                'provider_package_config_present': self.config_bytes is not None,
                'tool_pubspec_lock_sha256':manifest['tool_pubspec_lock_sha256'], 'execution': 'dart_source_no_cached_tool_snapshot'}


def prepare(work, run):
    manifest, _ = delta()
    with step('source_inventory'):
        executable = shutil.which('flutter')
        p.require(executable is not None, 'sdk_flutter_missing')
        base = Path(executable).resolve().parent.parent
        head = run('sdk_head', ['git', 'rev-parse', 'HEAD'], cwd=base).strip()
        p.require(head == manifest['framework_revision'], 'sdk_source_revision')
        entries = inventory(run('sdk_inventory', ['git', 'ls-tree', '-rz', 'HEAD', '--', *SOURCE_PATHS], cwd=base))
    with step('source_snapshot'):
        baseline = snapshot(base, entries)
        lock_path=base/'packages/flutter_tools/pubspec.lock'
        p.require(lock_path.is_file() and not lock_path.is_symlink(),'sdk_tool_lock_missing')
        lock=read_regular(lock_path)
        p.require(digest(lock)==manifest['tool_pubspec_lock_sha256'],'sdk_tool_lock_hash')
        original_config=base/'packages/flutter_tools/.dart_tool/package_config.json'
        initial_raw=optional_generated(original_config)
    with step('provider_dependencies'):
        # Flutter's universal cache initializes these lazily during pub get.
        # Initialize explicitly with the pinned lock and the SAME child cache,
        # validate source/lock, then freeze generated bytes. Never rebaseline later.
        run('sdk_provider_dependencies',[base/'bin/cache/dart-sdk/bin/dart','pub','get','--enforce-lockfile','--no-precompile'],
            cwd=base/'packages/flutter_tools')
        p.require(snapshot(base,entries)==baseline,'sdk_base_changed')
        p.require(read_regular(lock_path)==lock,'sdk_tool_lock_changed')
        raw=read_regular(original_config)
        package_config(raw,original_config,base/'packages/flutter_tools')
        graph=read_regular(original_config.parent/'package_graph.json')
        version=optional_generated(original_config.parent/'version')
    destination = work/'analyzer_overlay'
    with step('source_copy'):
        p.require(not destination.exists() and not destination.is_symlink(), 'sdk_existing_overlay')
        destination.mkdir(mode=0o700)
        files = {}
        for name in entries:
            if not name.startswith('packages/flutter_tools/'):continue
            target = destination/'flutter_tools'/name.removeprefix('packages/flutter_tools/')
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            data = read_regular(base/name)
            if name == TARGET:data = patch_source(data)
            target.write_bytes(data)
            files[target.relative_to(destination).as_posix()] = digest(data)
        copied_lock=destination/'flutter_tools/pubspec.lock'
        copied_lock.write_bytes(lock)
        files['flutter_tools/pubspec.lock']=digest(lock)
    with step('tool_dependencies'):
        run('sdk_dependencies',[base/'bin/cache/dart-sdk/bin/dart','pub','get','--enforce-lockfile','--no-precompile'],
            cwd=destination/'flutter_tools')
        p.require(read_regular(copied_lock)==lock,'sdk_tool_lock_changed')
        p.require(snapshot(base,entries)==baseline,'sdk_base_changed')
    with step('package_config'):
        generated=destination/'flutter_tools/.dart_tool/package_config.json'
        p.require(generated.is_file() and not generated.is_symlink(),'sdk_generated_config_missing')
        for name in ('package_config.json','package_graph.json'):
            file=generated.parent/name
            p.require(file.is_file() and not file.is_symlink(),'sdk_generated_file')
            files[file.relative_to(destination).as_posix()]=digest(read_regular(file))
        config=package_config(read_regular(generated),generated,destination/'flutter_tools')
        (destination/'package_config.json').write_bytes(config)
        files['package_config.json']=digest(config)
    with step('final_verification'):
        result = Overlay(base, destination, entries, baseline, raw, files, graph_bytes=graph, version_bytes=version, initial_config_bytes=initial_raw)
        result.verify()
    return result
