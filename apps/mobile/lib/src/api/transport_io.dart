import 'dart:convert';
import 'dart:io';
import 'transport.dart';

/// Explicitly constructed by development integration tooling, never by main().
class NativeApiTransport implements ApiTransport {
  NativeApiTransport()
    : _client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  final HttpClient _client;
  @override
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  ) async {
    final request = await _client
        .openUrl(method, uri)
        .timeout(const Duration(seconds: 10));
    request.followRedirects =
        false; // Never forward bearer credentials to another origin.
    headers.forEach(request.headers.set);
    if (body != null) request.write(body);
    final response = await request.close().timeout(const Duration(seconds: 10));
    final bytes = <int>[];
    await for (final chunk in response.timeout(const Duration(seconds: 10))) {
      bytes.addAll(chunk);
      if (bytes.length > 65536) {
        _client.close(force: true);
        throw const FormatException('response_too_large');
      }
    }
    return ApiResponse(response.statusCode, utf8.decode(bytes));
  }

  @override
  void close() => _client.close(force: true);
}
