import 'dart:async';
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
  Duration validationTimeout = const Duration(seconds: 5),
}) async {
  if (validationTimeout <= Duration.zero ||
      validationTimeout > const Duration(seconds: 5))
    throw const FixtureScriptFailure('invalid_verifier_timeout');
  final path =
      explicit ??
      (environment ?? Platform.environment)['WAINAK_IDENTITY_FIXTURE_SCRIPT'];
  if (path == null || path.isEmpty)
    throw const FixtureScriptFailure('explicit_fixture_script_required');
  if (path.length > 4096 ||
      !path.startsWith('/') ||
      path.contains('\x00') ||
      path.contains('\n') ||
      path.contains('\r') ||
      !path.endsWith('/serve_identity_fixture.py')) {
    throw const FixtureScriptFailure('invalid_fixture_script_path');
  }
  Process? probe;
  var exited = false;
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
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as f:
  s=os.fstat(f.fileno())
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o022 or s.st_size>1048576: raise ValueError()
  digest=hashlib.sha256(f.read(1048577)).hexdigest()
 print(json.dumps({'script':p,'sha256':digest}))
except Exception:
 sys.exit(2)
''';
    probe = await Process.start(
      '/usr/bin/python3',
      ['-c', verifier, path],
      includeParentEnvironment: false,
      environment: const {
        'PATH': '/usr/bin:/bin',
        'LANG': 'C.UTF-8',
        'PYTHONDONTWRITEBYTECODE': '1',
      },
    );
    final values = await Future.wait<Object>([
      probe.exitCode.then((code) {
        exited = true;
        return code;
      }),
      _boundedVerifierOutput(probe.stdout),
      _boundedVerifierOutput(probe.stderr),
    ], eagerError: true).timeout(validationTimeout);
    if (values[0] != 0 || (values[2] as String).isNotEmpty)
      throw const FixtureScriptFailure('fixture_ownership_or_mode_rejected');
    final data = jsonDecode(values[1] as String);
    if (data is! Map ||
        data['script'] != path ||
        data['sha256'] is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(data['sha256'] as String))
      throw const FixtureScriptFailure('invalid_fixture_provenance');
    return FixtureScriptSelection(path, data['sha256'] as String);
  } on FixtureScriptFailure {
    rethrow;
  } on TimeoutException {
    throw const FixtureScriptFailure('fixture_verifier_timeout');
  } catch (_) {
    throw const FixtureScriptFailure('fixture_validation_failed');
  } finally {
    final active = probe;
    if (active != null && !exited) {
      // Only this short-lived metadata verifier: never the DB-owning fixture.
      active.kill(ProcessSignal.sigterm);
      try {
        await active.exitCode.timeout(const Duration(seconds: 2));
      } on TimeoutException {
        active.kill(ProcessSignal.sigkill);
        try {
          await active.exitCode.timeout(const Duration(seconds: 2));
        } on TimeoutException {
          throw const FixtureScriptFailure(
            'fixture_verifier_cleanup_unverified',
          );
        }
      }
    }
  }
}

Future<String> _boundedVerifierOutput(Stream<List<int>> stream) async {
  final bytes = <int>[];
  await for (final chunk in stream) {
    if (bytes.length + chunk.length > 32768)
      throw const FixtureScriptFailure('fixture_verifier_output_limit');
    bytes.addAll(chunk);
  }
  return utf8.decode(bytes);
}
