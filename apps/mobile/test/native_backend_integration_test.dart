import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/api/client.dart';
import 'package:wainek_mobile/src/api/http_repository.dart';
import 'package:wainek_mobile/src/api/transport_io.dart';
import 'package:wainek_mobile/src/repository.dart';

void main() {
  final backendRoot = Platform.environment['WAINEK_BACKEND_ROOT'];
  final externalUrl = Platform.environment['WAINEK_TEST_BASE_URL'];
  final controlPath = Platform.environment['WAINEK_TEST_CONTROL_DIR'];
  Future<void> restartCheckpoint(String phase) async {
    if (controlPath == null) return;
    final directory = Directory(controlPath);
    expect(directory.isAbsolute, isTrue);
    expect(
      await FileSystemEntity.type(controlPath, followLinks: false),
      FileSystemEntityType.directory,
    );
    final ready = File('$controlPath/$phase.ready');
    final resumed = File('$controlPath/$phase.resumed');
    expect(
      await FileSystemEntity.type(ready.path, followLinks: false),
      FileSystemEntityType.notFound,
    );
    expect(
      await FileSystemEntity.type(resumed.path, followLinks: false),
      FileSystemEntityType.notFound,
    );
    // Publish only a closed, complete marker. Creating the final path before
    // writing lets the Python observer see an empty file after exists().
    // The private control directory has one Dart writer for each ready name.
    final staging = await directory.createTemp('.$phase-marker-');
    try {
      final pending = await File(
        '${staging.path}/ready',
      ).create(exclusive: true);
      await pending.writeAsString('ready', flush: true);
      expect(
        await FileSystemEntity.type(ready.path, followLinks: false),
        FileSystemEntityType.notFound,
      );
      // Both paths are on the same filesystem; rename publishes atomically.
      await pending.rename(ready.path);
    } finally {
      await staging.delete(recursive: true);
    }
    final deadline = DateTime.now().add(const Duration(seconds: 90));
    while (!await resumed.exists()) {
      if (DateTime.now().isAfter(deadline))
        throw TimeoutException('Isolated test restart checkpoint timed out');
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    expect(
      await FileSystemEntity.type(resumed.path, followLinks: false),
      FileSystemEntityType.file,
    );
    expect(await resumed.readAsString(), 'resumed');
  }

  test(
    'actual loopback backend: two sessions, adaptive profile to cards, block/report/delete',
    () async {
      Process? server;
      StreamSubscription<String>? errSub;
      Uri? external;
      if (externalUrl != null) {
        external = Uri.parse(externalUrl);
        expect(external.scheme, 'http');
        expect(external.host, '127.0.0.1');
        expect(external.hasPort && external.port > 0, isTrue);
        expect(
          external.userInfo.isEmpty &&
              !external.hasQuery &&
              !external.hasFragment,
          isTrue,
        );
        expect(external.path.isEmpty || external.path == '/', isTrue);
      } else {
        expect(controlPath, isNull);
        server = await Process.start(
          'python3',
          [
            '-u',
            '-c',
            r'''
from wsgiref.simple_server import make_server,WSGIRequestHandler
from wainek.api import DevelopmentApplication
class Quiet(WSGIRequestHandler):
 def log_message(self,*args): pass
app=DevelopmentApplication(enable_development=True)
with make_server('127.0.0.1',0,app,handler_class=Quiet) as server:
 print(server.server_port,flush=True)
 server.serve_forever()
''',
          ],
          environment: {'PYTHONPATH': '$backendRoot/backend'},
        );
        errSub = server.stderr.transform(utf8.decoder).listen((_) {});
      }
      WainekApiClient? peer;
      HttpJourneyRepository? repo;
      try {
        final Uri uri;
        if (external != null) {
          uri = external;
        } else {
          final line = await server!.stdout
              .transform(utf8.decoder)
              .transform(const LineSplitter())
              .first
              .timeout(const Duration(seconds: 10));
          uri = Uri.parse('http://127.0.0.1:${int.parse(line)}');
        }
        peer = WainekApiClient(baseUri: uri, transport: NativeApiTransport());
        final peerAccount = await peer.register(
          email:
              'peer_${DateTime.now().microsecondsSinceEpoch}@example.invalid',
          birthDate: '1994-01-01',
          isMuslim: true,
          acceptedTerms: true,
          acknowledgedPrivacy: true,
        );
        await peer.verifyEmailSimulation();
        await peer.saveProfile({
          'gender': 'male',
          'country': 'SA',
          'marital_status': 'single',
          'declared_wives': 0,
          'marriage_goal': 'build_family',
          'discoverable': true,
        });
        await peer.savePreferences({
          'min_age': 18,
          'max_age': 60,
          'countries': <String>[],
          'marital_statuses': ['single'],
        });
        repo = HttpJourneyRepository(
          WainekApiClient(baseUri: uri, transport: NativeApiTransport()),
        );
        await repo.register(
          age: 29,
          adult: true,
          muslim: true,
          terms: true,
          privacy: true,
        );
        expect(repo.registered, isTrue);
        expect(repo.emailVerified, isFalse);
        await repo.verifyDevelopmentEmail();
        expect(repo.emailVerified, isTrue);
        await repo.saveProfile(
          country: 'السعودية',
          goal: 'build_family',
          discoverable: true,
          minAge: 18,
          maxAge: 60,
        );
        var count = 0;
        while (!repo.assessmentSaved) {
          expect(count++, lessThan(4));
          await repo.saveAssessment(repo.assessmentOptions.first);
        }
        expect(count, 3);
        expect(repo.hasCandidate, isTrue);
        expect(repo.candidateDetails, contains('32'));
        await repo.requestRelationship();
        expect(repo.relationship, RelationshipState.requested);
        expect(
          () => repo!.simulateDecision(accepted: true),
          throwsA(isA<JourneyFailure>()),
        );
        final incoming = await peer.relationships();
        final id = (incoming['items'] as List).single['id'] as String;
        await peer.respond(
          id,
          accept: true,
        ); // Real recipient session, not client impersonation.
        await repo.refreshRelationship();
        expect(repo.relationship, RelationshipState.acceptedPendingActivation);
        await repo.simulateActivation();
        expect(repo.relationship, RelationshipState.activeCards);
        expect(repo.dialogueOptions, isNotEmpty);
        expect(repo.dialogueTransportAvailable, isFalse);
        expect(
          () => repo!.sendAnswer('لا ترسل'),
          throwsA(isA<JourneyFailure>()),
        );
        await restartCheckpoint('active');
        await repo.refreshRelationship();
        expect(repo.relationship, RelationshipState.activeCards);
        expect(repo.dialogueOptions, isNotEmpty);
        expect((await peer.me())['id'], peerAccount['id']);
        expect((await repo.api.me())['dev_email_verified'], isTrue);
        await repo.report('تحرش أو إساءة');
        await repo.block();
        expect(repo.relationship, RelationshipState.blocked);
        expect(repo.hasCandidate, isFalse);
        expect(repo.canReport, isTrue);
        await repo.report('سلامة طفل أو قاصر');
        expect(repo.reports, 2);
        await restartCheckpoint('blocked');
        await repo.refreshRelationship();
        expect(repo.relationship, RelationshipState.blocked);
        expect(repo.hasCandidate, isFalse);
        expect(repo.dialogueOptions, isEmpty);
        await repo.report('تحرش أو إساءة');
        expect(repo.reports, 3);
        await repo.deleteDemoAccount();
        expect(repo.registered, isFalse);
        expect(repo.canReport, isFalse);
      } finally {
        repo?.dispose();
        peer?.close();
        if (server != null) {
          server.kill(ProcessSignal.sigterm);
          try {
            await server.exitCode.timeout(const Duration(seconds: 5));
          } on TimeoutException {
            server.kill(ProcessSignal.sigkill);
            await server.exitCode;
          }
        }
        await errSub?.cancel();
      }
    },
    skip: backendRoot == null && externalUrl == null
        ? 'Set WAINEK_BACKEND_ROOT to an authorized local backend checkout; no server starts by default.'
        : false,
    timeout: const Timeout(Duration(seconds: 240)),
  );
}
