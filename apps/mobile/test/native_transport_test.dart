import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:wainek_mobile/src/api/transport_io.dart';

void main() {
  test(
    'native request uses UTF-8 byte Content-Length, never chunked',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final transport = NativeApiTransport();
      final payload = jsonEncode({'text': 'السلام عليكم'});
      final handled = server.first.then((request) async {
        expect(request.headers.contentLength, utf8.encode(payload).length);
        expect(
          request.headers.value(HttpHeaders.transferEncodingHeader),
          isNull,
        );
        expect(await utf8.decoder.bind(request).join(), payload);
        request.response.headers.contentType = ContentType.json;
        request.response.write('{"accepted":true}');
        await request.response.close();
      });
      try {
        final result = await transport.send(
          'POST',
          Uri.parse('http://127.0.0.1:${server.port}/utf8'),
          {'Content-Type': 'application/json'},
          payload,
        );
        expect(result.statusCode, 200);
        await handled.timeout(const Duration(seconds: 5));
      } finally {
        transport.close();
        await server.close(force: true);
      }
    },
  );
}
