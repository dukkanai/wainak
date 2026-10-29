import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/app.dart';
import 'package:wainek_mobile/src/repository.dart';
import 'package:wainek_mobile/src/api/client.dart';
import 'package:wainek_mobile/src/api/transport.dart';

Future<void> tapKey(WidgetTester t, String key) async {
  final target = find.byKey(Key(key));
  await t.ensureVisible(target);
  await t.pumpAndSettle();
  await t.tap(target);
  await t.pumpAndSettle();
}
Future<void> tapText(WidgetTester t, String text) async {
  final target = find.text(text).last;
  await t.ensureVisible(target);
  await t.pumpAndSettle();
  await t.tap(target);
  await t.pumpAndSettle();
}
Future<void> candidate(WidgetTester t, DevJourneyRepository r) async {
  await t.pumpWidget(WainekApp(repository: r));
  for (final key in ['adult', 'muslim', 'terms', 'privacy', 'register', 'save-profile']) {
    await tapKey(t, key);
  }
  await tapText(t, 'القيم والأهداف');
  await tapKey(t, 'save-assessment');
}
Future<void> dialogue(WidgetTester t, DevJourneyRepository r) async {
  await candidate(t, r);
  for (final key in ['request', 'accept', 'activate']) {
    await tapKey(t, key);
  }
}

class DeferredTransport implements ApiTransport {
  final replies = <Completer<ApiResponse>>[];
  final headers = <Map<String, String>>[];
  @override
  Future<ApiResponse> send(String method, Uri uri, Map<String,String> h, String? body) {
    headers.add(Map.of(h));
    final result = Completer<ApiResponse>();
    replies.add(result);
    return result.future;
  }
  @override
  void close() {}
}
ApiResponse registration(String token) => ApiResponse(201, jsonEncode({
  'mode':'synthetic_development_only', 'token_type':'Bearer', 'access_token':token,
  'account': {'id':'usr_0123456789abcdef0123456789abcdef'}
}));
Future<Map<String,dynamic>> register(WainekApiClient api) => api.register(
  email:'qa@example.invalid', birthDate:'1996-01-01',
  isMuslim:true, acceptedTerms:true, acknowledgedPrivacy:true,
);

void main() {
  testWidgets('QA: a declared minor cannot reach a profile despite checking all consents', (t) async {
    final r = DevJourneyRepository();
    await t.pumpWidget(WainekApp(repository:r));
    await tapKey(t, 'age');
    await tapText(t, '17 سنة');
    for (final key in ['adult','muslim','terms','privacy','register']) {
      await tapKey(t,key);
    }
    expect(r.registered,isFalse);
    expect(find.byKey(const Key('save-profile')),findsNothing);
    expect(find.textContaining('لا يمكن متابعة هذا السيناريو'), findsOneWidget);
    expect(t.takeException(),isNull);
  });

  testWidgets('QA: cancelling report block and delete does not mutate state', (t) async {
    final r = DevJourneyRepository();
    await candidate(t,r);
    await tapKey(t,'report');
    await tapText(t,'تحرش أو إساءة');
    await tapText(t,'الرجوع');
    expect(r.reports,0);
    await tapKey(t,'block');
    await tapText(t,'الرجوع');
    expect(r.relationship,RelationshipState.none);
    await tapKey(t,'account');
    await tapKey(t,'delete');
    await tapText(t,'الرجوع');
    expect(r.registered,isTrue);
    expect(r.profileSaved,isTrue);
    expect(r.assessmentSaved,isTrue);
    expect(t.takeException(),isNull);
  });

  testWidgets('QA: duplicate report confirm cannot pop the underlying journey', (t) async {
    final r = DevJourneyRepository();
    await candidate(t,r);
    await tapKey(t,'report');
    await tapText(t,'تحرش أو إساءة');
    final submit=find.byKey(const Key('submit-report'));
    await t.ensureVisible(submit);
    await t.pumpAndSettle();
    await t.tap(submit);
    await t.tap(submit,warnIfMissed:false);
    await t.pumpAndSettle();
    expect(r.reports,1);
    expect(find.byKey(const Key('page-heading')),findsOneWidget);
    expect(find.byKey(const Key('account')),findsOneWidget);
    expect(t.takeException(),isNull);
  });

  testWidgets('QA: block cancels pending choice and back forward cannot reopen delivery', (t) async {
    final r = DevJourneyRepository();
    await dialogue(t,r);
    await tapText(t,'نحدد وقتًا هادئًا للحوار');
    await tapKey(t,'network');
    await tapKey(t,'send');
    expect(r.answerPending,isTrue);
    await tapKey(t,'block');
    await tapText(t,'تأكيد الحظر');
    expect(r.answer,isNull);
    expect(r.answerPending,isFalse);
    await tapKey(t,'back');
    await tapKey(t,'back');
    await tapKey(t,'save-assessment');
    expect(find.byKey(const Key('activate')),findsNothing);
    expect(find.byKey(const Key('request')),findsNothing);
    expect(find.byKey(const Key('retry')),findsNothing);
    expect(find.byKey(const Key('report')),findsOneWidget);
    expect(r.relationship,RelationshipState.blocked);
    expect(t.takeException(),isNull);
  });

  testWidgets('QA: system back dismisses a safety dialog without navigating or reporting', (t) async {
    final r = DevJourneyRepository();
    await candidate(t,r);
    await tapKey(t,'report');
    await tapText(t,'سلامة طفل أو قاصر');
    await t.binding.handlePopRoute();
    await t.pumpAndSettle();
    expect(r.reports,0);
    expect(find.byKey(const Key('request')),findsOneWidget);
    expect(find.byKey(const Key('submit-report')),findsNothing);
    expect(Directionality.of(t.element(find.byKey(const Key('request')))),TextDirection.rtl);
    expect(t.takeException(),isNull);
  });

  testWidgets('QA: 200 percent narrow screen retains free safety and cancel actions', (t) async {
    t.view.physicalSize=const Size(320,800);
    t.view.devicePixelRatio=1;
    t.platformDispatcher.textScaleFactorTestValue=2;
    addTearDown(() {
      t.view.resetPhysicalSize();
      t.view.resetDevicePixelRatio();
      t.platformDispatcher.clearTextScaleFactorTestValue();
    });
    final r=DevJourneyRepository();
    await candidate(t,r);
    await tapKey(t,'report');
    final submit=t.widget<FilledButton>(find.byKey(const Key('submit-report')));
    expect(submit.onPressed,isNull);
    await tapText(t,'سلامة طفل أو قاصر');
    await tapKey(t,'submit-report');
    expect(r.reports,1);
    expect(r.relationship,RelationshipState.none);
    await tapKey(t,'block');
    await tapText(t,'الرجوع');
    expect(r.relationship,RelationshipState.none);
    await tapKey(t,'theme');
    expect(t.takeException(),isNull);
  });

  test('QA: out of order registration cannot overwrite the newest session',() async {
    final transport=DeferredTransport();
    final api=WainekApiClient(baseUri:Uri.parse('http://127.0.0.1:8089'),transport:transport);
    final old=register(api);
    final oldExpected=expectLater(old,throwsA(isA<ApiFailure>().having((e)=>e.code,'code','stale_response')));
    final current=register(api);
    transport.replies[1].complete(registration('synthetic-new'));
    await current;
    transport.replies[0].complete(registration('synthetic-old'));
    await oldExpected;
    final me=api.me();
    expect(transport.headers.last['Authorization'],'Bearer synthetic-new');
    transport.replies[2].complete(const ApiResponse(200,'{}'));
    await me;
    expect(api.hasSession,isTrue);
  });

  test('QA: successful stale read cannot survive account deletion',() async {
    final transport=DeferredTransport();
    final api=WainekApiClient(baseUri:Uri.parse('http://127.0.0.1:8089'),transport:transport);
    final first=register(api);
    transport.replies[0].complete(registration('synthetic-current'));
    await first;
    final stale=api.me();
    final staleExpected=expectLater(stale,throwsA(isA<ApiFailure>().having((e)=>e.code,'code','stale_response')));
    final deletion=api.deleteAccount();
    transport.replies[2].complete(const ApiResponse(200,'{"deleted":true}'));
    await deletion;
    transport.replies[1].complete(const ApiResponse(200,'{"id":"obsolete"}'));
    await staleExpected;
    expect(api.hasSession,isFalse);
  });
}
