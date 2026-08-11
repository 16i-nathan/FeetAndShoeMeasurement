#!/usr/bin/env bash
# Build a release APK wired to your hosted API.
# Usage:
#   ./scripts/build_apk.sh https://nikonyx-web.genius.rw
set -euo pipefail

API_URL="${1:-}"
if [[ -z "$API_URL" ]]; then
  echo "Usage: $0 https://YOUR-HOSTED-API"
  exit 1
fi

# strip trailing slash
API_URL="${API_URL%/}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/mobile"

echo "Building APK with API_BASE_URL=$API_URL"
echo "  Modes: A4 + Depth (LAB_MODES=false → no card/both lab modes)"
flutter pub get
flutter build apk --release \
  --dart-define="API_BASE_URL=$API_URL" \
  --dart-define=LAB_MODES=false

OUT="$ROOT/mobile/build/app/outputs/flutter-apk/app-release.apk"
echo ""
echo "APK ready:"
echo "  $OUT"
ls -lh "$OUT"
