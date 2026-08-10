"""Unit tests for quality geometry + ML measure on synthetic samples."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ['ALLOW_BOOTSTRAP_SEG'] = '1'
os.environ['LAB_MODES'] = '0'

from quality import evaluate_masks, order_corners, paper_corners_from_mask  # noqa: E402
from training.synthesize import make_sample  # noqa: E402
from ml_measure import MeasureError, measure_paper_ml  # noqa: E402


def test_order_corners_tl_tr_br_bl():
    pts = np.array([[10, 10], [100, 12], [98, 140], [8, 138]], dtype=np.float32)
    ordered = order_corners(pts)
    assert ordered[0][0] < ordered[1][0]
    assert ordered[0][1] < ordered[3][1]


def test_paper_corners_from_mask():
    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[40:160, 50:150] = 255
    corners, score = paper_corners_from_mask(mask)
    assert corners is not None
    assert corners.shape == (4, 2)
    assert score > 0.5


def test_evaluate_masks_ok_on_synthetic():
    rgb, label = make_sample(512)
    paper = (label == 1).astype(np.uint8) * 255
    foot = (label == 2).astype(np.uint8) * 255
    geo = evaluate_masks(paper, foot)
    assert geo.corners is not None
    assert geo.paper_coverage > 0.1
    assert geo.foot_coverage > 0.01


def test_measure_synthetic_plausible():
    rgb, _ = make_sample(512)
    r = measure_paper_ml(rgb, allow_bootstrap=True)
    assert 12.0 <= r['cm'] <= 35.0
    assert r['confidence'] > 0


def test_measure_rejects_empty():
    rgb = np.zeros((400, 400, 3), dtype=np.uint8)
    with pytest.raises(MeasureError):
        measure_paper_ml(rgb, allow_bootstrap=True)
