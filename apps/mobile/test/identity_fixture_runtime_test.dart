import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import '../tool/identity_fixture_runtime.dart';

void main() {
  late Directory root;
  late String fixtureHome;
  setUp(() async {
    root = await Directory.systemTemp.createTemp('wainak-fixture-runtime-');
    fixtureHome = (await Directory('${root.path}/home').create()).path;
    final permission = await Process.run('/usr/bin/chmod', [
      '0700',
      fixtureHome,
    ]);
    expect(permission.exitCode, 0);
  });
  tearDown(() => root.delete(recursive: true));

  FixtureRuntimeSelection select({String? python, String? home}) =>
      resolveFixtureRuntime(
        python: python ?? '/usr/bin/python3',
        home: home ?? fixtureHome,
        environment: const {},
      );

  test('missing explicit runtime has no host-specific fallback', () {
    expect(
      () => resolveFixtureRuntime(environment: const {}),
      throwsA(isA<FixtureRuntimeFailure>()),
    );
    expect(
      () => resolveFixtureRuntime(
        python: '/usr/bin/python3',
        environment: const {},
      ),
      throwsA(isA<FixtureRuntimeFailure>()),
    );
  });
  test('explicit and environment runtime selections are portable', () {
    final fromEnvironment = resolveFixtureRuntime(
      environment: {
        'WAINAK_IDENTITY_FIXTURE_PYTHON': '/usr/bin/python3',
        'WAINAK_IDENTITY_FIXTURE_HOME': fixtureHome,
      },
    );
    expect(fromEnvironment.python, '/usr/bin/python3');
    expect(fromEnvironment.home, fixtureHome);
    final explicit = resolveFixtureRuntime(
      python: '/usr/bin/python3',
      home: fixtureHome,
      environment: const {
        'WAINAK_IDENTITY_FIXTURE_PYTHON': 'invalid',
        'WAINAK_IDENTITY_FIXTURE_HOME': 'invalid',
      },
    );
    expect(explicit.home, fixtureHome);
  });
  test('relative and control-character runtime paths are rejected', () {
    for (final value in ['python3', '/tmp/tool\nsecret', '/tmp/tool\x00']) {
      expect(
        () => select(python: value),
        throwsA(isA<FixtureRuntimeFailure>()),
      );
      expect(() => select(home: value), throwsA(isA<FixtureRuntimeFailure>()));
    }
  });
  test(
    'missing directory and non-executable interpreter are rejected',
    () async {
      final noExecutable = await File(
        '${root.path}/not-python',
      ).writeAsString('');
      await Process.run('/usr/bin/chmod', ['0600', noExecutable.path]);
      expect(
        () => select(python: noExecutable.path),
        throwsA(isA<FixtureRuntimeFailure>()),
      );
      expect(
        () => select(python: root.path),
        throwsA(isA<FixtureRuntimeFailure>()),
      );
      expect(
        () => select(home: '${root.path}/missing'),
        throwsA(isA<FixtureRuntimeFailure>()),
      );
    },
  );
  test('private home cannot be a symlink or shared directory', () async {
    final link = await Link('${root.path}/alias').create(fixtureHome);
    expect(
      () => select(home: link.path),
      throwsA(isA<FixtureRuntimeFailure>()),
    );
    for (final mode in ['0755', '0600']) {
      await Process.run('/usr/bin/chmod', [mode, fixtureHome]);
      expect(() => select(), throwsA(isA<FixtureRuntimeFailure>()));
    }
    await Process.run('/usr/bin/chmod', ['0700', fixtureHome]);
  });
  test('interpreter symlink retains venv selection path', () async {
    final link = await Link(
      '${root.path}/venv-python',
    ).create('/usr/bin/python3');
    expect(select(python: link.path).python, link.path);
  });
  test('child environment excludes credentials and import overrides', () {
    final selected = resolveFixtureRuntime(
      environment: {
        'WAINAK_IDENTITY_FIXTURE_PYTHON': '/usr/bin/python3',
        'WAINAK_IDENTITY_FIXTURE_HOME': fixtureHome,
        'SYNTHETIC_PARENT_SECRET': 'must-not-be-forwarded',
        'PYTHONPATH': '/untrusted-path',
        'HOME': '/unrelated-home',
        'DOCKER_HOST': 'tcp://unrelated.invalid:2375',
      },
    );
    expect(selected.childEnvironment.keys.toSet(), {
      'HOME',
      'PATH',
      'LANG',
      'PYTHONDONTWRITEBYTECODE',
      'PYTHONUNBUFFERED',
      'PYTHONNOUSERSITE',
    });
    expect(selected.childEnvironment['HOME'], fixtureHome);
    expect(
      () => selected.childEnvironment['EXTRA'] = 'value',
      throwsUnsupportedError,
    );
  });
  test('real child receives only the selected sandbox environment', () async {
    final selected = select();
    final child = await Process.run(
      selected.python,
      [
        '-c',
        'import json,os; print(json.dumps({"home_matches":os.path.isdir(os.environ["HOME"]),"no_pythonpath":"PYTHONPATH" not in os.environ,"no_parent_secret":"SYNTHETIC_PARENT_SECRET" not in os.environ,"no_user_site":os.environ.get("PYTHONNOUSERSITE")=="1"}))',
      ],
      includeParentEnvironment: false,
      environment: selected.childEnvironment,
    );
    expect(child.exitCode, 0);
    expect(child.stderr, isEmpty);
    expect(jsonDecode(child.stdout as String), {
      'home_matches': true,
      'no_pythonpath': true,
      'no_parent_secret': true,
      'no_user_site': true,
    });
  });
  test('runtime rejection does not echo the supplied private path', () {
    try {
      select(python: '/private-path-that-does-not-exist');
      fail('Expected rejection');
    } on FixtureRuntimeFailure catch (error) {
      expect(error.toString(), isNot(contains('private-path')));
    }
  });
}
