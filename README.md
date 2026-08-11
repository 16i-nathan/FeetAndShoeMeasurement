# FeetAndShoeMeasurement

Production foot-length measurement from a phone photo using an **A4 sheet** as scale (ML segmentation + perspective rectification).

## Flutter app (primary UI)

```bash
# 1) Start the measurement API
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Optional: train/export bootstrap ONNX weights
pip install -r requirements-train.txt
python -m training.train_seg
uvicorn server:app --host 0.0.0.0 --port 8000

# Optional: enable AI / Gemini length (method appears when key is set)
export GEMINI_API_KEY=your_key
# export GEMINI_MODEL=gemini-2.5-flash   # optional
# export GEMINI_TIMEOUT_S=60            # optional

# 2) Run the mobile app (A4-only by default)
cd mobile
flutter pub get

# Android emulator (API → host machine):
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000

# Physical phone on same Wi‑Fi (replace with your PC IP):
flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000

# Lab modes (card / both) — not for production:
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000 --dart-define=LAB_MODES=true
```

App flow:
1. Choose **A4 paper**, **Depth / LiDAR**, **AI / Gemini**, or **Compare** (AI methods appear when `/api/health` reports `gemini_configured`)
2. Guidelines → camera → **Aligning…** / **Ready**
3. Paper: preview-stream validation → **3-shot burst** → median length
4. Gemini: same A4 Ready checks → single still → cloud `length_cm` (no mask preview)
5. Compare: one still → local ML + Gemini together; enter **truth cm** on the result screen to score
6. Depth: always enabled on the API (`depth_enabled: true`). On a **LiDAR (iOS) or ARCore depth (Android)** phone, pick Depth — capture uses native depth automatically. Emulator / web: use A4.
7. Result shows cm (0.5 cm steps), confidence, shoe size approx; truth scores land in the analysis DB

**Analysis dashboard:** open `http://127.0.0.1:8000/dashboard` after the API is running. Export: `/api/analysis/export`. Data file: `output/analysis.sqlite3` (kept across job TTL cleanup).

## How it works (production)

* ONNX (or bootstrap) segmentation → paper + foot masks
* Paper corners → homography onto canonical A4 plane (210×297 mm)
* Foot length on the metric plane; reject low-confidence frames
* Shared quality gates for Ready and measure
* Optional Gemini path: vision model returns foot length in cm using A4 as scale
* Optional Compare: local + Gemini in one job; manual truth → error mm + 0..1 score

## Deploy API + build APK

### A) Host the backend (Render)

1. Open [https://dashboard.render.com](https://dashboard.render.com) → Blueprint → this repo
2. Prefer **starter** (always-on) — free tier sleeps and breaks mobile timeouts
3. Health: `https://YOUR-URL.onrender.com/api/health` → `model_loaded` / `ok` / `depth_enabled`
4. To enable AI + Compare, set secret `GEMINI_API_KEY` (optional `GEMINI_MODEL`, `GEMINI_TIMEOUT_S`)
5. Dashboard: `https://YOUR-URL.onrender.com/dashboard`

### B) Build the Android APK

```bash
./scripts/build_apk.sh https://foot-measure-lab.onrender.com
```

## Training / release gate

```bash
python -m training.train_seg          # synthetic bootstrap → models/paper_foot_seg.onnx
python -m training.eval_gate          # MAE / fail-rate report
pytest -q tests/
```

Manual phone QA: [docs/QA_CHECKLIST.md](docs/QA_CHECKLIST.md)

## CLI (optional)

```bash
python main.py data/barefeet1.jpeg --ref paper
python main.py data/barefeet1.jpeg --ref gemini   # needs GEMINI_API_KEY
```

## Assumptions

* Top-down photo, full foot on A4, all four corners visible
* Floor not white (helps paper contrast)
* Soft light, flash off

## License

See `LICENSE`.
