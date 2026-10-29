import 'dart:io';
import 'identity_fixture_path.dart';

void check(bool condition) {
  if (!condition) throw StateError('fixture selection assertion failed');
}

Future<void> rejected(Future<void> Function() action) async {
  var denied = false;
  try {
    await action();
  } on FixtureScriptFailure {
    denied = true;
  }
  check(denied);
}

Future<void> main() async {
  final root = await Directory.systemTemp.createTemp(
    'wainek-fixture-path-check-',
  );
  var passed = 0;
  try {
    await rejected(() => resolveFixtureScript(environment: {}));
    passed++;
    await rejected(
      () => resolveFixtureScript(
        explicit: 'relative/serve_identity_fixture.py',
        environment: {},
      ),
    );
    passed++;
    final script = File('${root.path}/serve_identity_fixture.py');
    await script.writeAsString('# selection fixture only; never executed\n');
    final selected = await resolveFixtureScript(
      explicit: script.path,
      environment: {'WAINEK_IDENTITY_FIXTURE_SCRIPT': 'invalid'},
    );
    check(selected.path == script.path && selected.sha256.length == 64);
    passed++;
    final fromEnv = await resolveFixtureScript(
      environment: {'WAINEK_IDENTITY_FIXTURE_SCRIPT': script.path},
    );
    check(fromEnv.sha256 == selected.sha256);
    passed++;
    final linkDir = await Directory('${root.path}/alias').create();
    final link = Link('${linkDir.path}/serve_identity_fixture.py');
    await link.create(script.path);
    await rejected(() => resolveFixtureScript(explicit: link.path));
    passed++;
    final directory = await Directory(
      '${root.path}/directory/serve_identity_fixture.py',
    ).create(recursive: true);
    await rejected(() => resolveFixtureScript(explicit: directory.path));
    passed++;
    var timedOut = false;
    try {
      await resolveFixtureScript(
        explicit: script.path,
        validationTimeout: const Duration(microseconds: 1),
      );
    } on FixtureScriptFailure catch (failure) {
      timedOut = failure.code == 'fixture_verifier_timeout';
    }
    check(timedOut);
    passed++;
    final fifoDir = await Directory('${root.path}/fifo').create();
    final fifoPath = '${fifoDir.path}/serve_identity_fixture.py';
    final fifo = await Process.run('/usr/bin/mkfifo', [fifoPath]);
    check(fifo.exitCode == 0);
    await rejected(() => resolveFixtureScript(explicit: fifoPath));
    passed++;
    final mode = await Process.run('/usr/bin/chmod', ['0666', script.path]);
    check(mode.exitCode == 0);
    await rejected(() => resolveFixtureScript(explicit: script.path));
    passed++;
    stdout.writeln(
      'IDENTITY_FIXTURE_SELECTION_CHECKS_PASSED=$passed; no fixture execution or DB',
    );
  } catch (_) {
    stderr.writeln(
      'IDENTITY_FIXTURE_SELECTION_CHECKS_FAILED; details suppressed',
    );
    exitCode = 1;
  } finally {
    await root.delete(recursive: true);
  }
}
