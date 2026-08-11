"""AI-only A4 foot measure: vision model returns length in cm directly.

No local homography / heel-toe math for the reported number.
No masked preview overlay — result is numeric (+ optional notes JSON).
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import cv2
import httpx
import numpy as np

from depth_measure import assert_plausible_foot_cm
from ml_measure import MeasureError
from quality import order_corners
from shoe_size import sizes_from_cm

ROOT = Path(__file__).resolve().parent

DEFAULT_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash').strip()
GEMINI_TIMEOUT_S = float(os.environ.get('GEMINI_TIMEOUT_S', '60'))

MODEL_FALLBACKS = [
    DEFAULT_MODEL,
    'gemini-2.5-flash',
    'gemini-2.5-flash-lite',
    'gemini-2.0-flash',
    'gemini-1.5-flash',
]

RESULT_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'length_cm': {
            'type': 'NUMBER',
            'description': (
                'Foot length in centimeters from heel to longest toe, '
                'using the blank A4 sheet (210×297 mm) as the scale reference'
            ),
        },
        'confidence': {
            'type': 'NUMBER',
            'description': '0..1 confidence in length_cm',
        },
        'notes': {'type': 'STRING'},
    },
    'required': ['length_cm', 'confidence'],
}

PROMPT = """You measure a bare human foot on a blank A4 paper sheet in a top-down phone photo.

A4 is exactly 210 mm × 297 mm. Use that sheet as your only scale reference.

Return ONLY JSON matching the schema.
- length_cm: foot length in centimeters from the back of the heel pad to the tip of
  the LONGEST toe (same as a Brannock / ruler measurement). One decimal is fine.
- confidence: 0..1 how sure you are.
- notes: short reason if confidence is low.

Rules:
- Adult feet are typically about 22–31 cm. Kids can be shorter.
- Measure the full foot on the paper, not the ankle or pant cuff.
- If the photo is bad (cropped, extreme angle, flash glare), lower confidence
  and still give your best length_cm estimate.
"""


def gemini_configured() -> bool:
    return bool(os.environ.get('GEMINI_API_KEY', '').strip())


def gemini_model_name() -> str:
    return DEFAULT_MODEL or 'gemini-2.5-flash'


_LAST_USED_MODEL: str | None = None


def last_used_model() -> str:
    return _LAST_USED_MODEL or gemini_model_name()


def _encode_jpeg(rgb: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(
        '.jpg',
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        [int(cv2.IMWRITE_JPEG_QUALITY), quality],
    )
    if not ok:
        raise MeasureError('ENCODE', 'Could not encode image for AI measure')
    return buf.tobytes()


def _parse_json_text(text: str) -> dict:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    return json.loads(text)


def _norm_to_px(pt, w: int, h: int) -> np.ndarray | None:
    try:
        x, y = float(pt[0]), float(pt[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        if 0 <= x < w and 0 <= y < h:
            return np.array([x, y], dtype=np.float32)
        return None
    return np.array([x * (w - 1), y * (h - 1)], dtype=np.float32)


def _model_candidates() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in MODEL_FALLBACKS:
        name = (m or '').strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _friendly_http_error(status: int, body: str) -> str:
    lower = body.lower()
    if status == 404 or 'not found' in lower:
        return (
            'AI model not available for this API key. '
            'Set GEMINI_MODEL=gemini-2.5-flash (or another enabled model).'
        )
    if status in (401, 403) or 'api key' in lower or 'permission' in lower:
        return 'AI API key invalid or missing permission. Check GEMINI_API_KEY.'
    if status == 429 or 'quota' in lower or 'rate' in lower:
        return 'AI quota exceeded — try again later.'
    return f'AI request failed (HTTP {status}).'


def call_gemini_length_cm(rgb: np.ndarray) -> dict:
    global _LAST_USED_MODEL
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        raise MeasureError(
            'NO_GEMINI_KEY',
            'Set GEMINI_API_KEY on the API server to use AI measure.',
        )

    jpeg = _encode_jpeg(rgb)
    b64 = base64.b64encode(jpeg).decode('ascii')
    payload = {
        'contents': [
            {
                'role': 'user',
                'parts': [
                    {'text': PROMPT},
                    {'inline_data': {'mime_type': 'image/jpeg', 'data': b64}},
                ],
            }
        ],
        'generationConfig': {
            'temperature': 0.1,
            'responseMimeType': 'application/json',
            'responseSchema': RESULT_SCHEMA,
        },
    }

    last_error: MeasureError | None = None
    used_model = None
    body = None
    for model in _model_candidates():
        url = (
            f'https://generativelanguage.googleapis.com/v1beta/models/'
            f'{model}:generateContent'
        )
        try:
            with httpx.Client(timeout=GEMINI_TIMEOUT_S) as client:
                res = client.post(url, params={'key': api_key}, json=payload)
        except httpx.HTTPError as e:
            last_error = MeasureError('GEMINI_NET', f'AI request failed: {e}')
            continue

        if res.status_code == 404:
            last_error = MeasureError(
                'GEMINI_HTTP',
                _friendly_http_error(res.status_code, res.text),
            )
            continue
        if res.status_code >= 400:
            raise MeasureError(
                'GEMINI_HTTP',
                _friendly_http_error(res.status_code, res.text),
            )
        used_model = model
        body = res.json()
        break

    if body is None:
        raise last_error or MeasureError(
            'GEMINI_HTTP',
            'AI model not available. Set GEMINI_MODEL to an enabled model.',
        )

    _LAST_USED_MODEL = used_model or gemini_model_name()

    try:
        text = body['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError, TypeError) as e:
        raise MeasureError('GEMINI_EMPTY', 'AI returned no measurement JSON') from e

    try:
        data = _parse_json_text(text)
    except json.JSONDecodeError as e:
        raise MeasureError('GEMINI_JSON', f'Invalid AI JSON: {e}') from e

    if 'length_cm' not in data:
        raise MeasureError('GEMINI_SCHEMA', 'Missing length_cm from AI')
    return data


def length_mm_from_landmarks(
    corners_px: np.ndarray,
    heel_px: np.ndarray,
    toe_px: np.ndarray,
    px_per_mm: float = 2.0,
) -> float:
    """Kept for unit tests; not used by the AI-cm primary path."""
    from ml_measure import _a4_destination

    corners = order_corners(corners_px.astype(np.float32))
    dst = _a4_destination(px_per_mm)
    H = cv2.getPerspectiveTransform(corners, dst)
    pts = np.stack([heel_px, toe_px], axis=0).astype(np.float32).reshape(-1, 1, 2)
    warped = cv2.perspectiveTransform(pts, H).reshape(2, 2)
    dist_px = float(np.linalg.norm(warped[0] - warped[1]))
    return dist_px / px_per_mm


def measure_paper_gemini(
    rgb: np.ndarray,
    *,
    out_dir: Path | None = None,
    px_per_mm: float = 2.0,
) -> dict:
    """AI returns length_cm; that value is the measurement. No masked preview."""
    del px_per_mm  # unused — AI owns scale
    data = call_gemini_length_cm(rgb)
    try:
        length_cm = float(data['length_cm'])
    except (TypeError, ValueError) as e:
        raise MeasureError('GEMINI_SCHEMA', 'AI length_cm is not a number') from e

    conf = float(np.clip(float(data.get('confidence', 0.5)), 0.0, 1.0))
    try:
        cm = assert_plausible_foot_cm(length_cm)
    except ValueError as e:
        raise MeasureError('BAD_LENGTH', str(e)) from e

    method = 'ai_length_cm'
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'gemini_result.json').write_text(
            json.dumps(
                {
                    **data,
                    'cm': cm,
                    'method': method,
                    'model': last_used_model(),
                },
                indent=2,
            ),
            encoding='utf-8',
        )

    return {
        'cm': float(cm),
        'confidence': conf,
        'paper_score': conf,
        'foot_score': conf,
        'tilt': 0.0,
        'aspect_err': 0.0,
        'seg_source': f'gemini-cm:{last_used_model()}',
        'preview_path': None,
        'notes': data.get('notes') or '',
        'method': method,
    }


def pack_sizes(cm: float, confidence: float | None = None) -> dict:
    sizes = sizes_from_cm(cm)
    sizes['cm'] = round(cm * 2) / 2.0
    sizes['cm_raw'] = round(float(cm), 2)
    if confidence is not None:
        sizes['confidence'] = round(float(confidence), 3)
    return sizes
