import 'dart:io';

class FixtureRuntimeFailure implements Exception {
  const FixtureRuntimeFailure(this.code);
  final String code;
  @override
  String toString() => 'FixtureRuntimeFailure($code)';
}

/// Operator-selected test tools only; never imported by application lib/.
/// A Python venv commonly uses an interpreter symlink, so retain its selected
/// path rather than resolving it and accidentally bypassing the venv.
class FixtureRuntimeSelection {
  const FixtureRuntimeSelection(this.python, this.home);
  final String python, home;

  /// Deliberately excludes the parent environment, including credential and
  /// Python import-path variables. HOME belongs only to this test child.
  Map<String, String> get childEnvironment => Map.unmodifiable({
    'HOME': home,
    'PATH': '/usr/bin:/bin',
    'LANG': 'C.UTF-8',
    'PYTHONDONTWRITEBYTECODE': '1',
    'PYTHONUNBUFFERED': '1',
    'PYTHONNOUSERSITE': '1',
  });
}

String _absolutePath(String? value, String label) {
  if (value == null || value.isEmpty) {
    throw FixtureRuntimeFailure('explicit_fixture_${label}_required');
  }
  if (value.length > 4096 ||
      !value.startsWith('/') ||
      value.contains('\x00') ||
      value.contains('\n') ||
      value.contains('\r')) {
    throw FixtureRuntimeFailure('invalid_fixture_${label}_path');
  }
  return value;
}

FixtureRuntimeSelection resolveFixtureRuntime({
  String? python,
  String? home,
  Map<String, String>? environment,
}) {
  final selectedEnvironment = environment ?? Platform.environment;
  final selectedPython = _absolutePath(
    python ?? selectedEnvironment['WAINEK_IDENTITY_FIXTURE_PYTHON'],
    'python',
  );
  final selectedHome = _absolutePath(
    home ?? selectedEnvironment['WAINEK_IDENTITY_FIXTURE_HOME'],
    'home',
  );
  try {
    final interpreter = File(selectedPython).statSync();
    if (interpreter.type != FileSystemEntityType.file ||
        (interpreter.mode & 0x49) == 0) {
      throw const FixtureRuntimeFailure('fixture_python_not_executable');
    }
    final directory = Directory(selectedHome);
    final metadata = directory.statSync();
    if (FileSystemEntity.typeSync(selectedHome, followLinks: false) !=
            FileSystemEntityType.directory ||
        directory.resolveSymbolicLinksSync() != selectedHome ||
        (metadata.mode & 0x1ff) != 0x1c0) {
      throw const FixtureRuntimeFailure('fixture_home_not_private_canonical');
    }
  } on FixtureRuntimeFailure {
    rethrow;
  } catch (_) {
    throw const FixtureRuntimeFailure('fixture_runtime_validation_failed');
  }
  return FixtureRuntimeSelection(selectedPython, selectedHome);
}
