import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/native_archive/app.dart';
import 'package:wainek_mobile/src/native_archive/channel.dart';
import 'package:wainek_mobile/src/native_archive/controller.dart';

final class CapacityFixture implements ArchiveProbePort {
  @override
  Future<ArchiveLease> open(int epoch) async =>
      throw const ArchiveProbeFailure('capacity');
  @override
  Future<ArchiveProbeReceipt> probe(ArchiveLease lease) async =>
      throw StateError('must not probe after capacity rejection');
  @override
  Future<void> close(ArchiveLease lease) async {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('wainek/native_archive_v1');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  test('native capacity rejection is a bounded public status, not success', () async {
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'close') return {'closed': true};
      if (call.method == 'open') throw PlatformException(code: 'capacity');
      fail('capacity-rejected open must not probe');
    });
    final controller = ArchiveProbeController(MethodChannelArchiveProbe());
    controller.acknowledge(controller.viewToken, true);
    await controller.run(controller.viewToken);
    expect(controller.stage, ArchiveProbeStage.failed);
    expect(controller.failure, 'capacity');
    expect(controller.consent, false);
    controller.dispose();
  });

  testWidgets('capacity status explains new engine session without fake success',
      (tester) async {
    await tester.pumpWidget(NativeArchiveApp(port: CapacityFixture()));
    await tester.ensureVisible(find.byKey(const ValueKey('archive-ack')));
    await tester.tap(find.byKey(const ValueKey('archive-ack')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const ValueKey('archive-run')));
    await tester.tap(find.byKey(const ValueKey('archive-run')));
    await tester.pumpAndSettle();
    expect(find.textContaining('بلغت هذه الجلسة حد التجارب المحلية'), findsOneWidget);
    expect(find.textContaining('أعاد المحرك نجاح'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}
