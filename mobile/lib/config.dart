import 'package:flutter/foundation.dart' show kIsWeb;

/// Backend base URL for validate + measure APIs.
///
/// Override at build/run time:
///   --dart-define=API_BASE_URL=http://127.0.0.1:8000
///
/// Defaults when unset:
///   Web / desktop → http://127.0.0.1:8000
///   Android emulator → http://10.0.2.2:8000
///   Physical phone → set API_BASE_URL to your PC LAN IP or Render URL
const String _apiBaseUrlDefine = String.fromEnvironment('API_BASE_URL');

String get apiBaseUrl {
  if (_apiBaseUrlDefine.isNotEmpty) return _apiBaseUrlDefine;
  if (kIsWeb) return 'http://127.0.0.1:8000';
  // Mobile (Android emulator special alias; iOS sim also often uses 127.0.0.1 —
  // pass dart-define on iOS if needed).
  return 'http://10.0.2.2:8000';
}

/// When true, show card / both / depth lab modes. Production default is A4 only.
const bool labModes = bool.fromEnvironment(
  'LAB_MODES',
  defaultValue: false,
);
