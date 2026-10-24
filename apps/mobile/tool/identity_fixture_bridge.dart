import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'private_fixture_protocol.dart';
import 'identity_fixture_path.dart';

class FixtureFailure implements Exception {
  const FixtureFailure(this.code);
  final String code;
  @override
  String toString() => 'FixtureFailure($code)';
}

/// Test-only private PIPE capability. Never imported by lib/ or an app build.
/// No secrets are placed in argv, environment, files, URLs or diagnostic output.
class IdentityFixtureBridge {
  IdentityFixtureBridge._(this._process, this.scriptSelection);
  final FixtureScriptSelection scriptSelection;
  Map<String, String> get testProvenance => scriptSelection.provenance;
  final Process _process;
  final _ready = Completer<Map<String, dynamic>>();
  final _closed = Completer<Map<String, dynamic>>();
  final _requests = <int, Completer<Map<String, dynamic>>>{};
  StreamSubscription<List<int>>? _output;
  final _outputDone = Completer<void>(), _errorsDone = Completer<void>();
  late final PrivateFixtureProtocol _protocol;
  StreamSubscription<List<int>>? _errors;
  var _nextId = 0;
  bool _protocolFailed = false, _finished = false;
  late final Uri baseUri;
  static Future<IdentityFixtureBridge> start({
    String python =
        '/home/chatbot/wainak-dev/auth-tools-phase2/venv/bin/python',
    String? script,
    String home = '/home/chatbot/wainak-dev/mobile-tools/home',
  }) async {
    final selectedScript = await resolveFixtureScript(explicit: script);
    final Process process;
    try {
      process = await Process.start(
        python,
        [selectedScript.path, '--run-disposable-identity-fixture'],
        includeParentEnvironment: false,
        environment: {
          'HOME': home,
          'PATH': '/usr/bin:/bin',
          'LANG': 'C.UTF-8',
          'PYTHONDONTWRITEBYTECODE': '1',
          'PYTHONUNBUFFERED': '1',
        },
      );
    } catch (_) {
      throw const FixtureFailure('start_failed');
    }
    final bridge = IdentityFixtureBridge._(process, selectedScript);
    bridge._listen();
    try {
      final ready = await bridge._ready.future.timeout(
        const Duration(seconds: 120),
      );
      if (ready['type'] != 'ready' ||
          ready['mode'] != 'identity_fixture' ||
          ready['private_mailbox'] != true ||
          ready['base_url'] is! String)
        throw const FixtureFailure('invalid_ready');
      final uri = Uri.tryParse(ready['base_url'] as String);
      if (uri == null ||
          uri.scheme != 'http' ||
          uri.host != '127.0.0.1' ||
          !uri.hasPort ||
          uri.port <= 0 ||
          uri.userInfo.isNotEmpty ||
          uri.path.isNotEmpty ||
          uri.hasQuery ||
          uri.hasFragment)
        throw const FixtureFailure('invalid_origin');
      bridge.baseUri = uri;
      return bridge;
    } catch (_) {
      await bridge.abort();
      throw const FixtureFailure('readiness_failed');
    }
  }

  void _message(Map<String, dynamic> data) {
    if (data['type'] == 'ready' && !_ready.isCompleted) {
      _ready.complete(data);
      return;
    }
    if (data['type'] == 'closed' && !_closed.isCompleted) {
      _closed.complete(data);
      return;
    }
    final id = data['id'];
    if (id is int && _requests.containsKey(id)) {
      _requests.remove(id)!.complete(data);
      return;
    }
    _protocol.outputError();
  }

  void _listen() {
    _protocol = PrivateFixtureProtocol(
      onMessage: _message,
      onFailure: _failProtocol,
    );
    _output = _process.stdout.listen(
      _protocol.addOutput,
      onError: (_) {
        _protocol.outputError();
      },
      onDone: () {
        _protocol.finishOutput();
        if (!_ready.isCompleted)
          _ready.completeError(const FixtureFailure('closed_before_ready'));
        if (!_closed.isCompleted) _closed.complete({'cleanup_verified': false});
        if (!_outputDone.isCompleted) _outputDone.complete();
      },
    );
    _errors = _process.stderr.listen(
      _protocol.addErrorOutput,
      onError: (_) {
        _protocol.outputError();
      },
      onDone: () {
        _protocol.finishErrors();
        if (!_errorsDone.isCompleted) _errorsDone.complete();
      },
    );
    unawaited(
      _process.stdin.done.then<void>(
        (_) {},
        onError: (Object _, StackTrace __) {},
      ),
    );
  }

  void _failProtocol() {
    _protocolFailed = true;
    if (!_ready.isCompleted)
      _ready.completeError(const FixtureFailure('private_protocol_failed'));
    for (final request in _requests.values) {
      if (!request.isCompleted)
        request.complete({'ok': false, 'error': 'private_protocol_failed'});
    }
    _requests.clear();
  }

  Future<Map<String, dynamic>> _command(Map<String, dynamic> data) async {
    if (_finished || _protocolFailed || _nextId >= 256)
      throw const FixtureFailure('unavailable');
    final id = ++_nextId;
    final response = Completer<Map<String, dynamic>>();
    _requests[id] = response;
    try {
      _process.stdin.writeln(jsonEncode({'id': id, ...data}));
      await _process.stdin.flush();
      final result = await response.future.timeout(const Duration(seconds: 10));
      if (_protocolFailed)
        throw const FixtureFailure('private_protocol_failed');
      return result;
    } catch (_) {
      throw const FixtureFailure('private_command_failed');
    } finally {
      _requests.remove(id);
    }
  }

  Future<({String code, int sequence})> verification(
    String email, {
    int after = 0,
  }) async {
    // Only verification-purpose values are exposed to this phase's auth tests.
    if (!RegExp(
          r'^[a-z0-9][a-z0-9._-]{0,63}@example\.invalid$',
        ).hasMatch(email) ||
        after < 0)
      throw const FixtureFailure('invalid_mail_request');
    final result = await _command({
      'op': 'mail',
      'email': email,
      'purpose': 'verify',
      'after': after,
    });
    if (result['ok'] != true ||
        result['value'] is! String ||
        result['sequence'] is! int ||
        result['sequence'] <= after)
      throw const FixtureFailure('mail_not_ready');
    return (
      code: result['value'] as String,
      sequence: result['sequence'] as int,
    );
  }

  Future<void> shutdown() async {
    if (_finished) return;
    try {
      final acknowledgement = await _command({'op': 'shutdown'});
      if (acknowledgement['ok'] != true || acknowledgement['stopping'] != true)
        throw const FixtureFailure('shutdown_rejected');
      final terminal = await _closed.future.timeout(
        const Duration(seconds: 120),
      );
      final exit = await _process.exitCode.timeout(
        const Duration(seconds: 120),
      );
      await Future.wait([
        _outputDone.future,
        _errorsDone.future,
      ]).timeout(const Duration(seconds: 10));
      if (_protocolFailed ||
          !_protocol.terminalStreamComplete ||
          exit != 0 ||
          terminal['cleanup_verified'] != true ||
          terminal['checks_passed'] != true ||
          terminal['reason'] != 'shutdown')
        throw const FixtureFailure('cleanup_not_verified');
      _finished = true;
      await _cancelStreams();
    } catch (_) {
      await abort();
      throw const FixtureFailure('normal_shutdown_unverified');
    }
  }

  Future<void> abort() async {
    if (_finished) return;
    try {
      await _process.stdin.close();
    } catch (_) {}
    try {
      await _process.exitCode.timeout(const Duration(seconds: 120));
    } on TimeoutException {
      _process.kill(ProcessSignal.sigterm);
      try {
        await _process.exitCode.timeout(const Duration(seconds: 120));
      } on TimeoutException {
        throw const FixtureFailure('owned_child_audit_required');
      }
    }
    _finished = true;
    await _cancelStreams();
    // Abnormal cleanup is not counted as a passing normal journey.
  }

  Future<void> _cancelStreams() async {
    try {
      await _process.stdin.close();
    } catch (_) {}
    await _output?.cancel();
    await _errors?.cancel();
  }
}
