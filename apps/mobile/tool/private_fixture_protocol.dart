import 'dart:convert';

/// Bounded test-only private stream parser. No protocol bytes are logged or
/// embedded in exceptions. Receiving a closed record is not resource proof;
/// the caller must still check its fields, stream completion and process exit.
class PrivateFixtureProtocol {
  PrivateFixtureProtocol({required this.onMessage, required this.onFailure});
  final void Function(Map<String, dynamic>) onMessage;
  final void Function() onFailure;
  static const maxLineBytes = 4096;
  final _line = <int>[];
  bool failed = false,
      closedSeen = false,
      outputDone = false,
      errorDone = false;
  int get bufferedBytes => _line.length;
  bool get terminalStreamComplete =>
      closedSeen && outputDone && errorDone && !failed;
  void _fail() {
    _line.clear();
    if (!failed) {
      failed = true;
      onFailure();
    }
  }

  void addOutput(List<int> chunk) {
    for (final byte in chunk) {
      if (failed)
        continue; // Drain/discard malformed private output without retaining it.
      if (byte == 10) {
        if (closedSeen) {
          _fail();
          continue;
        }
        try {
          final value = jsonDecode(utf8.decode(_line));
          _line.clear();
          if (value is! Map<String, dynamic>) {
            _fail();
            continue;
          }
          if (value['type'] == 'closed') closedSeen = true;
          onMessage(value);
        } catch (_) {
          _fail();
        }
      } else if (_line.length >= maxLineBytes - 1) {
        _fail();
      } else {
        _line.add(byte);
      }
    }
  }

  void addErrorOutput(List<int> bytes) {
    if (bytes.isNotEmpty) _fail();
  }

  void outputError() => _fail();
  void finishOutput() {
    if (_line.isNotEmpty) _fail();
    outputDone = true;
  }

  void finishErrors() {
    errorDone = true;
  }
}
