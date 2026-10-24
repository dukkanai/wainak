import 'transport.dart';

ApiTransport createNativeTransport({
  Duration timeout = const Duration(seconds: 15),
}) => throw UnsupportedError(
  'Connected development mode requires a native transport; web stays disabled.',
);
