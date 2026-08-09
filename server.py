"""
Live capture API + static camera UI.

Run:
  uvicorn server:app --host 0.0.0.0 --port 8000
Open:
  http://localhost:8000/
"""

from __future__ import annotations

import io
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

from capture_validate import validate_frame
from main import (
    ensure_output_dir,
    measure_with_both,
    measure_with_card,
    measure_with_depth,
    measure_with_paper,
)
from shoe_size import sizes_from_cm

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / 'static'
UPLOADS = ROOT / 'output' / 'uploads'
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

app = FastAPI(title='Foot Measure Capture', version='1.0.0')


def _read_rgb(data: bytes, max_side: int = 1600) -> np.ndarray:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert('RGB')
    w, h = img.size
    long_side = max(w, h)
    if long_side > max_side:
        scale = max_side / long_side
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    return np.asarray(img)


def _downscale(rgb: np.ndarray, max_side: int = 480) -> np.ndarray:
    h, w = rgb.shape[:2]
    long_side = max(h, w)
    if long_side <= max_side:
        return rgb
    scale = max_side / long_side
    return cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def _run_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS[job_id]
        job['status'] = 'running'
        job['started_at'] = time.time()
        mode = job['mode']
        rgb_path = Path(job['rgb_path'])
        depth_path = job.get('depth_path')
        depth_scale = job.get('depth_scale')

    try:
        ensure_output_dir()
        data = rgb_path.read_bytes()
        rgb = _read_rgb(data)
        if mode == 'paper':
            cm = measure_with_paper(rgb)
        elif mode == 'card':
            cm = measure_with_card(rgb)
        elif mode == 'both':
            cm = measure_with_both(rgb)
        else:
            if not depth_path:
                raise ValueError(
                    'Depth mode needs a depth map. Capture saved the photo; '
                    'upload a LiDAR depth file to finish, or use card mode.'
                )
            cm = measure_with_depth(rgb, depth_path, depth_scale=depth_scale)

        sizes = sizes_from_cm(cm)
        preview = None
        for name in ('card_detect.jpg', 'depth_detect.jpg', 'fdraw.jpg', 'pdraw.jpg'):
            p = ROOT / 'output' / name
            if p.is_file():
                preview = f'/output/{name}?t={int(time.time())}'
                break

        with JOBS_LOCK:
            JOBS[job_id].update({
                'status': 'done',
                'finished_at': time.time(),
                'result': sizes,
                'preview_url': preview,
                'error': None,
            })
    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id].update({
                'status': 'error',
                'finished_at': time.time(),
                'error': str(e),
            })


@app.get('/api/health')
def health():
    return {'ok': True}


@app.post('/api/validate')
async def api_validate(
    frame: UploadFile = File(...),
    mode: str = Form('card'),
):
    data = await frame.read()
    if not data:
        return {'ready': False, 'message': 'Empty frame', 'checks': {}, 'hints': []}
    rgb = _read_rgb(data, max_side=960)
    rgb = _downscale(rgb, max_side=480)
    return validate_frame(rgb, mode=mode)


@app.post('/api/jobs')
async def create_job(
    image: UploadFile = File(...),
    mode: str = Form('card'),
    depth: UploadFile | None = File(None),
    depth_scale: float | None = Form(None),
):
    if mode not in ('paper', 'card', 'both', 'depth'):
        return {'error': 'Invalid mode'}

    UPLOADS.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    rgb_path = UPLOADS / f'{job_id}.jpg'
    raw = await image.read()
    rgb_path.write_bytes(raw)

    depth_path = None
    if depth is not None and depth.filename:
        ext = Path(depth.filename).suffix.lower() or '.npy'
        depth_path = str(UPLOADS / f'{job_id}_depth{ext}')
        Path(depth_path).write_bytes(await depth.read())

    with JOBS_LOCK:
        JOBS[job_id] = {
            'id': job_id,
            'status': 'queued',
            'mode': mode,
            'rgb_path': str(rgb_path),
            'depth_path': depth_path,
            'depth_scale': depth_scale,
            'created_at': time.time(),
            'result': None,
            'preview_url': None,
            'error': None,
        }

    # Depth without file: accept capture, finish later when depth arrives
    if mode == 'depth' and depth_path is None:
        with JOBS_LOCK:
            JOBS[job_id]['status'] = 'awaiting_depth'
            JOBS[job_id]['message'] = (
                'Photo captured. Attach a depth map to finish, or switch to card mode.'
            )
        return {'job_id': job_id, 'status': 'awaiting_depth'}

    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return {'job_id': job_id, 'status': 'queued'}


@app.post('/api/jobs/{job_id}/depth')
async def attach_depth(
    job_id: str,
    depth: UploadFile = File(...),
    depth_scale: float | None = Form(None),
):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {'error': 'Unknown job'}
        if job['status'] not in ('awaiting_depth', 'error'):
            return {'error': f'Job not waiting for depth (status={job["status"]})'}

    UPLOADS.mkdir(parents=True, exist_ok=True)
    ext = Path(depth.filename or 'depth.npy').suffix.lower() or '.npy'
    depth_path = UPLOADS / f'{job_id}_depth{ext}'
    depth_path.write_bytes(await depth.read())

    with JOBS_LOCK:
        JOBS[job_id]['depth_path'] = str(depth_path)
        JOBS[job_id]['depth_scale'] = depth_scale
        JOBS[job_id]['status'] = 'queued'
        JOBS[job_id]['mode'] = 'depth'

    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return {'job_id': job_id, 'status': 'queued'}


@app.get('/api/jobs/{job_id}')
def get_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {'error': 'Unknown job'}
        return {
            'id': job['id'],
            'status': job['status'],
            'mode': job['mode'],
            'message': job.get('message'),
            'result': job.get('result'),
            'preview_url': job.get('preview_url'),
            'error': job.get('error'),
        }


@app.get('/output/{name}')
def serve_output(name: str):
    path = ROOT / 'output' / name
    if not path.is_file():
        return {'error': 'not found'}
    return FileResponse(path)


app.mount('/', StaticFiles(directory=str(STATIC), html=True), name='static')
