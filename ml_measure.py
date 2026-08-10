"""Production A4 measurement: ML (or bootstrap) seg → homography → foot length cm."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from depth_measure import assert_plausible_foot_cm
from quality import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    DEFAULT_THRESHOLDS,
    GeometryResult,
    evaluate_masks,
    largest_component,
    order_corners,
)
from seg_infer import segment

ROOT = Path(__file__).resolve().parent


def largest_component_mask(mask: np.ndarray) -> np.ndarray:
    return largest_component(mask)


class MeasureError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _a4_destination(px_per_mm: float = 2.0) -> np.ndarray:
    w = A4_WIDTH_MM * px_per_mm
    h = A4_HEIGHT_MM * px_per_mm
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)


def foot_length_mm_on_plane(
    foot_mask_warped: np.ndarray,
    px_per_mm: float,
) -> float:
    """Longest extent of foot mask along paper long axis (height of A4)."""
    binary = (foot_mask_warped > 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        raise MeasureError('NO_FOOT', 'Could not find a foot on the paper after rectification.')
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    # Drop speckles — require a meaningful component
    if stats[idx, cv2.CC_STAT_AREA] < 80:
        raise MeasureError('NO_FOOT', 'Could not find a foot on the paper after rectification.')
    comp = (labels == idx).astype(np.uint8)
    ys, xs = np.where(comp > 0)
    if len(ys) < 20:
        raise MeasureError('NO_FOOT', 'Could not find a foot on the paper after rectification.')
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    h_px = y1 - y0 + 1
    w_px = x1 - x0 + 1
    long_px = float(max(h_px, w_px))
    contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        if len(c) >= 5:
            (_cx, _cy), (rw, rh), _ang = cv2.minAreaRect(c)
            # Prefer oriented major axis; ignore if absurdly near full paper
            major = float(max(rw, rh))
            paper_long = A4_HEIGHT_MM * px_per_mm
            if major < 0.95 * paper_long:
                long_px = major
            else:
                long_px = float(max(h_px, w_px))
                if long_px >= 0.95 * paper_long:
                    # Fall back to percentile extent to ignore speckles
                    long_px = float(np.percentile(ys, 98) - np.percentile(ys, 2))
    return long_px / px_per_mm


def draw_preview(
    rgb: np.ndarray,
    paper_mask: np.ndarray,
    foot_mask: np.ndarray,
    corners: np.ndarray | None,
    cm: float | None = None,
) -> np.ndarray:
    vis = rgb.copy()
    overlay = vis.copy()
    sheet = cv2.bitwise_or(
        (paper_mask > 0).astype(np.uint8) * 255,
        (foot_mask > 0).astype(np.uint8) * 255,
    )
    overlay[sheet > 0] = (80, 160, 255)
    overlay[foot_mask > 0] = (255, 140, 40)
    vis = cv2.addWeighted(vis, 0.65, overlay, 0.35, 0)
    if corners is not None:
        pts = corners.astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(vis, [pts], True, (0, 220, 80), 2)
        for i, p in enumerate(corners.astype(int)):
            cv2.circle(vis, tuple(p), 5, (0, 255, 0), -1)
    if cm is not None:
        cv2.putText(
            vis, f'{cm:.1f} cm', (16, 40),
            cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 3,
        )
        cv2.putText(
            vis, f'{cm:.1f} cm', (16, 40),
            cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2,
        )
    # Crop to sheet (+padding) so preview is not a weird full-frame crop of the leg
    if np.any(sheet):
        ys, xs = np.where(sheet > 0)
        y0, y1 = max(0, int(ys.min()) - 12), min(vis.shape[0], int(ys.max()) + 12)
        x0, x1 = max(0, int(xs.min()) - 12), min(vis.shape[1], int(xs.max()) + 12)
        if y1 > y0 + 40 and x1 > x0 + 40:
            vis = vis[y0:y1, x0:x1]
    return vis


def measure_paper_ml(
    rgb: np.ndarray,
    *,
    allow_bootstrap: bool | None = None,
    out_dir: Path | None = None,
    px_per_mm: float = 2.0,
) -> dict:
    """
    Measure foot length using segmentation + A4 homography.

    Returns dict with cm, confidence, scores, preview path fields.
    Raises MeasureError with .code in NO_PAPER, NO_FOOT, HIGH_TILT, LOW_CONF, ...
    """
    paper, foot, source = segment(rgb, allow_bootstrap=allow_bootstrap)
    # Keep largest foot blob to avoid corner speckles spanning the sheet
    foot = largest_component_mask(foot)
    geo: GeometryResult = evaluate_masks(paper, foot)

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    if not geo.ok or geo.corners is None:
        code = geo.errors[0] if geo.errors else 'LOW_CONF'
        msg = geo.hints[0] if geo.hints else 'Measurement quality too low — retake.'
        if out_dir is not None:
            prev = draw_preview(rgb, paper, foot, geo.corners)
            cv2.imwrite(str(out_dir / 'preview.jpg'), cv2.cvtColor(prev, cv2.COLOR_RGB2BGR))
        raise MeasureError(code, msg)

    corners = order_corners(geo.corners)
    dst = _a4_destination(px_per_mm)
    H = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    wh = (int(A4_WIDTH_MM * px_per_mm), int(A4_HEIGHT_MM * px_per_mm))
    # Exclusive class maps: foot pixels are not in paper — warp foot alone.
    foot_w = cv2.warpPerspective(foot, H, wh, flags=cv2.INTER_NEAREST)
    paper_w = cv2.warpPerspective(paper, H, wh, flags=cv2.INTER_NEAREST)
    sheet_w = cv2.bitwise_or(paper_w, foot_w)
    # Keep foot near the sheet (dilate sheet to avoid edge loss)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    sheet_dil = cv2.dilate(sheet_w, ker, iterations=2)
    foot_w = cv2.bitwise_and(foot_w, sheet_dil)

    try:
        length_mm = foot_length_mm_on_plane(foot_w, px_per_mm)
    except MeasureError:
        if out_dir is not None:
            prev = draw_preview(rgb, paper, foot, corners)
            cv2.imwrite(str(out_dir / 'preview.jpg'), cv2.cvtColor(prev, cv2.COLOR_RGB2BGR))
        raise

    # Reject clearly truncated masks only (very short span on the A4 plane)
    ys, xs = np.where(foot_w > 0)
    if len(ys) > 0:
        span = float(ys.max() - ys.min() + 1) / max(foot_w.shape[0], 1)
        if span < 0.35 and length_mm < 200:
            if out_dir is not None:
                prev = draw_preview(rgb, paper, foot, corners)
                cv2.imwrite(
                    str(out_dir / 'preview.jpg'),
                    cv2.cvtColor(prev, cv2.COLOR_RGB2BGR),
                )
            raise MeasureError(
                'PARTIAL_FOOT',
                'Only part of the foot was detected (see orange overlay). '
                'Retake top-down with the full heel and toes on a light A4 sheet.',
            )

    cm = assert_plausible_foot_cm(length_mm / 10.0)
    preview_path = None
    if out_dir is not None:
        prev = draw_preview(rgb, paper, foot, corners, cm=cm)
        preview_path = out_dir / 'preview.jpg'
        cv2.imwrite(str(preview_path), cv2.cvtColor(prev, cv2.COLOR_RGB2BGR))
        cv2.imwrite(str(out_dir / 'foot_warped.jpg'), foot_w)

    return {
        'cm': float(cm),
        'confidence': float(geo.confidence),
        'paper_score': float(geo.paper_score),
        'foot_score': float(geo.foot_score),
        'tilt': float(geo.tilt),
        'aspect_err': float(geo.aspect_err),
        'seg_source': source,
        'preview_path': str(preview_path) if preview_path else None,
    }


def measure_burst_median(rgbs: list[np.ndarray], **kwargs) -> dict:
    """Run measure on each frame; return median cm with spread."""
    results = []
    errors = []
    for i, rgb in enumerate(rgbs):
        out_dir = kwargs.get('out_dir')
        frame_dir = Path(out_dir) / f'frame_{i}' if out_dir else None
        try:
            r = measure_paper_ml(rgb, out_dir=frame_dir, allow_bootstrap=kwargs.get('allow_bootstrap'))
            results.append(r)
        except MeasureError as e:
            errors.append(e)

    if not results:
        if errors:
            raise errors[0]
        raise MeasureError('LOW_CONF', 'All burst frames failed measurement.')

    cms = sorted(r['cm'] for r in results)
    mid = cms[len(cms) // 2]
    spread = (cms[-1] - cms[0]) / 2.0 if len(cms) > 1 else 0.0
    best = min(results, key=lambda r: abs(r['cm'] - mid))
    conf = float(np.mean([r['confidence'] for r in results]))
    return {
        **best,
        'cm': float(mid),
        'cm_spread': float(spread),
        'cm_samples': [float(c) for c in cms],
        'n_ok': len(results),
        'n_fail': len(errors),
        'confidence': conf,
    }
