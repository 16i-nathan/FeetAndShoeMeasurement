"""Synthetic A4 + foot composites for bootstrap training."""

from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np

A4_W, A4_H = 210, 297  # mm aspect


def _random_floor(h: int, w: int) -> np.ndarray:
    base = np.array([
        random.randint(40, 100),
        random.randint(30, 80),
        random.randint(20, 60),
    ], dtype=np.uint8)
    img = np.tile(base, (h, w, 1)).astype(np.float32)
    noise = np.random.randn(h, w, 3).astype(np.float32) * random.uniform(5, 18)
    # wood-ish stripes
    for y in range(h):
        img[y] += np.sin(y / random.uniform(8, 20)) * random.uniform(3, 12)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def _draw_paper(canvas: np.ndarray, mask: np.ndarray) -> np.ndarray:
    h, w = canvas.shape[:2]
    # Perspective quad roughly centered
    pw = int(w * random.uniform(0.45, 0.72))
    ph = int(pw * (A4_H / A4_W) * random.uniform(0.92, 1.08))
    cx, cy = w // 2 + random.randint(-w // 12, w // 12), h // 2 + random.randint(-h // 14, h // 14)
    jitter = lambda v: v + random.randint(-12, 12)
    tl = (jitter(cx - pw // 2), jitter(cy - ph // 2))
    tr = (jitter(cx + pw // 2), jitter(cy - ph // 2))
    br = (jitter(cx + pw // 2), jitter(cy + ph // 2))
    bl = (jitter(cx - pw // 2), jitter(cy + ph // 2))
    pts = np.array([tl, tr, br, bl], dtype=np.int32)
    color = (
        random.randint(230, 255),
        random.randint(230, 255),
        random.randint(230, 255),
    )
    cv2.fillConvexPoly(canvas, pts, color)
    cv2.fillConvexPoly(mask, pts, 1)
    return pts.astype(np.float32)


def _draw_foot(canvas: np.ndarray, paper_mask: np.ndarray, foot_mask: np.ndarray, paper_pts: np.ndarray):
    # Ellipse foot inside paper bounds
    xs = paper_pts[:, 0]
    ys = paper_pts[:, 1]
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    fw = int((x1 - x0) * random.uniform(0.28, 0.42))
    fh = int((y1 - y0) * random.uniform(0.55, 0.78))
    fcx = random.randint(x0 + fw, max(x0 + fw + 1, x1 - fw))
    fcy = random.randint(y0 + fh // 2, max(y0 + fh // 2 + 1, y1 - fh // 2))
    skin = (
        random.randint(60, 160),
        random.randint(40, 110),
        random.randint(30, 90),
    )
    axes = (fw // 2, fh // 2)
    angle = random.uniform(-15, 15)
    cv2.ellipse(canvas, (fcx, fcy), axes, angle, 0, 360, skin, -1)
    cv2.ellipse(foot_mask, (fcx, fcy), axes, angle, 0, 360, 2, -1)
    # Ensure foot only counted on paper
    foot_mask[paper_mask == 0] = 0


def make_sample(size: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """Returns rgb uint8, label HxW with 0=bg, 1=paper, 2=foot."""
    rgb = _random_floor(size, size)
    paper = np.zeros((size, size), dtype=np.uint8)
    foot = np.zeros((size, size), dtype=np.uint8)
    pts = _draw_paper(rgb, paper)
    _draw_foot(rgb, paper, foot, pts)
    # Soft blur / noise
    if random.random() < 0.5:
        rgb = cv2.GaussianBlur(rgb, (5, 5), 0)
    label = np.zeros((size, size), dtype=np.uint8)
    label[paper > 0] = 1
    label[foot > 0] = 2
    return rgb, label


def write_dataset(out_dir: Path, n: int = 200, size: int = 512):
    out_dir = Path(out_dir)
    (out_dir / 'images').mkdir(parents=True, exist_ok=True)
    (out_dir / 'masks').mkdir(parents=True, exist_ok=True)
    for i in range(n):
        rgb, label = make_sample(size)
        cv2.imwrite(str(out_dir / 'images' / f'{i:04d}.jpg'), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        cv2.imwrite(str(out_dir / 'masks' / f'{i:04d}.png'), label)
    return n
