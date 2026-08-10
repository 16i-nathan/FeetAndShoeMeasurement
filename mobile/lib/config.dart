/// Backend base URL for validate + measure APIs.
///
/// Android emulator → host machine: `http://10.0.2.2:8000`
/// iOS simulator → `http://127.0.0.1:8000`
/// Physical device → `http://192.168.x.x:8000` or your Render HTTPS URL
/// Set at build time, e.g.:
/// flutter build apk --dart-define=API_BASE_URL=https://foot-measure-lab.onrender.com
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

/// When true, show card / both / depth lab modes. Production default is A4 only.
const bool labModes = bool.fromEnvironment(
  'LAB_MODES',
  defaultValue: false,
);
