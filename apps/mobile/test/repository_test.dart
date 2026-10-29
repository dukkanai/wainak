import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/repository.dart';

void register(DevJourneyRepository r) =>
    r.register(age: 29, adult: true, muslim: true, terms: true, privacy: true);
void ready(DevJourneyRepository r) {
  register(r);
  r.saveProfile(country: 'السعودية', goal: 'زواج', discoverable: true);
  r.saveAssessment('القيم');
}

void active(DevJourneyRepository r) {
  ready(r);
  r.requestRelationship();
  r.simulateDecision(accepted: true);
  r.simulateActivation();
}

void main() {
  test('minor cannot bypass eligibility with declarations', () {
    final r = DevJourneyRepository();
    expect(
      () => r.register(
        age: 17,
        adult: true,
        muslim: true,
        terms: true,
        privacy: true,
      ),
      throwsA(isA<JourneyFailure>()),
    );
    expect(r.registered, isFalse);
  });
  test('all required declarations must be present', () {
    for (var omitted = 0; omitted < 4; omitted++) {
      final r = DevJourneyRepository();
      expect(
        () => r.register(
          age: 18,
          adult: omitted != 0,
          muslim: omitted != 1,
          terms: omitted != 2,
          privacy: omitted != 3,
        ),
        throwsA(isA<JourneyFailure>()),
      );
    }
  });
  test('age and profile are separate from identity verification', () {
    final r = DevJourneyRepository();
    r.register(age: 18, adult: true, muslim: true, terms: true, privacy: true);
    expect(r.age, 18);
    expect(r.profileSaved, isFalse);
  });
  test('cannot request before completing profile and assessment', () {
    final r = DevJourneyRepository();
    register(r);
    expect(r.requestRelationship, throwsA(isA<JourneyFailure>()));
  });
  test('request acceptance and activation are distinct', () {
    final r = DevJourneyRepository();
    ready(r);
    expect(r.simulateActivation, throwsA(isA<JourneyFailure>()));
    r.requestRelationship();
    expect(r.requestRelationship, throwsA(isA<JourneyFailure>()));
    expect(r.simulateActivation, throwsA(isA<JourneyFailure>()));
    r.simulateDecision(accepted: true);
    expect(r.relationship, RelationshipState.acceptedPendingActivation);
    expect(() => r.sendAnswer('خيار'), throwsA(isA<JourneyFailure>()));
    r.simulateActivation();
    expect(r.relationship, RelationshipState.activeCards);
  });
  test('decline and cancellation do not open conversation', () {
    for (final accept in [false, true]) {
      final r = DevJourneyRepository();
      ready(r);
      r.requestRelationship();
      if (accept) {
        r.cancelRequest();
      } else {
        r.simulateDecision(accepted: false);
      }
      expect(r.simulateActivation, throwsA(isA<JourneyFailure>()));
      expect(() => r.sendAnswer('خيار'), throwsA(isA<JourneyFailure>()));
    }
  });
  test(
    'returning online does not claim automatic delivery or duplicate sends',
    () {
      final r = DevJourneyRepository();
      active(r);
      r.setOnline(false);
      r.sendAnswer('وقت هادئ');
      expect(r.answerPending, isTrue);
      r.setOnline(true);
      expect(r.answerPending, isTrue);
      expect(() => r.sendAnswer('مرة أخرى'), throwsA(isA<JourneyFailure>()));
      r.retryAnswer();
      expect(r.answerPending, isFalse);
      expect(r.retryAnswer, throwsA(isA<JourneyFailure>()));
    },
  );
  test('block cancels pending outbox and cannot be undone by activation', () {
    final r = DevJourneyRepository();
    active(r);
    r.setOnline(false);
    r.sendAnswer('وقت هادئ');
    r.block();
    expect(r.answer, isNull);
    expect(r.answerPending, isFalse);
    r.setOnline(true);
    expect(r.retryAnswer, throwsA(isA<JourneyFailure>()));
    expect(r.simulateActivation, throwsA(isA<JourneyFailure>()));
    expect(r.requestRelationship, throwsA(isA<JourneyFailure>()));
  });
  test('report available before purchase and after block without evidence', () {
    final r = DevJourneyRepository();
    ready(r);
    r.report('إساءة');
    r.block();
    r.report('سلامة طفل');
    expect(r.reports, 2);
    expect(r.answer, isNull);
  });
  test('delete and fresh repository remove synthetic state', () {
    final r = DevJourneyRepository();
    active(r);
    r.sendAnswer('وقت هادئ');
    r.report('إساءة');
    r.deleteDemoAccount();
    expect(r.registered, isFalse);
    expect(r.answer, isNull);
    expect(r.reports, 0);
    expect(r.country, isNull);
    expect(r.priority, isNull);
    expect(r.relationship, RelationshipState.none);
    expect(DevJourneyRepository().registered, isFalse);
  });
}
