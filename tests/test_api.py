"""API tests for production paper-only surface."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ['ALLOW_BOOTSTRAP_SEG'] = '1'
os.environ['LAB_MODES'] = '0'
os.environ['RATE_LIMIT_PER_MIN'] = '0'

from training.synthesize import make_sample  # noqa: E402
import server  # noqa: E402


@pytest.fixture
def client():
    return TestClient(server.app)


def _jpeg_bytes(rgb: np.ndarray) -> bytes:
    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    assert ok
    return buf.tobytes()


def test_health(client):
    r = client.get('/api/health')
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert 'model_loaded' in body


def test_rejects_card_mode(client):
    rgb, _ = make_sample(256)
    r = client.post(
        '/api/validate',
        data={'mode': 'card'},
        files={'frame': ('f.jpg', _jpeg_bytes(rgb), 'image/jpeg')},
    )
    assert r.status_code == 400


def test_validate_paper(client):
    rgb, _ = make_sample(512)
    r = client.post(
        '/api/validate',
        data={'mode': 'paper'},
        files={'frame': ('f.jpg', _jpeg_bytes(rgb), 'image/jpeg')},
    )
    assert r.status_code == 200
    body = r.json()
    assert 'ready' in body
    assert 'checks' in body
    assert 'tilt' in body['checks']


def test_job_paper_burst(client):
    frames = [_jpeg_bytes(make_sample(512)[0]) for _ in range(3)]
    files = [('images', (f'c{i}.jpg', frames[i], 'image/jpeg')) for i in range(3)]
    r = client.post('/api/jobs', data={'mode': 'paper'}, files=files)
    assert r.status_code == 200
    job_id = r.json()['job_id']
    # Poll
    import time
    for _ in range(40):
        j = client.get(f'/api/jobs/{job_id}').json()
        if j['status'] in ('done', 'error'):
            break
        time.sleep(0.25)
    assert j['status'] in ('done', 'error')
    if j['status'] == 'done':
        assert 'cm' in j['result']
        # Rounded to 0.5
        cm = j['result']['cm']
        assert abs(cm * 2 - round(cm * 2)) < 1e-6
