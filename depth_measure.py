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


def segment_foot_from_depth(depth_m, fx, fy, cx, cy,
                            min_height_m=0.008, max_height_m=0.12):
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

    # Keep largest component
    cnts, _ = cv2.findContours(foot_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        raise ValueError(
            "No raised foot found in depth. Capture top-down with LiDAR/ToF, "
            "foot fully in frame, depth in meters."
        )
    largest = max(cnts, key=cv2.contourArea)
    clean = np.zeros_like(foot_mask)
    cv2.drawContours(clean, [largest], -1, 255, thickness=-1)

    foot_pts, _ = backproject(depth_m, fx, fy, cx, cy, valid_mask=(clean > 0) & valid)
    if len(foot_pts) < 30:
        raise ValueError("Foot depth region too small / sparse.")

    return clean, foot_pts, largest, (normal, d)


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
    lo, hi = np.percentile(proj, [1, 99])
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
        depth_m, fx, fy, cx, cy
    )
    normal, d = plane
    # Size pixels at foot depth in the synthetic generator → use 3D foot points PCA
    # as primary; ray-plane footprint as the on-floor length (preferred).
    length_m = foot_length_m_on_plane(foot_mask, fx, fy, cx, cy, normal, d)
    box = cv2.boundingRect(contour)
    return length_m * 100.0, box, foot_mask, foot_pts


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
