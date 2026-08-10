"""Fast readiness checks for live camera frames — gates bad submissions."""

from __future__ import annotations

import cv2
import numpy as np

from utils import find_credit_card


def _brightness(gray: np.ndarray) -> float:
    return float(np.mean(gray))


def _sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _white_ratio(rgb: np.ndarray) -> float:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = (hsv[:, :, 2] > 180) & (hsv[:, :, 1] < 60)
    return float(np.mean(mask))


def _glare_ratio(gray: np.ndarray) -> float:
    """Strong flash / specular hotspots."""
    return float(np.mean(gray > 245))


def _border_touch_ratio(mask: np.ndarray, border: int = 4) -> float:
    """How much of a binary mask touches the frame border (crop risk)."""
    if mask is None or mask.size == 0 or not np.any(mask):
        return 1.0
    h, w = mask.shape[:2]
    edge = np.zeros_like(mask, dtype=bool)
    edge[:border, :] = True
    edge[-border:, :] = True
    edge[:, :border] = True
    edge[:, -border:] = True
    touch = np.logical_and(mask > 0, edge)
    return float(np.sum(touch) / max(np.sum(mask > 0), 1))


def validate_frame(rgb: np.ndarray, mode: str = 'card') -> dict:
    if rgb is None or rgb.size == 0:
        return {
            'ready': False,
            'score': 0.0,
            'checks': {'frame': False},
            'hints': ['No camera frame'],
            'message': 'Waiting for camera…',
            'errors': ['NO_FRAME'],
        }

    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bright = _brightness(gray)
    sharp = _sharpness(gray)
    white = _white_ratio(rgb)
    glare = _glare_ratio(gray)

    checks = {
        'brightness': 55 <= bright <= 200,
        'sharpness': sharp >= 40.0,
        'no_glare': glare < 0.02,
        'reference': False,
        'full_frame': False,
        'content': False,
    }
    hints: list[str] = []
    errors: list[str] = []

    if bright < 55:
        hints.append('Too dark — move to softer, brighter light (no flash)')
        errors.append('SHADOW')
    elif bright > 200:
        hints.append('Too bright — reduce glare / turn off flash')
        errors.append('GLARE')
    if not checks['sharpness']:
        hints.append('Hold steadier — image looks blurry')
        errors.append('BLUR')
    if not checks['no_glare']:
        hints.append('Flash glare detected — turn flash off, tilt slightly')
        errors.append('GLARE')
        checks['no_glare'] = False

    detail = {
        'brightness': round(bright, 1),
        'sharpness': round(sharp, 1),
        'white_ratio': round(white, 3),
        'glare_ratio': round(glare, 4),
    }

    # Content / subject presence via center edges
    edges = cv2.Canny(gray, 40, 120)
    cy0, cy1 = int(h * 0.12), int(h * 0.92)
    cx0, cx1 = int(w * 0.1), int(w * 0.9)
    center_edge = float(np.mean(edges[cy0:cy1, cx0:cx1] > 0))
    detail['center_edge'] = round(center_edge, 4)
    checks['content'] = center_edge >= 0.008
    if not checks['content']:
        hints.append('Center the full foot in the frame (top-down)')
        errors.append('CROP')

    if mode in ('card', 'both'):
        try:
            box, _rect, score = find_credit_card(
                gray, min_area_ratio=0.004, aspect_tol=0.12
            )
            checks['reference'] = score >= 1.5
            detail['card_score'] = round(float(score), 2)
            detail['card_box'] = [int(v) for v in box]
            x, y, bw, bh = box
            # Card must not be clipped by frame edge
            margin = 6
            clipped = (
                x <= margin
                or y <= margin
                or x + bw >= w - margin
                or y + bh >= h - margin
            )
            checks['full_frame'] = not clipped and checks['content']
            if clipped:
                hints.append('Keep the full credit card inside the frame')
                errors.append('CROP')
            if not checks['reference']:
                hints.append('Show a full credit card flat beside the foot')
                errors.append('NO_CARD')
        except ValueError:
            checks['reference'] = False
            checks['full_frame'] = False
            hints.append('Place a credit card fully visible beside the foot')
            errors.append('NO_CARD')

        if mode == 'both' and white < 0.08:
            checks['reference'] = False
            hints.append('Include the full A4 sheet as well as the card')
            errors.append('NO_PAPER')

    elif mode == 'paper':
        checks['reference'] = white >= 0.14
        # Approximate paper mask = bright pixels; reject if touching borders heavily
        paper_mask = ((cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 2] > 180)
                      & (cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1] < 60))
        touch = _border_touch_ratio(paper_mask.astype(np.uint8) * 255, border=5)
        detail['paper_border_touch'] = round(touch, 3)
        checks['full_frame'] = touch < 0.12 and checks['content']
        if not checks['reference']:
            hints.append('Show the full white A4 sheet in frame')
            errors.append('NO_PAPER')
        if touch >= 0.12:
            hints.append('Paper looks cropped — step back so all corners are visible')
            errors.append('CROP')

    else:  # depth
        checks['reference'] = True  # depth sensor supplies scale
        # Prefer subject not glued to borders
        subject = (edges > 0).astype(np.uint8) * 255
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        subject = cv2.morphologyEx(subject, cv2.MORPH_CLOSE, ker, iterations=2)
        touch = _border_touch_ratio(subject, border=4)
        detail['subject_border_touch'] = round(touch, 3)
        checks['full_frame'] = touch < 0.18 and checks['content']
        if not checks['full_frame']:
            hints.append('Keep the entire foot inside the frame (no cropped toes/heel)')
            errors.append('CROP')

    # Floor contrast: reject near-white floors for RGB modes
    if mode != 'depth':
        border = np.concatenate([
            gray[:8, :].ravel(), gray[-8:, :].ravel(),
            gray[:, :8].ravel(), gray[:, -8:].ravel(),
        ])
        floor_med = float(np.median(border))
        detail['floor_median'] = round(floor_med, 1)
        checks['contrast'] = floor_med < 170
        if not checks['contrast']:
            hints.append('Use a darker floor — white/light floors break detection')
            errors.append('WHITE_FLOOR')
    else:
        checks['contrast'] = True

    ready = all([
        checks['brightness'],
        checks['sharpness'],
        checks['no_glare'],
        checks['reference'],
        checks['full_frame'],
        checks['content'],
        checks.get('contrast', True),
    ])

    score = sum(1.0 for k in (
        'brightness', 'sharpness', 'no_glare', 'reference', 'full_frame', 'content', 'contrast'
    ) if checks.get(k)) / 7.0

    if ready:
        message = 'Ready — hold still, then capture'
    else:
        message = hints[0] if hints else 'Adjust framing'

    # Unique errors, keep order
    seen = set()
    uniq_errors = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            uniq_errors.append(e)

    return {
        'ready': bool(ready),
        'score': round(score, 2),
        'checks': checks,
        'hints': hints[:4],
        'errors': uniq_errors[:5],
        'detail': detail,
        'message': message,
    }
