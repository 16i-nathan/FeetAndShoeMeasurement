# Manual QA — run before shipping an APK

## Setup
1. Charge phone above 20% (low battery can throttle camera/CPU).
2. Start API (or use always-on Render URL).
3. Install release APK built with production `API_BASE_URL`.

## Capture protocol
1. Dark non-white floor, soft even light, flash off.
2. Full blank A4 sheet flat; foot fully on paper (heel + toes).
3. Phone parallel to floor (true top-down); all four paper corners in frame.
4. Wait until all chips are green (Light, Focus, No glare, Paper, Full frame, Foot, Tilt).
5. Tap Capture — app takes 3 stills and shows median ± spread.

## Repeatability gate (release)
Same foot, same setup, **5 captures**:
- Record the five displayed lengths (0.5 cm steps).
- Median of the five should lie within **±5 mm** of a ruler measurement.
- Max−min across the five should be **≤ 10 mm**.
- If confidence is often low or ± spread ≥ 0.5 cm, improve lighting/angle and retest.

## Failures to watch
- No more `takePicture was called before the previous capture returned`.
- Ready chips must turn red when paper/foot missing (not all-green with error text).
- Non-paper modes are hidden unless `LAB_MODES=true`.

## Sign-off
- [ ] Health `/api/health` shows `ok: true`
- [ ] 5-repeat gate passed
- [ ] Result shows 0.5 cm rounding + optional preview
- [ ] APK points at production API
