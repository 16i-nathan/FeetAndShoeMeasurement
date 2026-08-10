"""
Depth / LiDAR foot measurement.

Expects a metric (or scaled-to-metric) depth map aligned with the RGB image.
Typical sources: iPhone LiDAR exports, Android ToF, ARKit/ARCore depth,
or research RGB-D datasets.

Depth file formats:
  - .npy   float array in meters (preferred)
  - .png / .tif  16-bit; values * depth_scale → meters
                 default depth_scale=0.001 (millimeters)
"""

from __future__ import annotations

import os

import cv2
import numpy as np


def load_depth(path, depth_scale=None):
    """
    Load a depth map as float32 meters.
    depth_scale: multiply raw values to get meters.
      - None → 1.0 for float .npy, 0.001 for 16-bit images (mm→m)
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == '.npy':
        depth = np.load(path).astype(np.float32)
        if depth.ndim == 3:
            depth = depth[..., 0]
        scale = 1.0 if depth_scale is None else depth_scale
        return depth * scale

    raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError(f"Could not read depth map: {path}")
    if raw.ndim == 3:
        raw = raw[:, :, 0]
    depth = raw.astype(np.float32)
    scale = 0.001 if depth_scale is None else depth_scale
    return depth * scale


def resolve_depth_path(image_path, depth_arg=None):
    """Find depth sidecar if --depth not given: image_depth.npy / .png, etc."""
    if depth_arg:
        return depth_arg

    base, _ = os.path.splitext(image_path)
    stem = os.path.basename(base)
    parent = os.path.dirname(base) or '.'
    candidates = [
        f'{base}_depth.npy',
        f'{base}_depth.png',
        f'{base}_depth.tif',
        f'{base}.depth.npy',
        os.path.join(parent, f'{stem}_lidar.npy'),
        os.path.join(parent, f'{stem}_lidar.png'),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise ValueError(
        "No depth map found. Pass --depth PATH or place a sidecar next to the "
        "image (e.g. photo_depth.npy / photo_depth.png)."
    )


def resize_depth_to_image(depth, image_shape):
    h, w = image_shape[:2]
    if depth.shape[0] == h and depth.shape[1] == w:
        return depth
    return cv2.resize(depth, (w, h), interpolation=cv2.INTER_NEAREST)


def default_intrinsics(width, height, hfov_deg=60.0):
    """Approximate pinhole intrinsics from horizontal FOV (phone-like default)."""
    fx = (width / 2.0) / np.tan(np.deg2rad(hfov_deg) / 2.0)
    fy = fx
    cx = width / 2.0
    cy = height / 2.0
    return fx, fy, cx, cy


def backproject(depth_m, fx, fy, cx, cy, valid_mask=None):
    """Depth (H,W) meters → Nx3 points in camera frame."""
    h, w = depth_m.shape
    us, vs = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    z = depth_m
    if valid_mask is None:
        valid_mask = np.isfinite(z) & (z > 0.05) & (z < 5.0)
    u = us[valid_mask]
    v = vs[valid_mask]
    z = z[valid_mask]
    x = (u - cx) * z / fx
    y = (v - cy) * z / fy
    pts = np.stack([x, y, z], axis=1)
    return pts, valid_mask


def fit_ground_plane(points, max_iters=120, dist_thresh=0.008):
    """
    RANSAC plane fit. Returns (unit_normal, d) with n·p + d = 0,
    normal pointing roughly toward camera (negative Y/up in cam frame varies;
    we flip so mean point height is positive above plane).
    """
    if len(points) < 50:
        raise ValueError("Not enough depth points to fit a ground plane.")

    rng = np.random.default_rng(0)
    best_inliers = None
    best_model = None

    for _ in range(max_iters):
        idx = rng.choice(len(points), size=3, replace=False)
        p0, p1, p2 = points[idx]
        n = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n = n / norm
        d = -np.dot(n, p0)
        dist = np.abs(points @ n + d)
        inliers = dist < dist_thresh
        if best_inliers is None or inliers.sum() > best_inliers.sum():
            best_inliers = inliers
            best_model = (n, d)

    if best_model is None or best_inliers.sum() < 50:
        raise ValueError("Failed to fit ground plane from depth.")

    # Refit with inliers
    pts = points[best_inliers]
    centroid = pts.mean(axis=0)
    _, _, vh = np.linalg.svd(pts - centroid, full_matrices=False)
    n = vh[-1]
    n = n / (np.linalg.norm(n) + 1e-12)
    d = -np.dot(n, centroid)

    # Orient so the camera origin lies on the "above floor" side
    if -(d) < 0:  # height_above_plane(origin) = -d
        n, d = -n, -d

    return n, d


def height_above_plane(points, normal, d):
    """Positive = on the camera side of the plane (objects resting on floor)."""
    return -(points @ normal + d)


def assert_plausible_foot_cm(cm, min_cm=12.0, max_cm=35.0):
    """
    Reject garbage lengths from mis-detected blobs (cables, shoes piles, etc.).
    Adult feet are typically ~22–30 cm; allow kids down to ~12 cm.
    """
    if not np.isfinite(cm) or cm < min_cm or cm > max_cm:
        raise ValueError(
            f"Measured {cm:.1f} cm is outside a plausible foot range "
            f"({min_cm:.0f}–{max_cm:.0f} cm). Retake top-down with one full foot "
            "centered on a clear floor (no cables or other objects)."
        )
    return cm


def _contour_foot_score(contour, img_shape):
    """Prefer elongated, reasonably sized blobs near the image center."""
    h, w = img_shape[:2]
    area = float(cv2.contourArea(contour))
    img_area = float(h * w)
    if area < 0.003 * img_area or area > 0.40 * img_area:
        return -1.0
    x, y, bw, bh = cv2.boundingRect(contour)
    short, long = sorted((bw, bh))
    if short < 1:
        return -1.0
    aspect = long / short
    # Feet are elongated; reject near-square cable balls / clutter.
    if aspect < 1.35 or aspect > 6.5:
        return -1.0
    cx = x + bw * 0.5
    cy = y + bh * 0.5
    dist = np.hypot(cx - w * 0.5, cy - h * 0.5) / (0.5 * np.hypot(w, h))
    center = max(0.0, 1.0 - dist)
    # Penalize blobs glued to the border (often clutter / partial crop).
    margin = 4
    border_hit = (
        x <= margin or y <= margin or x + bw >= w - margin or y + bh >= h - margin
    )
    border_pen = 0.55 if border_hit else 1.0
    return area * aspect * (0.35 + 0.65 * center) * border_pen


def _refine_mask_with_rgb(foot_mask, rgb, depth_m):
    """
    When RGB is available, prefer pixels that differ from the border floor color.
    Keeps depth-raised region but drops floor-colored noise inside the blob.
    """
    if rgb is None or rgb.ndim != 3:
        return foot_mask
    h, w = foot_mask.shape
    if rgb.shape[0] != h or rgb.shape[1] != w:
        rgb = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA)

    # Sample floor color from border pixels that are valid depth and not foot.
    border = np.zeros((h, w), dtype=bool)
    m = max(6, min(h, w) // 25)
    border[:m, :] = True
    border[-m:, :] = True
    border[:, :m] = True
    border[:, -m:] = True
    valid = np.isfinite(depth_m) & (depth_m > 0.05) & (depth_m < 5.0)
    floor_pix = border & valid & (foot_mask == 0)
    if floor_pix.sum() < 80:
        return foot_mask

    floor_rgb = rgb[floor_pix].astype(np.float32)
    mean = floor_rgb.mean(axis=0)
    # Distance from floor color in RGB
    diff = np.linalg.norm(rgb.astype(np.float32) - mean, axis=2)
    # Keep raised pixels that look unlike the floor (skin/sock/shoe).
    unlike = diff > max(18.0, float(np.percentile(diff[floor_pix], 70)))
    refined = np.zeros_like(foot_mask)
    refined[(foot_mask > 0) & unlike] = 255
    if (refined > 0).sum() < 0.35 * max((foot_mask > 0).sum(), 1):
        return foot_mask  # RGB cue too aggressive — keep depth-only mask
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    refined = cv2.morphologyEx(refined, cv2.MORPH_CLOSE, ker, iterations=2)
    return refined


def segment_foot_from_depth(depth_m, fx, fy, cx, cy,
                            min_height_m=0.008, max_height_m=0.14,
                            rgb=None):
    """
    Foot = blob raised above the dominant ground plane.
    Returns foot_mask (H,W) uint8 and foot 3D points.
    """
    h, w = depth_m.shape
    # Prefer border pixels for plane seed (usually floor)
    border = np.zeros((h, w), dtype=bool)
    m = max(8, min(h, w) // 20)
    border[:m, :] = True
    border[-m:, :] = True
    border[:, :m] = True
    border[:, -m:] = True
    valid = np.isfinite(depth_m) & (depth_m > 0.05) & (depth_m < 5.0)

    border_pts, _ = backproject(depth_m, fx, fy, cx, cy, valid_mask=valid & border)
    if len(border_pts) < 50:
        border_pts, _ = backproject(depth_m, fx, fy, cx, cy, valid_mask=valid)

    # Subsample for RANSAC speed
    if len(border_pts) > 8000:
        sel = np.random.default_rng(0).choice(len(border_pts), 8000, replace=False)
        border_pts = border_pts[sel]

    normal, d = fit_ground_plane(border_pts)

    all_pts, valid_mask = backproject(depth_m, fx, fy, cx, cy, valid_mask=valid)
    heights = height_above_plane(all_pts, normal, d)

    raised = (heights > min_height_m) & (heights < max_height_m)
    foot_mask = np.zeros((h, w), dtype=np.uint8)
    # Map raised points back to pixels
    us, vs = np.meshgrid(np.arange(w), np.arange(h))
    u = us[valid_mask][raised]
    v = vs[valid_mask][raised]
    foot_mask[v, u] = 255

    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    foot_mask = cv2.morphologyEx(foot_mask, cv2.MORPH_CLOSE, ker, iterations=2)
    foot_mask = cv2.morphologyEx(foot_mask, cv2.MORPH_OPEN, ker, iterations=1)
    foot_mask = _refine_mask_with_rgb(foot_mask, rgb, depth_m)

    # Rank components — do not blindly take largest (cables / clutter win that).
    cnts, _ = cv2.findContours(foot_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    scored = []
    for c in cnts:
        s = _contour_foot_score(c, foot_mask.shape)
        if s > 0:
            scored.append((s, c))
    if not scored:
        raise ValueError(
            "No clear foot found in depth. Capture top-down with one full foot "
            "centered on a clear floor (LiDAR/ToF, depth in meters)."
        )
    scored.sort(key=lambda t: t[0], reverse=True)
    best = scored[0][1]
    clean = np.zeros_like(foot_mask)
    cv2.drawContours(clean, [best], -1, 255, thickness=-1)

    foot_pts, _ = backproject(depth_m, fx, fy, cx, cy, valid_mask=(clean > 0) & valid)
    if len(foot_pts) < 30:
        raise ValueError("Foot depth region too small / sparse.")

    return clean, foot_pts, best, (normal, d)


def rays_to_plane(us, vs, fx, fy, cx, cy, normal, d):
    """Intersect camera rays through pixels with plane n·p + d = 0."""
    dirs = np.stack([(us - cx) / fx, (vs - cy) / fy, np.ones(len(us))], axis=1)
    dirs = dirs / (np.linalg.norm(dirs, axis=1, keepdims=True) + 1e-12)
    denom = dirs @ normal
    t = -d / (denom + 1e-12)
    ok = t > 0
    return dirs[ok] * t[ok, None]


def foot_length_m_from_points(pts, normal=None):
    """Length along the principal axis of 3D points (meters)."""
    if len(pts) < 2:
        raise ValueError("Not enough points to measure foot length.")
    centered = pts - pts.mean(axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    axis = vh[0]
    if normal is not None:
        axis = axis - np.dot(axis, normal) * normal
        nrm = np.linalg.norm(axis)
        axis = vh[0] if nrm < 1e-9 else axis / nrm
    proj = centered @ axis
    lo, hi = np.percentile(proj, [2, 98])
    return float(hi - lo)


def foot_length_m_on_plane(foot_mask, fx, fy, cx, cy, normal, d):
    """Footprint length via ray–plane hits for foot pixels, then in-plane PCA."""
    vs, us = np.where(foot_mask > 0)
    if len(us) < 30:
        raise ValueError("Foot mask too small for depth measurement.")
    if len(us) > 20000:
        sel = np.random.default_rng(0).choice(len(us), 20000, replace=False)
        us, vs = us[sel], vs[sel]
    pts = rays_to_plane(
        us.astype(np.float32), vs.astype(np.float32), fx, fy, cx, cy, normal, d
    )
    return foot_length_m_from_points(pts, normal=normal)


def colorize_depth(depth_m, valid_max=2.0):
    """uint8 BGR visualization for debugging."""
    d = depth_m.copy()
    d[~np.isfinite(d)] = 0
    d = np.clip(d, 0, valid_max)
    norm = (d / valid_max * 255).astype(np.uint8)
    return cv2.applyColorMap(norm, cv2.COLORMAP_TURBO)


def measure_foot_cm_from_depth(rgb, depth_m, fx=None, fy=None, cx=None, cy=None,
                               hfov_deg=60.0):
    """
    Full depth pipeline. Returns (cm, foot_box, foot_mask, foot_pts).
    """
    h, w = rgb.shape[:2]
    depth_m = resize_depth_to_image(depth_m, rgb.shape)

    if fx is None or fy is None:
        fx0, fy0, cx0, cy0 = default_intrinsics(w, h, hfov_deg=hfov_deg)
        fx = fx0 if fx is None else fx
        fy = fy0 if fy is None else fy
        cx = cx0 if cx is None else cx
        cy = cy0 if cy is None else cy
    else:
        cx = w / 2.0 if cx is None else cx
        cy = h / 2.0 if cy is None else cy

    foot_mask, foot_pts, contour, plane = segment_foot_from_depth(
        depth_m, fx, fy, cx, cy, rgb=rgb
    )
    normal, d = plane
    length_m = foot_length_m_on_plane(foot_mask, fx, fy, cx, cy, normal, d)
    # Cross-check with 3D PCA on raised points; reject if they disagree a lot
    # (usually means the mask mixed foot + clutter).
    length_pts = foot_length_m_from_points(foot_pts, normal=normal)
    if length_pts > 0.05:
        ratio = max(length_m, length_pts) / max(min(length_m, length_pts), 1e-6)
        if ratio > 1.35:
            # Prefer the shorter of the two when both are in range — clutter
            # inflates length more often than it shrinks it.
            length_m = min(length_m, length_pts)

    cm = assert_plausible_foot_cm(length_m * 100.0)
    box = cv2.boundingRect(contour)
    return cm, box, foot_mask, foot_pts


def make_synthetic_rgbd(out_rgb='data/synthetic_depth_rgb.jpg',
                        out_depth='data/synthetic_depth_rgb_depth.npy',
                        foot_length_m=0.26):
    """Create a simple RGB-D pair for smoke-testing --ref depth."""
    h, w = 640, 480
    fx = fy = 520.0
    cx, cy = w / 2.0, h / 2.0
    z_floor = 0.85

    us, vs = np.meshgrid(np.arange(w), np.arange(h))
    # Floor plane Z constant (camera looking straight down approx)
    depth = np.full((h, w), z_floor, dtype=np.float32)

    # Footprint sized on the floor plane (ray–plane length); depth marks a raised slab
    z_foot = z_floor - 0.04
    foot_len_px = foot_length_m * fx / z_floor
    foot_wid_px = 0.09 * fy / z_floor
    v0 = int(h / 2 - foot_len_px / 2)
    v1 = int(h / 2 + foot_len_px / 2)
    u0 = int(w / 2 - foot_wid_px / 2)
    u1 = int(w / 2 + foot_wid_px / 2)
    depth[v0:v1, u0:u1] = z_foot

    rgb = np.full((h, w, 3), 50, dtype=np.uint8)  # dark floor
    rgb[v0:v1, u0:u1] = (170, 130, 110)  # skin-ish

    os.makedirs(os.path.dirname(out_rgb) or '.', exist_ok=True)
    cv2.imwrite(out_rgb, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    np.save(out_depth, depth)
    return out_rgb, out_depth, dict(fx=fx, fy=fy, cx=cx, cy=cy, expected_cm=foot_length_m * 100)
