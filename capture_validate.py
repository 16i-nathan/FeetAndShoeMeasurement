"""Fast readiness checks for live camera frames — gates bad submissions.

Production path uses the same segmentation + geometry gates as measure.
"""

from __future__ import annotations

import os

import cv2
import numpy as np

from quality import (
    DEFAULT_THRESHOLDS,
    brightness,
    glare_ratio,
    sharpness,
)
from seg_infer import segment
from quality import evaluate_masks


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj


def validate_frame(rgb: np.ndarray, mode: str = 'paper') -> dict:
    if rgb is None or rgb.size == 0:
        return {
            'ready': False,
            'score': 0.0,
            'checks': {'frame': False},
            'hints': ['No camera frame'],
            'message': 'Waiting for camera…',
            'errors': ['NO_FRAME'],
        }

    thr = DEFAULT_THRESHOLDS
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bright = brightness(gray)
    sharp = sharpness(gray)
    glare = glare_ratio(gray)

    checks = {
        'brightness': thr.brightness_min <= bright <= thr.brightness_max,
        'sharpness': sharp >= thr.sharpness_min,
        'no_glare': glare < thr.glare_max,
        'reference': False,
        'full_frame': False,
        'content': False,
        'tilt': False,
    }
    hints: list[str] = []
    errors: list[str] = []
    detail = {
        'brightness': round(bright, 1),
        'sharpness': round(sharp, 1),
        'glare_ratio': round(glare, 4),
    }

    if bright < thr.brightness_min:
        hints.append('Too dark — move to softer, brighter light (no flash)')
        errors.append('SHADOW')
    elif bright > thr.brightness_max:
        hints.append('Too bright — reduce glare / turn off flash')
        errors.append('GLARE')
    if not checks['sharpness']:
        hints.append('Hold steadier — image looks blurry')
        errors.append('BLUR')
    if not checks['no_glare']:
        hints.append('Flash glare detected — turn flash off, tilt slightly')
        errors.append('GLARE')

    # Lab RGB modes when LAB_MODES=1
    lab = os.environ.get('LAB_MODES', '0') == '1'
    if mode in ('card', 'both') and lab:
        return _validate_lab_legacy(rgb, mode, checks, hints, errors, detail)

    if mode in ('card', 'both') and not lab:
        return {
            'ready': False,
            'score': 0.0,
            'checks': {k: bool(v) for k, v in checks.items()},
            'hints': ['Card modes require LAB_MODES=1'],
            'message': 'Use A4 paper or Depth mode',
            'errors': ['MODE'],
            'detail': detail,
        }

    if mode == 'depth':
        return _validate_depth(rgb, checks, hints, errors, detail, thr)

    if mode != 'paper':
        return {
            'ready': False,
            'score': 0.0,
            'checks': {k: bool(v) for k, v in checks.items()},
            'hints': ['Supported modes: paper, depth'],
            'message': 'Use A4 paper or Depth mode',
            'errors': ['MODE'],
            'detail': detail,
        }

    try:
        paper, foot, source = segment(rgb)
        geo = evaluate_masks(paper, foot, thr)
        detail['seg_source'] = source
        detail['paper_score'] = round(geo.paper_score, 3)
        detail['foot_score'] = round(geo.foot_score, 3)
        detail['confidence'] = round(geo.confidence, 3)
        detail['tilt'] = round(geo.tilt, 3)
        detail['aspect_err'] = round(geo.aspect_err, 3)
        detail['paper_coverage'] = round(geo.paper_coverage, 3)
        detail['foot_coverage'] = round(geo.foot_coverage, 3)
        detail['border_touch'] = round(geo.border_touch, 3)

        checks['reference'] = geo.paper_score >= thr.paper_score_min and geo.corners is not None
        checks['full_frame'] = geo.border_touch < thr.border_touch_max
        checks['content'] = (
            geo.foot_score >= thr.foot_score_min
            and 'PARTIAL_FOOT' not in geo.errors
            and 'NO_FOOT' not in geo.errors
        )
        checks['tilt'] = geo.tilt <= thr.tilt_max and geo.aspect_err <= thr.aspect_err_max

        for e in geo.errors:
            if e not in errors:
                errors.append(e)
        for h in geo.hints:
            if h not in hints:
                hints.append(h)

        # Ready only when geometry would pass measure (same gates)
        if not geo.ok:
            if 'HIGH_TILT' in geo.errors:
                checks['tilt'] = False
            if 'PARTIAL_FOOT' in geo.errors or 'NO_FOOT' in geo.errors:
                checks['content'] = False
            if 'NO_PAPER' in geo.errors or 'LOW_CONF' in geo.errors:
                checks['reference'] = False
            if 'CROP' in geo.errors:
                checks['full_frame'] = False
    except Exception as e:
        checks['reference'] = False
        checks['content'] = False
        checks['tilt'] = False
        checks['full_frame'] = False
        errors.append('LOW_CONF')
        hints.append(f'Segmentation unavailable: {e}')

    ready = all(checks[k] for k in (
        'brightness', 'sharpness', 'no_glare', 'reference', 'full_frame', 'content', 'tilt'
    ))

    score = sum(1.0 for k in checks if checks.get(k)) / max(len(checks), 1)

    if ready:
        message = 'Ready — hold still, then capture'
    else:
        # Prefer actionable hint; never claim Ready while chips fail
        message = hints[0] if hints else 'Adjust framing'

    seen = set()
    uniq_errors = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            uniq_errors.append(e)

    return _json_safe({
        'ready': bool(ready),
        'score': round(float(score), 2),
        'checks': {k: bool(v) for k, v in checks.items()},
        'hints': hints[:4],
        'errors': uniq_errors[:5],
        'detail': detail,
        'message': message,
    })


def _validate_depth(rgb, checks, hints, errors, detail, thr):
    """RGB heuristics for depth mode (scale comes from depth map at capture)."""
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    cy0, cy1 = int(h * 0.12), int(h * 0.92)
    cx0, cx1 = int(w * 0.1), int(w * 0.9)
    center_edge = float(np.mean(edges[cy0:cy1, cx0:cx1] > 0))
    detail['center_edge'] = round(center_edge, 4)

    checks['reference'] = True  # depth sensor supplies scale
    checks['content'] = center_edge >= 0.008
    if not checks['content']:
        hints.append('Center one full foot in the frame (top-down)')
        errors.append('CROP')

    subject = (edges > 0).astype(np.uint8) * 255
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    subject = cv2.morphologyEx(subject, cv2.MORPH_CLOSE, ker, iterations=2)
    from quality import border_touch_ratio
    touch = border_touch_ratio(subject, border=4)
    detail['subject_border_touch'] = round(touch, 3)
    checks['full_frame'] = touch < 0.18 and checks['content']
    if not checks['full_frame']:
        hints.append('Keep the entire foot inside the frame (no cropped toes/heel)')
        errors.append('CROP')

    cy0c, cy1c = int(h * 0.22), int(h * 0.82)
    cx0c, cx1c = int(w * 0.22), int(w * 0.78)
    center_mass = float(np.mean(subject[cy0c:cy1c, cx0c:cx1c] > 0))
    detail['center_mass'] = round(center_mass, 4)
    if center_mass < 0.04:
        checks['content'] = False
        hints.append('Center one full foot; clear cables/objects from the floor')
        errors.append('CLUTTER')

    ring = subject.copy()
    ring[cy0c:cy1c, cx0c:cx1c] = 0
    ring_mass = float(np.mean(ring > 0))
    detail['ring_mass'] = round(ring_mass, 4)
    if ring_mass > center_mass * 1.8 and ring_mass > 0.06:
        checks['content'] = False
        hints.append('Clear the floor — extra objects confuse foot detection')
        errors.append('CLUTTER')

    # Soft tilt proxy: prefer subject not extremely skewed — always allow for depth
    checks['tilt'] = True

    ready = all(checks[k] for k in (
        'brightness', 'sharpness', 'no_glare', 'reference', 'full_frame', 'content', 'tilt'
    ))
    return _json_safe({
        'ready': bool(ready),
        'score': round(sum(1.0 for v in checks.values() if v) / max(len(checks), 1), 2),
        'checks': {k: bool(v) for k, v in checks.items()},
        'hints': hints[:4],
        'errors': list(dict.fromkeys(errors))[:5],
        'detail': detail,
        'message': 'Ready — hold still, then capture' if ready else (hints[0] if hints else 'Adjust framing'),
    })


def _validate_lab_legacy(rgb, mode, checks, hints, errors, detail):
    """Minimal legacy path when LAB_MODES=1 for card/both."""
    from utils import find_credit_card

    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    center_edge = float(np.mean(edges[int(h * 0.12):int(h * 0.92), int(w * 0.1):int(w * 0.9)] > 0))
    checks['content'] = center_edge >= 0.008
    checks['tilt'] = True
    if mode in ('card', 'both'):
        try:
            box, _rect, score = find_credit_card(gray, min_area_ratio=0.004, aspect_tol=0.12)
            checks['reference'] = score >= 1.5
            x, y, bw, bh = box
            clipped = x <= 6 or y <= 6 or x + bw >= w - 6 or y + bh >= h - 6
            checks['full_frame'] = not clipped and checks['content']
        except ValueError:
            checks['reference'] = False
            checks['full_frame'] = False
            hints.append('Place a credit card fully visible beside the foot')
            errors.append('NO_CARD')
    else:
        checks['reference'] = True
        checks['full_frame'] = checks['content']

    ready = all(checks.values())
    return _json_safe({
        'ready': bool(ready),
        'score': round(sum(1.0 for v in checks.values() if v) / len(checks), 2),
        'checks': {k: bool(v) for k, v in checks.items()},
        'hints': hints[:4],
        'errors': errors[:5],
        'detail': detail,
        'message': 'Ready — hold still, then capture' if ready else (hints[0] if hints else 'Adjust'),
    })

