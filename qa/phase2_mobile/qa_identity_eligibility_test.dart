import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/identity/app.dart';
import 'package:wainek_mobile/src/identity/client.dart';
import 'support/identity_fixture.dart';

Future<void> tap(WidgetTester t,String key) async {
  final target=find.byKey(Key(key));
  expect(target,findsOneWidget);
  await t.ensureVisible(target);await t.pumpAndSettle();
  await t.tap(target);await t.pumpAndSettle();
}
Future<void> enter(WidgetTester t,String key,String value) async {
  final target=find.byKey(Key(key));await t.ensureVisible(target);
  await t.enterText(target,value);await t.pumpAndSettle();
}
Future<IdentityClient> start(WidgetTester t,IdentityFixture f) async {
  final c=IdentityClient(baseUri:Uri.parse('http://127.0.0.1:8089'),transport:f);
  await t.pumpWidget(IdentityApp(client:c));await tap(t,'identity-toggle');
  await enter(t,'identity-email','member@example.invalid');
  await enter(t,'identity-password','SyntheticOnlyPassword!12');
  return c;
}
void main(){
  testWidgets('independent UI age17 with all declarations cannot send registration',(t) async {
    final f=IdentityFixture();final c=await start(t,f);
    await tap(t,'identity-age');await t.tap(find.text('17 سنة').last);await t.pumpAndSettle();
    for(final key in ['identity-adult','identity-muslim','identity-terms','identity-privacy']){await tap(t,key);}
    await tap(t,'identity-submit');
    expect(f.registrations,0);expect(c.stage,IdentityStage.signedOut);
    expect(find.byKey(const Key('identity-error')),findsOneWidget);
    expect(find.byKey(const Key('identity-profile')),findsNothing);
    expect(t.takeException(),isNull);
    await t.pumpWidget(const SizedBox());
  });
  testWidgets('independent missing privacy consent remains blocked until explicit consent',(t) async {
    final f=IdentityFixture();final c=await start(t,f);
    for(final key in ['identity-adult','identity-muslim','identity-terms']){await tap(t,key);}
    await tap(t,'identity-submit');
    expect(f.registrations,0);expect(c.stage,IdentityStage.signedOut);
    expect(t.widget<CheckboxListTile>(find.byKey(const Key('identity-privacy'))).value,isFalse);
    await enter(t,'identity-password','SyntheticOnlyPassword!12');
    await tap(t,'identity-privacy');await tap(t,'identity-submit');
    expect(f.registrations,1);expect(c.stage,IdentityStage.pendingVerification);
    expect(find.byKey(const Key('identity-profile')),findsNothing);
    expect(t.takeException(),isNull);
    await t.pumpWidget(const SizedBox());
  });
}
