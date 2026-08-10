# Foot Measure Lab (Flutter)

Camera UI with Ready validation + automatic LiDAR/AR depth on compatible phones.

```bash
# from repo root
uvicorn server:app --host 0.0.0.0 --port 8000

cd mobile
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # Android emulator (no LiDAR)
# Physical phone (required for Depth / LiDAR):
flutter run --dart-define=API_BASE_URL=http://<LAN-IP>:8000
```

## Depth / LiDAR

| Device | Path |
|---|---|
| iPhone/iPad with LiDAR | ARKit scene depth (automatic) |
| Android with ARCore depth | ARCore depth image (automatic) |
| Browser / emulator / no LiDAR | Not supported — use Credit card mode |

In the app: choose **Depth / LiDAR** → if the pill says **LiDAR ready**, tap **Capture**. RGB + depth upload together; no manual file.

Release build example:

```bash
flutter build apk --dart-define=API_BASE_URL=https://YOUR-API.onrender.com
flutter build ipa --dart-define=API_BASE_URL=https://YOUR-API.onrender.com
```
