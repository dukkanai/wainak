import 'transport.dart';
import 'transport_io.dart';

ApiTransport createNativeTransport({
  Duration timeout = const Duration(seconds: 15),
}) => NativeApiTransport(timeout: timeout);
