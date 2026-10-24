abstract interface class ApiTransport {
  Future<ApiResponse> send(
    String method,
    Uri uri,
    Map<String, String> headers,
    String? body,
  );
  void close();
}

class ApiResponse {
  const ApiResponse(this.statusCode, this.body);
  final int statusCode;
  final String body;
}
