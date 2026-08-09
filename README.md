# FeetAndShoeMeasurement

Measure foot length from a phone photo using a **credit card** or **A4 paper** as scale (classical CV, no deep learning required).

## Flutter app (primary UI)

```bash
# 1) Start the measurement API
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000

# 2) Run the mobile app
cd mobile
flutter pub get

# Android emulator (API → host machine):
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000

# Physical phone on same Wi‑Fi (replace with your PC IP):
flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000

# iOS simulator:
flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

App flow:
1. Camera opens → status **Aligning…** / **Ready**
2. Tap **Capture**
3. Measurement runs in the background on the API
4. Shows cm + approx EU / US sizes

Modes: **credit card** (recommended), A4 paper, paper + card.

> Browsers / Flutter `camera` cannot read iPhone LiDAR depth. For reliable sizing without depth files, use a **credit card** in frame.

## Deploy API (always-on)

Repo includes `Dockerfile` + `render.yaml`.

1. Deploy this repo as a **Docker web service** on [Render](https://dashboard.render.com) (Blueprint or Web Service)
2. Point the Flutter app at the HTTPS URL:

```bash
flutter run --dart-define=API_BASE_URL=https://YOUR-SERVICE.onrender.com
```

Health check: `GET /api/health`

## CLI (optional)

```bash
python main.py data/barefeet1.jpeg --ref paper
python main.py data/photo.jpg --ref card
```

## How it works

* Convert image → HSV, blur, k-means color segmentation
* Detect paper or credit-card rectangle (known real-world size)
* Find foot bounding region and convert pixels → cm

## Assumptions

* Top-down photo, full foot visible
* Card or A4 fully visible when used as reference
* Floor not white (helps segmentation)

## Shoe size chart

Length is returned in cm; compare with `images/ShoeSizeChart.png` or the in-app approx sizes.

## License

See `LICENSE`.
