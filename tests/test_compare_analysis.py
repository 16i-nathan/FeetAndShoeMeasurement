"""Compare mode + truth scoring + analysis store."""

from __future__ import annotations

import os
import sys
import time
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

from analysis_store import AnalysisStore, pick_winner, score_from_abs_mm  # noqa: E402
from training.synthesize import make_sample  # noqa: E402
import server  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'ANALYSIS', AnalysisStore(tmp_path / 'analysis.sqlite3'))
    monkeypatch.setattr(server, 'STORE', server.JobStore(tmp_path / 'jobs.sqlite3'))
    return TestClient(server.app)


def _jpeg_bytes(rgb: np.ndarray) -> bytes:
    ok, buf = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    assert ok
    return buf.tobytes()


def test_score_helpers():
    assert score_from_abs_mm(0) == 1.0
    assert score_from_abs_mm(20) == 0.0
    assert pick_winner(2.0, 5.0) == 'local'
    assert pick_winner(5.0, 2.0) == 'gemini'
    assert pick_winner(3.0, 3.0) == 'tie'


def test_health_depth_and_modes(client, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    r = client.get('/api/health')
    assert r.status_code == 200
    body = r.json()
    assert body['depth_enabled'] is True
    assert 'paper' in body['modes']
    assert 'depth' in body['modes']
    assert 'compare' not in body['modes']


def test_compare_job_and_truth(client, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')

    def fake_local(rgb, out_dir=None, px_per_mm=2.0):
        if out_dir is not None:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        return {
            'cm': 26.0,
            'confidence': 0.8,
            'seg_source': 'test',
            'paper_score': 0.9,
            'foot_score': 0.85,
        }

    def fake_gemini(rgb, out_dir=None, px_per_mm=2.0):
        if out_dir is not None:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        return {
            'cm': 26.8,
            'confidence': 0.91,
            'method': 'ai_length_cm',
            'seg_source': 'gemini-cm:test',
            'notes': '',
            'preview_path': None,
        }

    monkeypatch.setattr(server, 'measure_paper_ml', fake_local)
    monkeypatch.setattr(server, 'measure_paper_gemini', fake_gemini)

    rgb, _ = make_sample(512)
    r = client.post(
        '/api/jobs',
        data={'mode': 'compare'},
        files={'image': ('c.jpg', _jpeg_bytes(rgb), 'image/jpeg')},
    )
    assert r.status_code == 200
    job_id = r.json()['job_id']
    for _ in range(40):
        j = client.get(f'/api/jobs/{job_id}').json()
        if j['status'] in ('done', 'error'):
            break
        time.sleep(0.1)
    assert j['status'] == 'done'
    assert j['result']['compare']['local']['cm'] == 26.0
    assert j['result']['compare']['gemini']['cm'] == 27.0  # rounded 26.8 → 27.0
    assert j['result']['backend'] == 'gemini'

    t = client.post(f'/api/jobs/{job_id}/truth', json={'truth_cm': 26.5})
    assert t.status_code == 200
    body = t.json()
    assert body['ok'] is True
    assert body['truth_cm'] == 26.5
    assert body['winner'] in ('local', 'gemini', 'tie')
    assert body['scores']['local'] is not None
    assert body['scores']['gemini'] is not None

    s = client.get('/api/analysis/summary').json()
    assert s['n'] >= 1
    tries = client.get('/api/analysis/tries').json()['tries']
    assert any(x['job_id'] == job_id for x in tries)

    dash = client.get('/dashboard')
    assert dash.status_code == 200
    assert b'Measurement analysis' in dash.content


def test_paper_truth_records_local_only(client, monkeypatch):
    def fake_paper(rgb, out_dir=None, px_per_mm=2.0):
        return {
            'cm': 25.5,
            'confidence': 0.7,
            'seg_source': 'test',
            'paper_score': 0.8,
            'foot_score': 0.75,
            'cm_spread': 0.0,
            'n_ok': 1,
        }

    monkeypatch.setattr(server, 'measure_paper_ml', fake_paper)
    monkeypatch.setattr(server, 'measure_burst_median', fake_paper)

    rgb, _ = make_sample(512)
    r = client.post(
        '/api/jobs',
        data={'mode': 'paper'},
        files={'image': ('c.jpg', _jpeg_bytes(rgb), 'image/jpeg')},
    )
    job_id = r.json()['job_id']
    for _ in range(40):
        j = client.get(f'/api/jobs/{job_id}').json()
        if j['status'] in ('done', 'error'):
            break
        time.sleep(0.1)
    assert j['status'] == 'done'
    t = client.post(f'/api/jobs/{job_id}/truth', json={'truth_cm': 25.0})
    assert t.status_code == 200
    assert t.json()['scores']['local'] is not None
    assert t.json()['scores']['gemini'] is None
