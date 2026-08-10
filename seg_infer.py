"""ONNX paper/foot segmentation inference + bootstrap classical masks."""

from __future__ import annotations

import json
import os
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / 'models'
DEFAULT_ONNX = MODELS_DIR / 'paper_foot_seg.onnx'
DEFAULT_CARD = MODELS_DIR / 'model_card.json'

# Class indices
CLS_BG = 0
CLS_PAPER = 1
CLS_FOOT = 2

_SESSION = None
_CARD: dict | None = None
_LOAD_ERROR: str | None = None


def model_card_path() -> Path:
    return Path(os.environ.get('MODEL_CARD', str(DEFAULT_CARD)))


def onnx_path() -> Path:
    return Path(os.environ.get('MODEL_ONNX', str(DEFAULT_ONNX)))


def load_model_card() -> dict:
    global _CARD
    if _CARD is not None:
        return _CARD
    path = model_card_path()
    if path.is_file():
        _CARD = json.loads(path.read_text())
    else:
        _CARD = {
            'version': 'bootstrap',
            'input_size': 512,
            'classes': ['background', 'paper', 'foot'],
            'mean': [0.485, 0.456, 0.406],
            'std': [0.229, 0.224, 0.225],
        }
    return _CARD


def model_loaded() -> bool:
    ensure_session()
    return _SESSION is not None


def model_load_error() -> str | None:
    ensure_session()
    return _LOAD_ERROR


def ensure_session():
    global _SESSION, _LOAD_ERROR
    if _SESSION is not None or _LOAD_ERROR == 'missing':
        return _SESSION
    path = onnx_path()
    if not path.is_file():
        _LOAD_ERROR = 'missing'
        return None
    try:
        import onnxruntime as ort

        _SESSION = ort.InferenceSession(
            str(path), providers=['CPUExecutionProvider']
        )
        _LOAD_ERROR = None
    except Exception as e:
        _LOAD_ERROR = str(e)
        _SESSION = None
    return _SESSION


def _preprocess(rgb: np.ndarray, size: int, mean, std) -> np.ndarray:
    img = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    x = img.astype(np.float32) / 255.0
    x = (x - np.array(mean, dtype=np.float32)) / np.array(std, dtype=np.float32)
    x = np.transpose(x, (2, 0, 1))[None, ...]
    return x


def bootstrap_segment(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Classical bootstrap masks used when ONNX is unavailable (dev only)
    or as synthetic-label generator. Not a silent production fallback for
    low-confidence ML — production requires ONNX + quality gates.
    """
    h, w = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # White / near-white paper
    paper = (
        (hsv[:, :, 2] > 160)
        & (hsv[:, :, 1] < 80)
    ).astype(np.uint8) * 255
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    paper = cv2.morphologyEx(paper, cv2.MORPH_CLOSE, ker, iterations=2)
    paper = cv2.morphologyEx(paper, cv2.MORPH_OPEN, ker, iterations=1)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    paper_px = rgb[paper > 0]
    if len(paper_px) > 50:
        mean = paper_px.mean(axis=0).astype(np.float32)
    else:
        mean = np.array([240, 240, 240], dtype=np.float32)
    diff = np.linalg.norm(rgb.astype(np.float32) - mean, axis=2)
    paper_dil = cv2.dilate(paper, ker, iterations=3)
    # Non-paper-colored pixels inside the sheet region
    foot = ((diff > 28) & (paper_dil > 0)).astype(np.uint8) * 255
    foot = cv2.morphologyEx(foot, cv2.MORPH_OPEN, ker, iterations=1)
    foot = cv2.morphologyEx(foot, cv2.MORPH_CLOSE, ker, iterations=2)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        (foot > 0).astype(np.uint8), connectivity=8
    )
    if n > 1:
        idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        if stats[idx, cv2.CC_STAT_AREA] > 0.004 * h * w:
            foot = (labels == idx).astype(np.uint8) * 255
        else:
            foot = np.zeros_like(foot)

    return paper, foot


def segment(rgb: np.ndarray, allow_bootstrap: bool | None = None) -> tuple[np.ndarray, np.ndarray, str]:
    """
    Returns (paper_mask, foot_mask, source) where source is 'onnx' or 'bootstrap'.
    """
    if allow_bootstrap is None:
        allow_bootstrap = os.environ.get('ALLOW_BOOTSTRAP_SEG', '1') == '1'

    card = load_model_card()
    size = int(card.get('input_size', 512))
    mean = card.get('mean', [0.485, 0.456, 0.406])
    std = card.get('std', [0.229, 0.224, 0.225])
    sess = ensure_session()

    if sess is not None:
        h, w = rgb.shape[:2]
        inp = _preprocess(rgb, size, mean, std)
        input_name = sess.get_inputs()[0].name
        out = sess.run(None, {input_name: inp})[0]
        # out: (1, C, H, W) or (1, H, W)
        if out.ndim == 4:
            if out.shape[1] == 3:
                pred = np.argmax(out[0], axis=0).astype(np.uint8)
            else:
                pred = np.argmax(out[0], axis=0).astype(np.uint8)
        else:
            pred = out[0].astype(np.uint8)
        pred = cv2.resize(pred, (w, h), interpolation=cv2.INTER_NEAREST)
        paper = (pred == CLS_PAPER).astype(np.uint8) * 255
        foot = (pred == CLS_FOOT).astype(np.uint8) * 255
        return paper, foot, 'onnx'

    if allow_bootstrap:
        paper, foot = bootstrap_segment(rgb)
        return paper, foot, 'bootstrap'

    raise RuntimeError(
        'Segmentation model not loaded. Place models/paper_foot_seg.onnx '
        'or set ALLOW_BOOTSTRAP_SEG=1 for development.'
    )
