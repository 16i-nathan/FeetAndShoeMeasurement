"""Durable analysis tries — survives job TTL cleanup."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / 'output' / 'analysis.sqlite3'

_LOCK = threading.Lock()


def error_mm(pred_cm: float | None, truth_cm: float) -> float | None:
    if pred_cm is None:
        return None
    return round((float(pred_cm) - float(truth_cm)) * 10.0, 2)


def score_from_abs_mm(abs_err_mm: float | None) -> float | None:
    """0..1 score: 0 mm → 1.0, 20 mm → 0.0 (linear clamp)."""
    if abs_err_mm is None:
        return None
    return round(max(0.0, min(1.0, 1.0 - float(abs_err_mm) / 20.0)), 3)


def pick_winner(
    local_abs: float | None, gemini_abs: float | None
) -> str | None:
    if local_abs is None and gemini_abs is None:
        return None
    if local_abs is None:
        return 'gemini'
    if gemini_abs is None:
        return 'local'
    if abs(local_abs - gemini_abs) < 0.05:
        return 'tie'
    return 'local' if local_abs < gemini_abs else 'gemini'


class AnalysisStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with _LOCK:
            conn = self._conn()
            try:
                conn.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS tries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        truth_cm REAL NOT NULL,
                        local_cm REAL,
                        gemini_cm REAL,
                        primary_cm REAL,
                        local_error_mm REAL,
                        gemini_error_mm REAL,
                        primary_error_mm REAL,
                        local_score REAL,
                        gemini_score REAL,
                        primary_score REAL,
                        winner TEXT,
                        confidence REAL,
                        notes TEXT,
                        payload TEXT,
                        created_at REAL NOT NULL
                    )
                    '''
                )
                conn.execute(
                    'CREATE INDEX IF NOT EXISTS idx_tries_job ON tries(job_id)'
                )
                conn.execute(
                    'CREATE INDEX IF NOT EXISTS idx_tries_created ON tries(created_at)'
                )
                conn.commit()
            finally:
                conn.close()

    def upsert_truth(
        self,
        *,
        job_id: str,
        mode: str,
        truth_cm: float,
        local_cm: float | None = None,
        gemini_cm: float | None = None,
        primary_cm: float | None = None,
        confidence: float | None = None,
        notes: str = '',
        extra: dict | None = None,
    ) -> dict:
        local_err = error_mm(local_cm, truth_cm)
        gemini_err = error_mm(gemini_cm, truth_cm)
        primary_err = error_mm(primary_cm, truth_cm)
        local_abs = abs(local_err) if local_err is not None else None
        gemini_abs = abs(gemini_err) if gemini_err is not None else None
        primary_abs = abs(primary_err) if primary_err is not None else None
        row = {
            'job_id': job_id,
            'mode': mode,
            'truth_cm': round(float(truth_cm), 2),
            'local_cm': None if local_cm is None else round(float(local_cm), 2),
            'gemini_cm': None if gemini_cm is None else round(float(gemini_cm), 2),
            'primary_cm': None if primary_cm is None else round(float(primary_cm), 2),
            'local_error_mm': local_err,
            'gemini_error_mm': gemini_err,
            'primary_error_mm': primary_err,
            'local_score': score_from_abs_mm(local_abs),
            'gemini_score': score_from_abs_mm(gemini_abs),
            'primary_score': score_from_abs_mm(primary_abs),
            'winner': pick_winner(local_abs, gemini_abs),
            'confidence': confidence,
            'notes': notes or '',
            'created_at': time.time(),
        }
        payload = json.dumps({**(extra or {}), **row})
        with _LOCK:
            conn = self._conn()
            try:
                existing = conn.execute(
                    'SELECT id FROM tries WHERE job_id = ? ORDER BY id DESC LIMIT 1',
                    (job_id,),
                ).fetchone()
                if existing:
                    conn.execute(
                        '''
                        UPDATE tries SET
                            mode=?, truth_cm=?, local_cm=?, gemini_cm=?, primary_cm=?,
                            local_error_mm=?, gemini_error_mm=?, primary_error_mm=?,
                            local_score=?, gemini_score=?, primary_score=?,
                            winner=?, confidence=?, notes=?, payload=?, created_at=?
                        WHERE id=?
                        ''',
                        (
                            row['mode'],
                            row['truth_cm'],
                            row['local_cm'],
                            row['gemini_cm'],
                            row['primary_cm'],
                            row['local_error_mm'],
                            row['gemini_error_mm'],
                            row['primary_error_mm'],
                            row['local_score'],
                            row['gemini_score'],
                            row['primary_score'],
                            row['winner'],
                            row['confidence'],
                            row['notes'],
                            payload,
                            row['created_at'],
                            existing['id'],
                        ),
                    )
                    row['id'] = int(existing['id'])
                else:
                    cur = conn.execute(
                        '''
                        INSERT INTO tries (
                            job_id, mode, truth_cm, local_cm, gemini_cm, primary_cm,
                            local_error_mm, gemini_error_mm, primary_error_mm,
                            local_score, gemini_score, primary_score,
                            winner, confidence, notes, payload, created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ''',
                        (
                            row['job_id'],
                            row['mode'],
                            row['truth_cm'],
                            row['local_cm'],
                            row['gemini_cm'],
                            row['primary_cm'],
                            row['local_error_mm'],
                            row['gemini_error_mm'],
                            row['primary_error_mm'],
                            row['local_score'],
                            row['gemini_score'],
                            row['primary_score'],
                            row['winner'],
                            row['confidence'],
                            row['notes'],
                            payload,
                            row['created_at'],
                        ),
                    )
                    row['id'] = int(cur.lastrowid)
                conn.commit()
            finally:
                conn.close()
        return row

    def list_tries(self, limit: int = 200) -> list[dict]:
        with _LOCK:
            conn = self._conn()
            try:
                rows = conn.execute(
                    '''
                    SELECT id, job_id, mode, truth_cm, local_cm, gemini_cm, primary_cm,
                           local_error_mm, gemini_error_mm, primary_error_mm,
                           local_score, gemini_score, primary_score,
                           winner, confidence, notes, created_at
                    FROM tries
                    ORDER BY created_at DESC
                    LIMIT ?
                    ''',
                    (int(limit),),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def summary(self) -> dict:
        tries = self.list_tries(limit=5000)
        n = len(tries)
        if n == 0:
            return {
                'n': 0,
                'local_mae_mm': None,
                'gemini_mae_mm': None,
                'primary_mae_mm': None,
                'local_mean_score': None,
                'gemini_mean_score': None,
                'wins': {'local': 0, 'gemini': 0, 'tie': 0},
            }

        def mae(key: str) -> float | None:
            vals = [abs(t[key]) for t in tries if t.get(key) is not None]
            if not vals:
                return None
            return round(sum(vals) / len(vals), 2)

        def mean_score(key: str) -> float | None:
            vals = [t[key] for t in tries if t.get(key) is not None]
            if not vals:
                return None
            return round(sum(vals) / len(vals), 3)

        wins = {'local': 0, 'gemini': 0, 'tie': 0}
        for t in tries:
            w = t.get('winner')
            if w in wins:
                wins[w] += 1

        return {
            'n': n,
            'local_mae_mm': mae('local_error_mm'),
            'gemini_mae_mm': mae('gemini_error_mm'),
            'primary_mae_mm': mae('primary_error_mm'),
            'local_mean_score': mean_score('local_score'),
            'gemini_mean_score': mean_score('gemini_score'),
            'wins': wins,
        }
