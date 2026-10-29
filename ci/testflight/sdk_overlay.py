"""Reviewed analyzer-only source overlay; never modify the provider's Flutter SDK."""
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
    return manifest, helper


def patch_source(before):
    manifest, helper = delta()
    p.require(digest(before) == manifest['before_sha256'] and before.count(OLD.encode()) == 1, 'sdk_delta_before')
    after = before.replace(OLD.encode(), NEW.encode()) + b'\n' + helper
    p.require(digest(after) == manifest['after_sha256'], 'sdk_delta_after')
    return after


def inventory(raw):
    result = {}
    for entry in raw.split('\0'):
        if not entry:continue
        meta, name = entry.split('\t')
        mode, kind, oid = meta.split()
        path = PurePosixPath(name)
        p.require(mode in {'100644', '100755'} and kind == 'blob' and len(oid) == 40 and
                  all(c in '0123456789abcdef' for c in oid), 'sdk_inventory_entry')
        p.require(not path.is_absolute() and '..' not in path.parts and str(path) == name and
                  name not in result and any(name == x or name.startswith(x+'/') for x in SOURCE_PATHS), 'sdk_inventory_path')
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


class Overlay:
    def __init__(self, base, destination, entries, baseline, config_bytes, files):
        self.base, self.destination, self.entries = base, destination, entries
        self.baseline, self.config_bytes, self.files = baseline, config_bytes, files

    def verify(self):
        p.require(snapshot(self.base, self.entries) == self.baseline, 'sdk_base_changed')
        p.require(read_regular(self.base/'packages/flutter_tools/.dart_tool/package_config.json') == self.config_bytes,
                  'sdk_package_config_changed')
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
                'provider_sdk_modified': False, 'execution': 'dart_source_no_cached_tool_snapshot'}


def prepare(work, run):
    manifest, _ = delta()
    executable = shutil.which('flutter')
    p.require(executable is not None, 'sdk_flutter_missing')
    base = Path(executable).resolve().parent.parent
    head = run('sdk_head', ['git', 'rev-parse', 'HEAD'], cwd=base).strip()
    p.require(head == manifest['framework_revision'], 'sdk_source_revision')
    entries = inventory(run('sdk_inventory', ['git', 'ls-tree', '-rz', 'HEAD', '--', *SOURCE_PATHS], cwd=base))
    baseline = snapshot(base, entries)
    destination = work/'analyzer_overlay'
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
    config_path = base/'packages/flutter_tools/.dart_tool/package_config.json'
    raw = read_regular(config_path)
    config = package_config(raw, config_path, destination/'flutter_tools')
    (destination/'package_config.json').write_bytes(config)
    files['package_config.json'] = digest(config)
    result = Overlay(base, destination, entries, baseline, raw, files)
    result.verify()
    return result
