import 'dart:convert';
import 'dart:io';

class FixtureScriptFailure implements Exception {
  const FixtureScriptFailure(this.code);
  final String code;
  @override
  String toString() => 'FixtureScriptFailure($code)';
}

class FixtureScriptSelection {
  const FixtureScriptSelection(this.path, this.sha256);
  final String path, sha256;
  Map<String, String> get provenance => {'script': path, 'sha256': sha256};
}

/// Test capability only, never imported by lib/. No default checkout fallback.
/// Metadata probe does not import or execute the selected script or start a DB.
Future<FixtureScriptSelection> resolveFixtureScript({
  String? explicit,
  Map<String, String>? environment,
}) async {
  final path =
      explicit ??
      (environment ?? Platform.environment)['WAINAK_IDENTITY_FIXTURE_SCRIPT'];
  if (path == null || path.isEmpty)
    throw const FixtureScriptFailure('explicit_fixture_script_required');
  if (!path.startsWith('/') ||
      path.contains('\x00') ||
      path.contains('\n') ||
      path.contains('\r') ||
      !path.endsWith('/serve_identity_fixture.py')) {
    throw const FixtureScriptFailure('invalid_fixture_script_path');
  }
  try {
    if (FileSystemEntity.typeSync(path, followLinks: false) !=
            FileSystemEntityType.file ||
        File(path).resolveSymbolicLinksSync() != path) {
      throw const FixtureScriptFailure(
        'fixture_must_be_regular_canonical_file',
      );
    }
    // Fixed local verifier uses the current OS UID and one no-follow descriptor.
    // Path and hash are nonsecret provenance; no mailbox/session material exists.
    const verifier = r'''
import os,sys,stat,hashlib,json
try:
 p=sys.argv[1]
 if os.path.realpath(p)!=p: raise ValueError()
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as f:
  s=os.fstat(f.fileno())
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o022 or s.st_size>1048576: raise ValueError()
  digest=hashlib.sha256(f.read(1048577)).hexdigest()
 print(json.dumps({'script':p,'sha256':digest}))
except Exception:
 sys.exit(2)
''';
    final result = await Process.run(
      '/usr/bin/python3',
      ['-c', verifier, path],
      includeParentEnvironment: false,
      environment: const {
        'PATH': '/usr/bin:/bin',
        'LANG': 'C.UTF-8',
        'PYTHONDONTWRITEBYTECODE': '1',
      },
    ).timeout(const Duration(seconds: 5));
    if (result.exitCode != 0 || (result.stderr as String).isNotEmpty)
      throw const FixtureScriptFailure('fixture_ownership_or_mode_rejected');
    final data = jsonDecode(result.stdout as String);
    if (data is! Map ||
        data['script'] != path ||
        data['sha256'] is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(data['sha256'] as String))
      throw const FixtureScriptFailure('invalid_fixture_provenance');
    return FixtureScriptSelection(path, data['sha256'] as String);
  } on FixtureScriptFailure {
    rethrow;
  } catch (_) {
    throw const FixtureScriptFailure('fixture_validation_failed');
  }
}
