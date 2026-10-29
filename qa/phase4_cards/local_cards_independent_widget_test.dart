// Independent QA overlay, no network/fixture or real relationship.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/main.dart' as entry;
import 'package:wainek_mobile/src/local_cards/app.dart';

Future<void> tapQaLocal(WidgetTester t,String key)async{
 final f=find.byKey(Key(key));await t.ensureVisible(f);await t.pumpAndSettle();await t.tap(f);await t.pumpAndSettle();
}
Future<void> startQaLocal(WidgetTester t)async{await tapQaLocal(t,'local-cards-ack');await tapQaLocal(t,'local-cards-start');}
void expectLockedQaLocal(WidgetTester t){expect(find.byKey(const Key('local-cards-ack')),findsOneWidget);expect(find.byKey(const Key('local-cards-preview-response')),findsNothing);}

void main(){
 testWidgets('QA default entrypoint remains disabled without developer opt-in',(t)async{
  expect(const bool.fromEnvironment('WAINEK_DEV_MODE'),isFalse);
  entry.main();await t.pumpAndSettle();
  expect(find.byType(entry.DisabledBuild),findsOneWidget);
  expect(find.byKey(const Key('local-cards-ack')),findsNothing);
 });
 testWidgets('QA covered-route old answer and preview cannot target a new card',(t)async{
  await t.pumpWidget(const LocalCardsApp());await startQaLocal(t);await tapQaLocal(t,'local-card-daily_rhythm');
  final oldAnswer=t.widget<OutlinedButton>(find.byKey(const Key('local-response-rhythm_plan'))).onPressed!;
  await tapQaLocal(t,'local-response-rhythm_plan');
  final oldPreview=t.widget<FilledButton>(find.byKey(const Key('local-cards-preview'))).onPressed!;
  await tapQaLocal(t,'local-cards-preview');
  final nav=Navigator.of(t.element(find.byType(Scaffold)));
  nav.push(MaterialPageRoute<void>(builder:(_)=>const Scaffold(body:Text('صفحة اختبار مستقلة'))));await t.pumpAndSettle();
  nav.pop();await t.pumpAndSettle();expectLockedQaLocal(t);
  await startQaLocal(t);await tapQaLocal(t,'local-card-different_views');
  oldAnswer();oldPreview();await t.pumpAndSettle();
  expect(find.byKey(const Key('local-response-views_defer')),findsOneWidget);
  expect(find.byKey(const Key('local-response-rhythm_plan')),findsNothing);
  expect(t.widget<FilledButton>(find.byKey(const Key('local-cards-preview'))).onPressed,isNull);
  expect(find.byKey(const Key('local-cards-preview-response')),findsNothing);expect(t.takeException(),isNull);
 });
 testWidgets('QA background invalidates old checkbox and start even after fresh acknowledgement',(t)async{
  await t.pumpWidget(const LocalCardsApp());
  final oldCheckbox=t.widget<CheckboxListTile>(find.byKey(const Key('local-cards-ack'))).onChanged!;
  await tapQaLocal(t,'local-cards-ack');
  final oldStart=t.widget<FilledButton>(find.byKey(const Key('local-cards-start'))).onPressed!;
  await tapQaLocal(t,'local-cards-start');await tapQaLocal(t,'local-card-daily_rhythm');await tapQaLocal(t,'local-response-rhythm_plan');await tapQaLocal(t,'local-cards-preview');
  try{
   t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);await t.pumpAndSettle();
  }finally{t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);await t.pumpAndSettle();}
  expectLockedQaLocal(t);await tapQaLocal(t,'local-cards-ack');
  oldCheckbox(false);oldStart();await t.pumpAndSettle();
  expectLockedQaLocal(t);expect(t.widget<CheckboxListTile>(find.byKey(const Key('local-cards-ack'))).value,isTrue);
  expect(find.byKey(const Key('local-card-daily_rhythm')),findsNothing);
  await tapQaLocal(t,'local-cards-start');await tapQaLocal(t,'local-card-daily_rhythm');
  expect(t.widget<FilledButton>(find.byKey(const Key('local-cards-preview'))).onPressed,isNull);expect(t.takeException(),isNull);
 });
}
