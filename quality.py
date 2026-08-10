"""Shared quality gates for validate + measure (A4 paper production path)."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

# A4 ISO 216
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0
A4_ASPECT = A4_HEIGHT_MM / A4_WIDTH_MM  # ~1.414


@dataclass
class QualityThresholds:
    brightness_min: float = 55.0
    brightness_max: float = 200.0
    sharpness_min: float = 40.0
    glare_max: float = 0.02
    paper_coverage_min: float = 0.12
    paper_coverage_max: float = 0.85
    foot_coverage_min: float = 0.015
    foot_on_paper_min: float = 0.45
    aspect_err_max: float = 0.18
    tilt_max: float = 0.22  # |1 - aspect/expected| proxy + corner skew
    border_touch_max: float = 0.10
    paper_score_min: float = 0.40
    foot_score_min: float = 0.35
    conf_min: float = 0.40


DEFAULT_THRESHOLDS = QualityThresholds()


@dataclass
class GeometryResult:
    ok: bool
    corners: np.ndarray | None = None  # (4, 2) float32 image coords
    paper_score: float = 0.0
    foot_score: float = 0.0
    confidence: float = 0.0
    tilt: float = 1.0
    aspect_err: float = 1.0
    paper_coverage: float = 0.0
    foot_coverage: float = 0.0
    foot_on_paper: float = 0.0
    border_touch: float = 1.0
    errors: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)


def brightness(gray: np.ndarray) -> float:
    return float(np.mean(gray))


def sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def glare_ratio(gray: np.ndarray) -> float:
    return float(np.mean(gray > 245))


def border_touch_ratio(mask: np.ndarray, border: int = 5) -> float:
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


def largest_component(mask: np.ndarray) -> np.ndarray:
    binary = (mask > 0).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return np.zeros_like(binary)
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (labels == idx).astype(np.uint8) * 255


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Order as TL, TR, BR, BL."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.stack([tl, tr, br, bl], axis=0)


def paper_corners_from_mask(paper_mask: np.ndarray) -> tuple[np.ndarray | None, float]:
    """Return (corners 4x2, rectangularity score) or (None, 0)."""
    mask = largest_component(paper_mask)
    if not np.any(mask):
        return None, 0.0
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, 0.0
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < 100:
        return None, 0.0
    peri = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.02 * peri, True)
    if len(approx) == 4:
        corners = order_corners(approx.reshape(4, 2))
    else:
        rect = cv2.minAreaRect(c)
        box = cv2.boxPoints(rect)
        corners = order_corners(box)
    hull = cv2.convexHull(c)
    hull_area = cv2.contourArea(hull)
    rectangularity = float(area / hull_area) if hull_area > 0 else 0.0
    # Prefer near-quad
    if len(approx) == 4:
        rectangularity = min(1.0, rectangularity + 0.15)
    return corners, rectangularity


def aspect_error_from_corners(corners: np.ndarray) -> float:
    tl, tr, br, bl = corners
    w1 = np.linalg.norm(tr - tl)
    w2 = np.linalg.norm(br - bl)
    h1 = np.linalg.norm(bl - tl)
    h2 = np.linalg.norm(br - tr)
    width = 0.5 * (w1 + w2)
    height = 0.5 * (h1 + h2)
    if min(width, height) < 1:
        return 1.0
    aspect = max(width, height) / min(width, height)
    return abs(aspect - A4_ASPECT) / A4_ASPECT


def tilt_from_corners(corners: np.ndarray) -> float:
    """0 = orthographic rectangle; higher = perspective/skew."""
    tl, tr, br, bl = corners
    top = np.linalg.norm(tr - tl)
    bottom = np.linalg.norm(br - bl)
    left = np.linalg.norm(bl - tl)
    right = np.linalg.norm(br - tr)
    if min(top, bottom, left, right) < 1:
        return 1.0
    parallel = 0.5 * (abs(top - bottom) / max(top, bottom) + abs(left - right) / max(left, right))
    return float(np.clip(parallel, 0.0, 1.0))


def evaluate_masks(
    paper_mask: np.ndarray,
    foot_mask: np.ndarray,
    thr: QualityThresholds | None = None,
) -> GeometryResult:
    thr = thr or DEFAULT_THRESHOLDS
    h, w = paper_mask.shape[:2]
    img_area = float(h * w)
    errors: list[str] = []
    hints: list[str] = []

    paper = largest_component(paper_mask)
    foot = (foot_mask > 0).astype(np.uint8) * 255
    # Exclusive class maps put foot pixels outside "paper"; use sheet = paper∪foot.
    sheet = largest_component(cv2.bitwise_or(paper, foot))
    if not np.any(sheet):
        sheet = paper

    paper_cov = float(np.mean(sheet > 0))
    foot_cov = float(np.mean(foot > 0))
    foot_px = max(int(np.sum(foot > 0)), 1)
    # Dilate sheet slightly so foot near edges still counts as on-paper
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    sheet_dil = cv2.dilate(sheet, ker, iterations=2)
    foot_on_paper = float(np.sum(cv2.bitwise_and(foot, sheet_dil) > 0) / foot_px)
    touch = border_touch_ratio(sheet)

    corners, rect_score = paper_corners_from_mask(sheet)
    aspect_err = 1.0
    tilt = 1.0
    if corners is not None:
        aspect_err = aspect_error_from_corners(corners)
        tilt = tilt_from_corners(corners)

    paper_score = 0.0
    if corners is not None:
        paper_score = float(
            np.clip(
                0.35 * rect_score
                + 0.25 * (1.0 - min(aspect_err / thr.aspect_err_max, 1.0))
                + 0.20 * (1.0 - min(tilt / thr.tilt_max, 1.0))
                + 0.20 * np.clip(
                    (paper_cov - thr.paper_coverage_min)
                    / max(thr.paper_coverage_max - thr.paper_coverage_min, 1e-6),
                    0,
                    1,
                ),
                0,
                1,
            )
        )

    foot_score = 0.0
    if foot_cov >= thr.foot_coverage_min:
        foot_score = float(
            np.clip(
                0.45 * np.clip(foot_cov / 0.15, 0, 1)
                + 0.40 * foot_on_paper
                + 0.15 * (1.0 if foot_cov < 0.35 else 0.5),
                0,
                1,
            )
        )

    if paper_cov < thr.paper_coverage_min or corners is None:
        errors.append('NO_PAPER')
        hints.append('Show the full white A4 sheet with all four corners visible')
    elif aspect_err > thr.aspect_err_max:
        errors.append('HIGH_TILT')
        hints.append('Hold the phone more top-down so the paper looks rectangular')
    elif tilt > thr.tilt_max:
        errors.append('HIGH_TILT')
        hints.append('Reduce camera angle — keep the phone parallel to the floor')
    elif paper_score < thr.paper_score_min:
        errors.append('LOW_CONF')
        hints.append('Improve paper contrast — dark floor, even light, no flash')

    if touch >= thr.border_touch_max:
        errors.append('CROP')
        hints.append('Step back so the full A4 sheet is inside the frame')

    if foot_cov < thr.foot_coverage_min or foot_score < thr.foot_score_min:
        errors.append('NO_FOOT')
        hints.append('Place the full foot on the paper with toes and heel visible')
    elif foot_on_paper < thr.foot_on_paper_min:
        errors.append('NO_FOOT')
        hints.append('Keep the entire foot on the A4 sheet')

    confidence = float(np.clip(0.5 * paper_score + 0.5 * foot_score, 0, 1))
    if confidence < thr.conf_min and 'LOW_CONF' not in errors:
        errors.append('LOW_CONF')
        hints.append('Hold steady and improve lighting for a clearer capture')

    ok = (
        corners is not None
        and not errors
        and paper_score >= thr.paper_score_min
        and foot_score >= thr.foot_score_min
        and confidence >= thr.conf_min
    )
    # Allow ok when only soft LOW_CONF from borderline — require empty errors
    ok = len(errors) == 0 and corners is not None

    return GeometryResult(
        ok=ok,
        corners=corners,
        paper_score=paper_score,
        foot_score=foot_score,
        confidence=confidence,
        tilt=tilt,
        aspect_err=aspect_err,
        paper_coverage=paper_cov,
        foot_coverage=foot_cov,
        foot_on_paper=foot_on_paper,
        border_touch=touch,
        errors=errors,
        hints=hints[:4],
    )
