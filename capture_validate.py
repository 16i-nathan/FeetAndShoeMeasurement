"""Fast readiness checks for live camera frames."""

from __future__ import annotations

import cv2
import numpy as np

from utils import find_credit_card


def _brightness(gray: np.ndarray) -> float:
    return float(np.mean(gray))


def _sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _white_ratio(rgb: np.ndarray) -> float:
    """Fraction of near-white pixels (A4 / card candidates)."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # high V, low S
    mask = (hsv[:, :, 2] > 180) & (hsv[:, :, 1] < 60)
    return float(np.mean(mask))


def validate_frame(rgb: np.ndarray, mode: str = 'card') -> dict:
    """
    Return readiness for a single RGB frame.
    Designed to run on downscaled frames (~480px long side).
    """
    if rgb is None or rgb.size == 0:
        return {
            'ready': False,
            'score': 0.0,
            'checks': {'frame': False},
            'hints': ['No camera frame'],
            'message': 'Waiting for camera…',
        }

    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bright = _brightness(gray)
    sharp = _sharpness(gray)
    white = _white_ratio(rgb)

    checks = {
        'brightness': 40 <= bright <= 210,
        'sharpness': sharp >= 25.0,
        'reference': False,
    }
    hints = []

    if not checks['brightness']:
        hints.append('Improve lighting (avoid dark or blown-out flash)')
    if not checks['sharpness']:
        hints.append('Hold steadier — image looks blurry')

    detail = {
        'brightness': round(bright, 1),
        'sharpness': round(sharp, 1),
        'white_ratio': round(white, 3),
    }

    if mode in ('card', 'both'):
        try:
            box, _rect, score = find_credit_card(gray, min_area_ratio=0.004, aspect_tol=0.12)
            checks['reference'] = score >= 1.4
            detail['card_score'] = round(float(score), 2)
            detail['card_box'] = [int(v) for v in box]
            if not checks['reference']:
                hints.append('Show a full credit card flat in the frame')
        except ValueError:
            checks['reference'] = False
            hints.append('Place a credit card fully visible beside the foot')
    elif mode == 'paper':
        # A4 should cover a sizable bright rectangle
        checks['reference'] = white >= 0.12
        if not checks['reference']:
            hints.append('Show the full white A4 sheet in frame')
    else:  # depth — RGB preview only; depth processed after capture
        checks['reference'] = True
        hints.append('Capture now — depth is processed in the background after shot')

    # Soft hint only — reference + focus/exposure are what gate Ready
    if mode != 'depth':
        edges = cv2.Canny(gray, 40, 120)
        cy0, cy1 = int(h * 0.15), int(h * 0.9)
        cx0, cx1 = int(w * 0.1), int(w * 0.9)
        center_edge = float(np.mean(edges[cy0:cy1, cx0:cx1] > 0))
        detail['center_edge'] = round(center_edge, 4)
        if center_edge < 0.004:
            hints.append('Point the camera at the foot (top-down)')

    ready = checks['brightness'] and checks['sharpness'] and checks['reference']

    score = (
        (0.3 if checks['brightness'] else 0.0)
        + (0.3 if checks['sharpness'] else 0.0)
        + (0.4 if checks['reference'] else 0.0)
    )

    if ready:
        message = 'Ready — hold still and capture'
    else:
        message = hints[0] if hints else 'Adjust framing'

    return {
        'ready': bool(ready),
        'score': round(score, 2),
        'checks': checks,
        'hints': hints[:3],
        'detail': detail,
        'message': message,
    }
