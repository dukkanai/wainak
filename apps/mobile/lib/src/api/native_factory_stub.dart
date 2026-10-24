import 'transport.dart';

ApiTransport createNativeTransport() => throw UnsupportedError(
  'Connected development mode requires a native transport; web stays disabled.',
);
