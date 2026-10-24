import 'dart:convert';
import 'dart:io';
import 'private_fixture_protocol.dart';

void check(bool value, String label) {
  if (!value) throw StateError(label);
}

void main() {
  var passed = 0;
  void test(String name, void Function() body) {
    try {
      body();
      passed++;
      stdout.writeln('PASS $name');
    } catch (_) {
      throw StateError('FAIL $name (private bytes suppressed)');
    }
  }

  test('fragmented complete records wait for both streams', () {
    var count = 0;
    final parser = PrivateFixtureProtocol(
      onMessage: (_) {
        count++;
      },
      onFailure: () {},
    );
    final bytes = utf8.encode('{"type":"ready"}\n{"type":"closed"}\n');
    for (final byte in bytes) {
      parser.addOutput([byte]);
    }
    check(
      count == 2 && !parser.failed && !parser.terminalStreamComplete,
      'records before drain',
    );
    parser.finishOutput();
    parser.finishErrors();
    check(parser.terminalStreamComplete, 'drained transcript');
  });
  test(
    'Arabic UTF8 split across chunks is decoded only after bounded newline',
    () {
      var correct = false;
      final parser = PrivateFixtureProtocol(
        onMessage: (m) {
          correct = m['value'] == 'رمز اصطناعي';
        },
        onFailure: () {},
      );
      for (final byte in utf8.encode(
        '${jsonEncode({'id': 1, 'value': 'رمز اصطناعي'})}\n',
      )) {
        parser.addOutput([byte]);
      }
      check(
        correct && !parser.failed && parser.bufferedBytes == 0,
        'UTF8 chunk boundaries',
      );
    },
  );
  test(
    'oversize without newline fails immediately and retains no private bytes',
    () {
      var failures = 0, count = 0;
      final parser = PrivateFixtureProtocol(
        onMessage: (_) {
          count++;
        },
        onFailure: () {
          failures++;
        },
      );
      parser.addOutput(List<int>.filled(4096, 65));
      check(
        parser.failed &&
            failures == 1 &&
            count == 0 &&
            parser.bufferedBytes == 0,
        'bounded allocation',
      );
      parser.addOutput(List<int>.filled(8192, 66));
      check(
        failures == 1 && parser.bufferedBytes == 0,
        'discard after failure',
      );
    },
  );
  test('trailing JSON after closed invalidates successful terminal status', () {
    final parser = PrivateFixtureProtocol(onMessage: (_) {}, onFailure: () {});
    parser.addOutput(
      utf8.encode('{"type":"closed","cleanup_verified":true}\n'),
    );
    parser.addOutput(utf8.encode('{"id":99,"ok":true}\n'));
    parser.finishOutput();
    parser.finishErrors();
    check(
      parser.failed && !parser.terminalStreamComplete,
      'trailing protocol rejected',
    );
  });
  test('nonempty stderr and malformed final line fail without diagnostics', () {
    final parser = PrivateFixtureProtocol(onMessage: (_) {}, onFailure: () {});
    parser.addOutput(utf8.encode('{"type":"closed"}\n'));
    parser.addErrorOutput([88]);
    parser.finishOutput();
    parser.finishErrors();
    check(parser.failed && !parser.terminalStreamComplete, 'stderr rejected');
    final unfinished = PrivateFixtureProtocol(
      onMessage: (_) {},
      onFailure: () {},
    );
    unfinished.addOutput([123]);
    unfinished.finishOutput();
    check(unfinished.failed, 'unterminated record');
  });
  stdout.writeln('PRIVATE_PROTOCOL_CHECKS_PASSED=$passed');
}
