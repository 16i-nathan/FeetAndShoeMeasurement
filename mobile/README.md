# Foot Measure Lab (Flutter)

Camera UI with Ready validation. Talks to the Python API in the repo root.

```bash
# from repo root
uvicorn server:app --host 0.0.0.0 --port 8000

cd mobile
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # Android emulator
# flutter run --dart-define=API_BASE_URL=http://<LAN-IP>:8000 # physical device
```

Release build example:

```bash
flutter build apk --dart-define=API_BASE_URL=https://YOUR-API.onrender.com
```
