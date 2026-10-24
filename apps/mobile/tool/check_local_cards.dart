// Standalone verification prints fixed case labels only, never draft values.
// ignore_for_file: avoid_print

import '../lib/src/local_cards/catalog.dart';
import '../lib/src/local_cards/controller.dart';

void check(bool condition) {
  if (!condition)
    throw StateError('Local draft invariant failed; values suppressed');
}

void rejects(void Function() action) {
  var rejected = false;
  try {
    action();
  } on LocalDraftFailure {
    rejected = true;
  } on LocalCatalogFailure {
    rejected = true;
  }
  check(rejected);
}

LocalDraftController begun() {
  final c = LocalDraftController(sampleLocalCatalog());
  c.start(c.viewToken, acceptedLocalOnly: true);
  return c;
}

void selected(LocalDraftController c) {
  c.openCard(c.viewToken, c.catalog.cards.first.id);
  c.choose(c.viewToken, c.card!.responses.first.id);
}

void emptyLocked(LocalDraftController c) => check(
  c.stage == LocalDraftStage.locked &&
      !c.acknowledged &&
      c.card == null &&
      c.response == null,
);
void main() {
  final cases = <String, void Function()>{
    'default and release gate deny local demo': () {
      for (final dev in [false, true])
        for (final release in [false, true])
          for (final mode in [
            'local_cards',
            'fake',
            'identity',
            'api',
            'unknown',
          ])
            check(
              localCardsModeAllowed(
                    developmentEnabled: dev,
                    releaseMode: release,
                    mode: mode,
                  ) ==
                  (dev && !release && mode == 'local_cards'),
            );
    },
    'sample catalogue is bounded Arabic and has deferral without scoring': () {
      final c = sampleLocalCatalog();
      check(
        c.locale == 'ar' &&
            c.cards.length == 4 &&
            c.cards.every(
              (v) =>
                  v.responses.length == 4 &&
                  v.responses.any((r) => r.id.endsWith('_defer')),
            ),
      );
    },
    'catalogue collections are deep immutable and copy input containers': () {
      final responses = [
        LocalCardResponse(id: 'alpha_one', label: 'خيار أول'),
        LocalCardResponse(id: 'alpha_two', label: 'خيار ثان'),
      ];
      final card = LocalDialogueCard(
        id: 'card_alpha',
        topic: LocalCardTopic.privacy,
        title: 'عنوان',
        prompt: 'سؤال واضح',
        responses: responses,
      );
      responses.clear();
      check(card.responses.length == 2);
      final cards = [card];
      final c = LocalDialogueCatalog(
        version: 'sample_one',
        locale: 'ar',
        cards: cards,
      );
      cards.clear();
      check(c.cards.length == 1);
      var first = false, second = false;
      try {
        c.cards.clear();
      } on UnsupportedError {
        first = true;
      }
      try {
        card.responses.clear();
      } on UnsupportedError {
        second = true;
      }
      check(first && second);
    },
    'unknown locale duplicate IDs empty and directional override copy reject':
        () {
          final c = sampleLocalCatalog();
          rejects(
            () => LocalDialogueCatalog(
              version: 'sample_one',
              locale: 'ar-SA',
              cards: c.cards,
            ),
          );
          rejects(
            () => LocalDialogueCatalog(
              version: 'sample_one',
              locale: 'ar',
              cards: [c.cards.first, c.cards.first],
            ),
          );
          rejects(() => LocalCardResponse(id: 'invalid\n', label: 'خيار'));
          rejects(() => LocalCardResponse(id: 'valid_id', label: ' '));
          rejects(
            () => LocalCardResponse(id: 'valid_id', label: 'نص\u202eخفى'),
          );
          rejects(
            () => LocalCardResponse(
              id: 'valid_id',
              label: List.filled(121, 'س').join(),
            ),
          );
          rejects(
            () => LocalDialogueCard(
              id: 'card_bad',
              topic: LocalCardTopic.privacy,
              title: 'عنوان',
              prompt: 'سؤال',
              responses: [
                c.cards.first.responses.first,
                c.cards.first.responses.first,
              ],
            ),
          );
        },
    'locked state needs current explicit acknowledgement': () {
      final c = LocalDraftController(sampleLocalCatalog());
      rejects(() => c.openCard(c.viewToken, c.catalog.cards.first.id));
      rejects(() => c.start(c.viewToken, acceptedLocalOnly: false));
      emptyLocked(c);
      c.start(c.viewToken, acceptedLocalOnly: true);
      rejects(() => c.start(c.viewToken, acceptedLocalOnly: true));
      check(c.stage == LocalDraftStage.catalog);
    },
    'one choice preview is local and input rejection is atomic': () {
      final c = begun();
      selected(c);
      final prior = c.response;
      rejects(() => c.openCard(c.viewToken, 'missing_card'));
      rejects(() => c.choose(c.viewToken, 'missing_response'));
      rejects(
        () => c.choose(c.viewToken, c.catalog.cards.last.responses.first.id),
      );
      check(
        identical(prior, c.response) && c.stage == LocalDraftStage.choosing,
      );
      c.preview(c.viewToken);
      check(c.stage == LocalDraftStage.preview && identical(prior, c.response));
    },
    'preview without selected response rejects': () {
      final c = begun();
      c.openCard(c.viewToken, c.catalog.cards.first.id);
      rejects(() => c.preview(c.viewToken));
      check(c.response == null && c.stage == LocalDraftStage.choosing);
    },
    'cross controller and cross version view capabilities reject': () {
      final a = begun(), b = begun();
      rejects(() => b.openCard(a.viewToken, b.catalog.cards.first.id));
      final source = sampleLocalCatalog();
      final d = LocalDraftController(
        LocalDialogueCatalog(
          version: 'local_cards_v2',
          locale: 'ar',
          cards: source.cards,
        ),
      );
      rejects(() => d.start(a.viewToken, acceptedLocalOnly: true));
      emptyLocked(d);
    },
    'card change invalidates old callbacks and removes old choice': () {
      final c = begun();
      selected(c);
      final old = c.viewToken;
      c.openCard(c.viewToken, c.catalog.cards.last.id);
      rejects(() => c.choose(old, c.catalog.cards.first.responses.first.id));
      check(c.response == null && c.card!.id == c.catalog.cards.last.id);
    },
    'return to catalogue preserves only boundary acknowledgement': () {
      final c = begun();
      selected(c);
      final old = c.viewToken;
      c.returnToCatalog(c.viewToken);
      check(
        c.stage == LocalDraftStage.catalog &&
            c.acknowledged &&
            c.card == null &&
            c.response == null,
      );
      rejects(() => c.preview(old));
      c.openCard(c.viewToken, c.catalog.cards.first.id);
      check(c.response == null);
    },
    'clear invalidates even a previously captured start action': () {
      final c = LocalDraftController(sampleLocalCatalog());
      final old = c.viewToken;
      c.clear();
      rejects(() => c.start(old, acceptedLocalOnly: true));
      emptyLocked(c);
      c.start(c.viewToken, acceptedLocalOnly: true);
      selected(c);
      final selectedView = c.viewToken;
      c.clear();
      rejects(() => c.preview(selectedView));
      emptyLocked(c);
    },
    'all host invalidations remove choice and boundary acknowledgement': () {
      for (final reason in LocalDraftInvalidation.values) {
        final c = begun();
        selected(c);
        c.preview(c.viewToken);
        final old = c.viewToken;
        c.invalidate(reason);
        emptyLocked(c);
        rejects(() => c.preview(old));
      }
    },
    'repeat press creates no history or secondary transition': () {
      final c = begun();
      c.openCard(c.viewToken, c.catalog.cards.first.id);
      final old = c.viewToken;
      final response = c.card!.responses.first.id;
      c.choose(old, response);
      rejects(() => c.choose(old, response));
      c.choose(c.viewToken, response);
      c.preview(c.viewToken);
      final shown = c.viewToken;
      c.preview(shown);
      check(c.isCurrentView(shown) && c.stage == LocalDraftStage.preview);
      c.clear();
      c.clear();
      emptyLocked(c);
    },
    'disposed terminal rejects old and newly requested capabilities': () {
      final c = begun();
      selected(c);
      final old = c.viewToken;
      c.dispose();
      c.clear();
      c.invalidate(LocalDraftInvalidation.cancel);
      c.dispose();
      rejects(() => c.preview(old));
      rejects(() => c.start(c.viewToken, acceptedLocalOnly: true));
      check(
        c.stage == LocalDraftStage.disposed &&
            c.card == null &&
            c.response == null &&
            !c.acknowledged &&
            !c.isCurrentView(c.viewToken),
      );
    },
    'string representations and failures never include draft values': () {
      final c = begun();
      selected(c);
      check(
        c.toString() == 'LocalDraftController' &&
            c.viewToken.toString() == 'LocalDraftViewToken' &&
            c.card.toString() == 'LocalDialogueCard' &&
            c.response.toString() == 'LocalCardResponse',
      );
      try {
        c.choose(c.viewToken, 'unrecognised_private_value');
      } on LocalDraftFailure catch (e) {
        check(e.toString() == 'LocalDraftFailure');
      }
    },
  };
  for (final entry in cases.entries) {
    entry.value();
    print('PASS ${entry.key}');
  }
  print('LOCAL_CARDS_CHECKS_PASSED=${cases.length}');
}
