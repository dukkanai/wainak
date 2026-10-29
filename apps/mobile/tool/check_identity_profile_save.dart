import 'dart:async';
import 'dart:io';
import 'package:wainek_mobile/src/identity/client.dart';
import 'package:wainek_mobile/src/identity/profile_save.dart';
import '../test/support/identity_fixture.dart';

void check(bool value, String label) {
  if (!value) throw StateError(label);
}

Map<String, dynamic> profile() => {
  'gender': 'male',
  'country': 'GB',
  'marital_status': 'married',
  'declared_wives': 1,
  'marriage_goal': 'build_family',
  'discoverable': true,
};
Map<String, dynamic> preferences() => {
  'min_age': 27,
  'max_age': 47,
  'countries': ['GB'],
  'marital_statuses': ['single'],
};
Future<IdentityClient> login(IdentityFixture f) async {
  f.verified = true;
  final client = IdentityClient(
    baseUri: Uri.parse('http://127.0.0.1:8089'),
    transport: f,
  );
  await client.login('member@example.invalid', 'SyntheticOnlyPassword!12');
  return client;
}

Future<Map<String, dynamic>> save(IdentityClient c) => saveIdentityProfile(
  c,
  profile: profile(),
  preferences: preferences(),
  isCurrent: () => true,
);
Future<ProfileSaveFailure> failed(Future<Map<String, dynamic>> action) async {
  try {
    await action;
  } on ProfileSaveFailure catch (error) {
    return error;
  }
  throw StateError('expected incomplete save');
}

int calls(IdentityFixture f, String request) =>
    f.calls.where((value) => value == request).length;

Future<void> main() async {
  var count = 0;
  Future<void> test(String name, Future<void> Function() action) async {
    try {
      await action();
      count++;
      stdout.writeln('PASS $name');
    } catch (_) {
      throw StateError('FAIL $name (details suppressed)');
    }
  }

  await test('complete sequence preserves all submitted fields', () async {
    final f = IdentityFixture();
    final actual = await login(f);
    final result = await save(actual);
    check(result['next_question'] is Map, 'assessment');
    check(f.storedProfile?['declared_wives'] == 1, 'marital data');
    check(f.storedPreferences?['countries'][0] == 'GB', 'preference list');
    check(calls(f, 'GET /v1/me') == 0, 'no extra successful readback');
    actual.close();
  });
  await test('failed first write does not start preferences', () async {
    final f = IdentityFixture()..failProfileSaveAt = 'profile';
    final c = await login(f);
    final error = await failed(save(c));
    check(!error.report.profileAcknowledged, 'no acknowledgement');
    check(error.report.profileObserved == false, 'readback mismatch');
    check(calls(f, 'PUT /v1/me/preferences') == 0, 'no second write');
    c.close();
  });
  await test(
    'lost first response reads matching value without claiming acknowledgement',
    () async {
      final f = IdentityFixture()
        ..failProfileSaveAt = 'profile'
        ..applyBeforeFailure = true;
      final c = await login(f);
      final error = await failed(save(c));
      check(
        !error.report.profileAcknowledged &&
            error.report.profileObserved == true,
        'observed not acknowledged',
      );
      check(
        error.message.contains('دون تأكيد نتيجة طلب الكتابة'),
        'honest readback',
      );
      check(
        calls(f, 'PUT /v1/me/preferences') == 0,
        'no automatic continuation',
      );
      c.close();
    },
  );
  await test('second write failure records confirmed first write', () async {
    final f = IdentityFixture()..failProfileSaveAt = 'preferences';
    final c = await login(f);
    final error = await failed(save(c));
    check(
      error.report.profileAcknowledged && !error.report.preferencesAcknowledged,
      'partial',
    );
    check(error.report.preferencesObserved == false, 'missing preferences');
    check(calls(f, 'GET /v1/me/assessment') == 0, 'no question request');
    check(
      calls(f, 'PUT /v1/me/profile') == 1 &&
          calls(f, 'PUT /v1/me/preferences') == 1,
      'no retry',
    );
    c.close();
  });
  await test(
    'lost preferences response stays distinct from acknowledgement',
    () async {
      final f = IdentityFixture()
        ..failProfileSaveAt = 'preferences'
        ..applyBeforeFailure = true;
      final c = await login(f);
      final error = await failed(save(c));
      check(
        error.report.profileAcknowledged &&
            !error.report.preferencesAcknowledged,
        'acknowledgements',
      );
      check(
        error.report.preferencesObserved == true,
        'matching persisted preferences',
      );
      check(error.causeCode == 'network_uncertain', 'uncertain cause retained');
      c.close();
    },
  );
  await test('assessment failure does not deny two confirmed writes', () async {
    final f = IdentityFixture()..failProfileSaveAt = 'assessment';
    final c = await login(f);
    final error = await failed(save(c));
    check(
      error.report.profileAcknowledged && error.report.preferencesAcknowledged,
      'writes confirmed',
    );
    check(
      error.message.contains('لكن لم نؤكد تحميل الأسئلة'),
      'read failure distinct',
    );
    c.close();
  });
  await test(
    'unavailable readback is unknown not failed persistence',
    () async {
      final f = IdentityFixture()
        ..failProfileSaveAt = 'preferences'
        ..failReadback = true;
      final c = await login(f);
      final error = await failed(save(c));
      check(error.report.preferencesObserved == null, 'unknown');
      check(error.report.profileAcknowledged, 'first acknowledgement retained');
      c.close();
    },
  );
  await test('foreign actor readback cannot confirm a save', () async {
    final f = IdentityFixture()
      ..failProfileSaveAt = 'profile'
      ..applyBeforeFailure = true
      ..unrelatedReadback = true;
    final c = await login(f);
    final error = await failed(save(c));
    check(error.report.profileObserved == null, 'foreign identity rejected');
    c.close();
  });
  await test('only an explicit second call retries writes', () async {
    final f = IdentityFixture()..failProfileSaveAt = 'preferences';
    final c = await login(f);
    await failed(save(c));
    check(calls(f, 'PUT /v1/me/profile') == 1, 'initial only');
    f.failProfileSaveAt = null;
    await save(c);
    check(
      calls(f, 'PUT /v1/me/profile') == 2 &&
          calls(f, 'PUT /v1/me/preferences') == 2,
      'explicit retry',
    );
    c.close();
  });
  await test('stale UI stops before sending any writes', () async {
    final f = IdentityFixture();
    final c = await login(f);
    try {
      await saveIdentityProfile(
        c,
        profile: profile(),
        preferences: preferences(),
        isCurrent: () => false,
      );
      throw StateError('stale accepted');
    } on IdentityFailure catch (e) {
      check(e.code == 'stale_response', 'stale code');
    }
    check(calls(f, 'PUT /v1/me/profile') == 0, 'no write');
    c.close();
  });
  await test(
    'session change during first write stops continuation and readback',
    () async {
      final f = IdentityFixture()..holdProfile = true;
      final c = await login(f);
      final pending = save(c).then<Object>((v) => v, onError: (Object e) => e);
      await Future<void>.delayed(Duration.zero);
      c.forgetLocalSession();
      f.pendingProfile!.complete(f.reply(200, {'profile': f.lastProfile}));
      final outcome = await pending;
      check(
        outcome is IdentityFailure && outcome is! ProfileSaveFailure,
        'stale not prior-account partial',
      );
      check(
        calls(f, 'PUT /v1/me/preferences') == 0 && calls(f, 'GET /v1/me') == 0,
        'no continuation',
      );
      c.close();
    },
  );
  await test(
    'draft lists are snapshotted before asynchronous writes',
    () async {
      final f = IdentityFixture()..holdProfile = true;
      final c = await login(f);
      final p = profile(), pref = preferences();
      final pending = saveIdentityProfile(
        c,
        profile: p,
        preferences: pref,
        isCurrent: () => true,
      );
      await Future<void>.delayed(Duration.zero);
      p['country'] = 'SA';
      (pref['countries'] as List)[0] = 'SA';
      f.pendingProfile!.complete(f.reply(200, {'profile': f.lastProfile}));
      await pending;
      check(
        f.lastProfile?['country'] == 'GB' &&
            f.lastPreferences?['countries'][0] == 'GB',
        'immutable submission',
      );
      c.close();
    },
  );
  await test('session change during readback discards old result', () async {
    final f = IdentityFixture()
      ..failProfileSaveAt = 'preferences'
      ..holdReadback = true;
    final c = await login(f);
    final pending = save(c).then<Object>((v) => v, onError: (Object e) => e);
    await Future<void>.delayed(Duration.zero);
    c.forgetLocalSession();
    f.pendingReadback!.complete(
      f.reply(200, {
        'id': 'usr_11111111111111111111111111111111',
        'profile': profile(),
        'preferences': preferences(),
      }),
    );
    final outcome = await pending;
    check(
      outcome is IdentityFailure && outcome is! ProfileSaveFailure,
      'stale readback',
    );
    c.close();
  });
  await test('replacement authenticated session is not mistaken for original session', () async {
    final f = IdentityFixture()..holdProfile = true;
    final c = await login(f);
    final pending = save(c).then<Object>((v) => v, onError: (Object e) => e);
    await Future<void>.delayed(Duration.zero);
    final original = c.sessionGeneration;
    await c.login('member@example.invalid', 'SyntheticOnlyPassword!12');
    check(c.authenticated && c.sessionGeneration != original, 'new authenticated generation');
    f.pendingProfile!.complete(f.reply(200, {'profile': f.lastProfile}));
    final outcome = await pending;
    check(outcome is IdentityFailure && outcome is! ProfileSaveFailure, 'old outcome discarded');
    check(c.authenticated && calls(f, 'PUT /v1/me/preferences') == 0, 'new session retained');
    c.close();
  });
  stdout.writeln('identity profile save: $count checks passed');
}
