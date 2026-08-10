"""SQLite-backed job store for production API."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / 'output' / 'jobs.sqlite3'

_LOCK = threading.Lock()


class JobStore:
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
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    '''
                )
                conn.commit()
            finally:
                conn.close()

    def put(self, job_id: str, data: dict):
        now = time.time()
        payload = json.dumps(data)
        with _LOCK:
            conn = self._conn()
            try:
                conn.execute(
                    '''
                    INSERT INTO jobs (id, status, mode, payload, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        status=excluded.status,
                        mode=excluded.mode,
                        payload=excluded.payload,
                        updated_at=excluded.updated_at
                    ''',
                    (
                        job_id,
                        data.get('status', 'queued'),
                        data.get('mode', 'paper'),
                        payload,
                        data.get('created_at', now),
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get(self, job_id: str) -> dict | None:
        with _LOCK:
            conn = self._conn()
            try:
                row = conn.execute(
                    'SELECT payload FROM jobs WHERE id = ?', (job_id,)
                ).fetchone()
                if not row:
                    return None
                return json.loads(row['payload'])
            finally:
                conn.close()

    def update(self, job_id: str, **fields):
        job = self.get(job_id)
        if not job:
            return None
        job.update(fields)
        self.put(job_id, job)
        return job

    def cleanup(self, ttl_seconds: float = 86400.0) -> int:
        cutoff = time.time() - ttl_seconds
        with _LOCK:
            conn = self._conn()
            try:
                cur = conn.execute('DELETE FROM jobs WHERE updated_at < ?', (cutoff,))
                conn.commit()
                return cur.rowcount or 0
            finally:
                conn.close()
