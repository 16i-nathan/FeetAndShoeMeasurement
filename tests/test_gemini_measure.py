"""Unit tests for Gemini AI length measure (mocked HTTP)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('ALLOW_BOOTSTRAP_SEG', '1')

from gemini_measure import (  # noqa: E402
    _norm_to_px,
    _parse_json_text,
    length_mm_from_landmarks,
    measure_paper_gemini,
)
from ml_measure import MeasureError  # noqa: E402


def test_parse_json_text_fenced():
    raw = '```json\n{"length_cm": 26.5, "confidence": 0.9}\n```'
    assert _parse_json_text(raw)['length_cm'] == 26.5


def test_norm_to_px():
    pt = _norm_to_px([0.5, 0.25], 201, 101)
    assert pt is not None
    assert abs(float(pt[0]) - 100.0) < 1e-3
    assert abs(float(pt[1]) - 25.0) < 1e-3


def test_length_mm_from_landmarks_a4_full_height():
    # Corners of a 210x297 image at 1 px/mm; heel top-center, toe bottom-center
    corners = np.array(
        [[0, 0], [209, 0], [209, 296], [0, 296]], dtype=np.float32
    )
    heel = np.array([105, 10], dtype=np.float32)
    toe = np.array([105, 280], dtype=np.float32)
    mm = length_mm_from_landmarks(corners, heel, toe, px_per_mm=1.0)
    assert 265 < mm < 275


def test_measure_paper_gemini_mocked(tmp_path):
    rgb = np.zeros((240, 180, 3), dtype=np.uint8)
    rgb[:] = (40, 40, 40)
    payload = {
        'candidates': [
            {
                'content': {
                    'parts': [
                        {
                            'text': json.dumps(
                                {'length_cm': 26.4, 'confidence': 0.88}
                            )
                        }
                    ]
                }
            }
        ]
    }

    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = payload
    mock_res.text = ''

    with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'}, clear=False):
        with patch('gemini_measure.httpx.Client') as client_cls:
            client = MagicMock()
            client.__enter__.return_value = client
            client.__exit__.return_value = False
            client.post.return_value = mock_res
            client_cls.return_value = client
            out = measure_paper_gemini(rgb, out_dir=tmp_path)

    assert out['cm'] == pytest.approx(26.4, abs=0.01)
    assert out['confidence'] == pytest.approx(0.88, abs=0.01)
    assert out['preview_path'] is None
    assert out['method'] == 'ai_length_cm'
    assert (tmp_path / 'gemini_result.json').is_file()
    assert not (tmp_path / 'preview.jpg').exists()


def test_measure_paper_gemini_requires_key():
    rgb = np.zeros((64, 48, 3), dtype=np.uint8)
    env = {k: v for k, v in os.environ.items() if k != 'GEMINI_API_KEY'}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(MeasureError) as ei:
            measure_paper_gemini(rgb)
    assert ei.value.code == 'NO_GEMINI_KEY'
