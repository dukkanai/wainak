import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'transport.dart';

/// Bounded, redirect-free native development transport. No credential logs.
class NativeApiTransport implements ApiTransport {
  final Set<HttpClient> _active = {};
  bool _closed = false;
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) async {
    if (_closed) throw StateError('Transport closed');
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 10);
    _active.add(client);
    Future<ApiResponse> perform() async {
      final request = await client.openUrl(method, uri);
      request.followRedirects = false;
      headers.forEach(request.headers.set);
      final payload = body == null ? <int>[] : utf8.encode(body);
      request.contentLength = payload.length;
      if (payload.isNotEmpty) request.add(payload);
      final response = await request.close();
      final bytes = <int>[];
      await for (final chunk in response) {
        bytes.addAll(chunk);
        if (bytes.length > 65536)
          throw const FormatException('response_too_large');
      }
      return ApiResponse(response.statusCode, utf8.decode(bytes));
    }

    try {
      return await perform().timeout(
        const Duration(seconds: 15),
        onTimeout: () {
          client.close(force: true);
          throw TimeoutException('Development request timeout');
        },
      );
    } finally {
      _active.remove(client);
      client.close(force: true);
    }
  }

  @override
  void close() {
    _closed = true;
    for (final client in _active) {
      client.close(force: true);
    }
    _active.clear();
  }
}
