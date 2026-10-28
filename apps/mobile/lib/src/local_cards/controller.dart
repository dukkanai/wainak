import 'catalog.dart';

enum LocalDraftStage { locked, catalog, choosing, preview, disposed }

enum LocalDraftInvalidation {
  cancel,
  back,
  routeCovered,
  background,
  hidden,
  scopeChanged,
  sessionChanged,
  safetyBlock,
}

enum LocalDraftFailureCode {
  closed,
  staleView,
  invalidAction,
  unknownCard,
  unknownResponse,
  acknowledgementRequired,
}

final class LocalDraftFailure implements Exception {
  const LocalDraftFailure(this.code);
  final LocalDraftFailureCode code;
  @override
  String toString() => 'LocalDraftFailure';
}

/// Capability scoped to this controller, catalogue version and exact rendered view.
/// It is neither an account credential nor a delivery/entitlement capability.
final class LocalDraftViewToken {
  const LocalDraftViewToken._(
    this._owner,
    this._version,
    this._revision,
    this._card,
  );
  final Object _owner;
  final String _version;
  final int _revision;
  final String? _card;
  @override
  String toString() => 'LocalDraftViewToken';
}

bool localCardsModeAllowed({
  required bool developmentEnabled,
  required bool releaseMode,
  required String mode,
}) => developmentEnabled && !releaseMode && mode == 'local_cards';

/// One RAM-only choice, synchronous transitions, no history, serialization,
/// clock, async work, API, logging, persistence or implied partner response.
final class LocalDraftController {
  LocalDraftController(this.catalog);
  final LocalDialogueCatalog catalog;
  final Object _owner = Object();
  int _revision = 0;
  LocalDraftStage _stage = LocalDraftStage.locked;
  LocalDialogueCard? _card;
  LocalCardResponse? _response;
  bool _acknowledged = false;
  LocalDraftStage get stage => _stage;
  bool get acknowledged => _acknowledged;
  LocalDialogueCard? get card => _card;
  LocalCardResponse? get response => _response;
  LocalDraftViewToken get viewToken =>
      LocalDraftViewToken._(_owner, catalog.version, _revision, _card?.id);
  bool isCurrentView(LocalDraftViewToken token) =>
      _stage != LocalDraftStage.disposed &&
      identical(token._owner, _owner) &&
      token._version == catalog.version &&
      token._revision == _revision &&
      token._card == _card?.id;
  void _check(LocalDraftViewToken token) {
    if (_stage == LocalDraftStage.disposed)
      throw const LocalDraftFailure(LocalDraftFailureCode.closed);
    if (!isCurrentView(token))
      throw const LocalDraftFailure(LocalDraftFailureCode.staleView);
  }

  void start(LocalDraftViewToken token, {required bool acceptedLocalOnly}) {
    _check(token);
    if (_stage != LocalDraftStage.locked)
      throw const LocalDraftFailure(LocalDraftFailureCode.invalidAction);
    if (!acceptedLocalOnly)
      throw const LocalDraftFailure(
        LocalDraftFailureCode.acknowledgementRequired,
      );
    _acknowledged = true;
    _stage = LocalDraftStage.catalog;
    _revision++;
  }

  void openCard(LocalDraftViewToken token, String cardId) {
    _check(token);
    if (!_acknowledged ||
        !{
          LocalDraftStage.catalog,
          LocalDraftStage.choosing,
          LocalDraftStage.preview,
        }.contains(_stage))
      throw const LocalDraftFailure(LocalDraftFailureCode.invalidAction);
    final matches = catalog.cards.where((v) => v.id == cardId);
    if (matches.length != 1)
      throw const LocalDraftFailure(LocalDraftFailureCode.unknownCard);
    final next = matches.single;
    _card = next;
    _response = null;
    _stage = LocalDraftStage.choosing;
    _revision++;
  }

  void choose(LocalDraftViewToken token, String responseId) {
    _check(token);
    if (_stage != LocalDraftStage.choosing || _card == null)
      throw const LocalDraftFailure(LocalDraftFailureCode.invalidAction);
    final matches = _card!.responses.where((v) => v.id == responseId);
    if (matches.length != 1)
      throw const LocalDraftFailure(LocalDraftFailureCode.unknownResponse);
    final next = matches.single;
    if (identical(next, _response)) return;
    _response = next;
    _revision++;
  }

  void preview(LocalDraftViewToken token) {
    _check(token);
    if (_stage == LocalDraftStage.preview) return;
    if (_stage != LocalDraftStage.choosing || _response == null)
      throw const LocalDraftFailure(LocalDraftFailureCode.invalidAction);
    _stage = LocalDraftStage.preview;
    _revision++;
  }

  void returnToCatalog(LocalDraftViewToken token) {
    _check(token);
    if (!_acknowledged ||
        !{LocalDraftStage.choosing, LocalDraftStage.preview}.contains(_stage))
      throw const LocalDraftFailure(LocalDraftFailureCode.invalidAction);
    _card = null;
    _response = null;
    _stage = LocalDraftStage.catalog;
    _revision++;
  }

  void clear() {
    if (_stage == LocalDraftStage.disposed) return;
    _card = null;
    _response = null;
    _acknowledged = false;
    _stage = LocalDraftStage.locked;
    _revision++;
  }

  void invalidate(LocalDraftInvalidation reason) => clear();
  void dispose() {
    if (_stage == LocalDraftStage.disposed) return;
    clear();
    _stage = LocalDraftStage.disposed;
    _revision++;
  }

  @override
  String toString() => 'LocalDraftController';
}
