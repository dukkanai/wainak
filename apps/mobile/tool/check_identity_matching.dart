import 'dart:async';
import 'dart:io';
import 'package:wainak_mobile/src/identity/client.dart';
import 'package:wainak_mobile/src/identity/matching_repository.dart';
import '../test/support/matching_fixture.dart';

void check(bool value) {
  if (!value) throw StateError('Matching assertion failed');
}

Future<bool> rejected(FutureOr<void> Function() action) async {
  try {
    await action();
    return false;
  } on IdentityFailure {
    return true;
  } on ArgumentError {
    return true;
  }
}

Future<(MatchingFixture, IdentityClient, IdentityMatchingRepository)> setup({
  bool incoming = false,
}) async {
  final f = MatchingFixture()
    ..verified = true
    ..incoming = incoming;
  final c = IdentityClient(
    baseUri: Uri.parse('http://127.0.0.1:8089'),
    transport: f,
  );
  await c.login(f.email, 'SyntheticOnlyPassword!12');
  return (f, c, IdentityMatchingRepository(c));
}

Future<void> main() async {
  var passed = 0;
  Future<void> scenario(String label, Future<void> Function() body) async {
    await body();
    passed++;
    stdout.writeln('PASS $label');
  }

  try {
    await scenario(
      'typed projection verifies actor direction and peer; no implicit card action',
      () async {
        final (f, c, r) = await setup(incoming: true);
        f.hasRelation = true;
        await r.refreshCandidates();
        await r.refreshRelationships();
        check(
          r.candidates.single.id == f.targetId &&
              r.relationships.single.can(MatchAction.accept),
        );
        final wrong = {...f.relationship, 'direction': 'outgoing'};
        check(
          await rejected(
            () => MatchRelationship.fromJson(
              wrong,
              actorId: r.actorId,
              generation: r.generation,
            ),
          ),
        );
        final bad = {
          ...f.relationship,
          'permissions': {
            ...(f.relationship['permissions'] as Map<String, dynamic>),
            'can_send_cards': true,
          },
        };
        check(
          await rejected(
            () => MatchRelationship.fromJson(
              bad,
              actorId: r.actorId,
              generation: r.generation,
            ),
          ),
        );
        check(
          await rejected(
            () => c.domain(
              'GET',
              '/v1/relationships/rel_44444444444444444444444444444444/cards',
            ),
          ),
        );
        c.close();
      },
    );
    await scenario(
      'uncertain request keeps same actor target and idempotency key across refresh',
      () async {
        final (f, c, r) = await setup();
        await r.refreshCandidates();
        final candidate = r.candidates.single;
        f.failRequestOnce = true;
        check(await rejected(() => r.request(candidate)));
        check(r.pendingRequestTargets.single == candidate.id);
        await r.refreshRelationships();
        await r.retryRequest(candidate.id);
        final calls = f.matchingCalls
            .where(
              (v) => v['method'] == 'POST' && v['path'] == '/v1/relationships',
            )
            .toList();
        check(
          calls.length == 2 &&
              calls[0]['key'] == calls[1]['key'] &&
              f.requestCreates == 1 &&
              r.pendingRequestTargets.isEmpty,
        );
        check(
          calls.every(
            (v) =>
                (v['header_names'] as Set).contains('X-Session-Token') &&
                !(v['header_names'] as Set).contains('Authorization'),
          ),
        );
        c.close();
      },
    );
    await scenario(
      'report retry is independent of block and metadata-only',
      () async {
        final (f, c, r) = await setup();
        await r.refreshCandidates();
        final target = r.candidateContext(r.candidates.single);
        f.failReportOnce = true;
        check(await rejected(() => r.report(target, 'harassment')));
        await r.block(target);
        await r.report(target, 'harassment');
        final calls = f.matchingCalls
            .where((v) => v['path'] == '/v1/reports')
            .toList();
        check(calls.length == 2 && calls[0]['key'] == calls[1]['key']);
        check(
          (calls.last['body'] as Map).keys.toSet().difference({
                'target_id',
                'category',
              }).isEmpty &&
              f.blockCalls == 1,
        );
        c.close();
      },
    );
    await scenario(
      'new target and new report intent use distinct idempotency keys',
      () async {
        final (f, c, r) = await setup();
        await r.refreshCandidates();
        await r.request(r.candidates.single);
        f.targetId = 'usr_33333333333333333333333333333333';
        await r.refreshCandidates();
        final other = r.candidates.single;
        await r.request(other);
        final requests = f.matchingCalls
            .where(
              (v) => v['method'] == 'POST' && v['path'] == '/v1/relationships',
            )
            .toList();
        check(requests[0]['key'] != requests[1]['key']);
        final context = r.candidateContext(other);
        await r.report(context, 'threat');
        await r.report(context, 'other_safety');
        final reports = f.matchingCalls
            .where((v) => v['path'] == '/v1/reports')
            .toList();
        check(reports[0]['key'] != reports[1]['key']);
        c.close();
      },
    );
    for (final kind in ['relationships', 'candidates', 'accept']) {
      await scenario(
        'late $kind reply cannot restore blocked peer or actions',
        () async {
          final (f, c, r) = await setup(incoming: true);
          f.hasRelation = true;
          await r.refreshCandidates();
          final target = r.candidateContext(r.candidates.single);
          await r.refreshRelationships();
          final relation = r.relationships.single;
          final oldRelations = f.reply(200, {
            'items': [f.relationship],
          });
          final oldCandidates = f.reply(200, {
            'items': [f.candidate],
            'mode': 'synthetic_development_only',
          });
          final oldAccepted = f.reply(200, {
            ...f.relationship,
            'status': 'accepted_pending_activation',
            'available_actions': ['end', 'block', 'report'],
          });
          late Future<bool> pending;
          if (kind == 'relationships') {
            f.holdRelationships = true;
            pending = rejected(r.refreshRelationships);
          } else if (kind == 'candidates') {
            f.holdCandidates = true;
            pending = rejected(r.refreshCandidates);
          } else {
            f.holdAction = true;
            pending = rejected(() => r.act(relation, MatchAction.accept));
          }
          await Future<void>.delayed(Duration.zero);
          await r.block(target);
          if (kind == 'relationships')
            f.pendingRelationships!.complete(oldRelations);
          else if (kind == 'candidates')
            f.pendingCandidates!.complete(oldCandidates);
          else
            f.pendingAction!.complete(oldAccepted);
          check(await pending);
          check(
            r.relationships.isEmpty &&
                r.candidates.isEmpty &&
                r.lastSafety?.alias == null,
          );
          c.close();
        },
      );
    }
    await scenario(
      'incoming actor can decline redacted stale-consent peer without accepting',
      () async {
        final (f, c, r) = await setup(incoming: true);
        f.hasRelation = true;
        f.peerHidden = true;
        await r.refreshRelationships();
        final relation = r.relationships.single;
        check(
          relation.peer == null &&
              !relation.can(MatchAction.accept) &&
              relation.can(MatchAction.decline),
        );
        await r.act(relation, MatchAction.decline);
        check(r.relationships.single.status == 'declined');
        c.close();
      },
    );
    await scenario(
      'stale available-action hint is rejected without optimistic acceptance',
      () async {
        final (f, c, r) = await setup(incoming: true);
        f.hasRelation = true;
        await r.refreshRelationships();
        final relation = r.relationships.single;
        f.rejectActions = true;
        check(await rejected(() => r.act(relation, MatchAction.accept)));
        check(r.relationships.isEmpty && c.authenticated);
        c.close();
      },
    );
    await scenario(
      'domain business410 preserves session; domain401 expires it',
      () async {
        final (f, c, r) = await setup();
        await r.refreshCandidates();
        final target = r.candidateContext(r.candidates.single);
        f.reportGone = true;
        check(await rejected(() => r.report(target, 'other_safety')));
        check(c.authenticated);
        f.unknownGone = true;
        check(await rejected(r.refreshCandidates));
        check(c.authenticated);
        f.unknownGone = false;
        f.expired = true;
        check(await rejected(r.refreshRelationships));
        check(!c.authenticated);
        c.close();
      },
    );
    await scenario(
      'old candidate or confirmation cannot move into a replacement actor/session',
      () async {
        final (f, c, r) = await setup();
        await r.refreshCandidates();
        final candidate = r.candidates.single;
        final safety = r.candidateContext(candidate);
        final before = f.matchingCalls.length;
        await c.login(f.email, 'SyntheticOnlyPassword!12');
        final replacement = IdentityMatchingRepository(c);
        check(await rejected(() => r.request(candidate)));
        check(await rejected(() => replacement.request(candidate)));
        check(await rejected(() => replacement.block(safety)));
        check(f.matchingCalls.length == before);
        c.close();
      },
    );
    await scenario(
      'invalid request key and card activation endpoints never reach transport',
      () async {
        final (f, c, r) = await setup();
        final before = f.matchingCalls.length;
        check(
          await rejected(
            () => c.domain(
              'POST',
              '/v1/relationships',
              body: {'candidate_id': f.targetId},
              idempotencyKey: 'short',
            ),
          ),
        );
        check(
          await rejected(
            () => c.domain(
              'POST',
              '/v1/dev/relationships/rel_44444444444444444444444444444444/activate',
            ),
          ),
        );
        check(
          await rejected(
            () => c.domain(
              'POST',
              '/v1/relationships/rel_44444444444444444444444444444444/cards',
            ),
          ),
        );
        check(f.matchingCalls.length == before);
        r.close();
        c.close();
      },
    );
    stdout.writeln('IDENTITY_MATCHING_CHECKS_PASSED=$passed');
  } catch (_) {
    stderr.writeln(
      'IDENTITY_MATCHING_CHECKS_FAILED; private values suppressed',
    );
    throw StateError('Identity matching checks failed; details suppressed');
  }
}
