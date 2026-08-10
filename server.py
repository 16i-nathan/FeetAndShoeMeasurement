"""
Foot Measure production API (A4 paper + ML segmentation).

Used by the Flutter app for live Ready checks and background measurement.

Run:
  uvicorn server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import io
import os
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageOps

from capture_validate import validate_frame
from job_store import JobStore
from ml_measure import MeasureError, measure_burst_median, measure_paper_ml
from seg_infer import load_model_card, model_load_error, model_loaded
from shoe_size import sizes_from_cm

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / 'output' / 'uploads'
JOBS_DIR = ROOT / 'output' / 'jobs'
STORE = JobStore()

LAB_MODES = os.environ.get('LAB_MODES', '0') == '1'
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get('CORS_ORIGINS', '*').split(',')
    if o.strip()
]
RATE_LIMIT_PER_MIN = int(os.environ.get('RATE_LIMIT_PER_MIN', '60'))

app = FastAPI(title='Foot Measure API', version='3.0.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ['*'] else ['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

_rate: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    if request.client:
        return request.client.host
    return 'unknown'


def _check_rate(request: Request):
    if RATE_LIMIT_PER_MIN <= 0:
        return
    ip = _client_ip(request)
    now = time.time()
    with _rate_lock:
        window = [t for t in _rate[ip] if now - t < 60.0]
        if len(window) >= RATE_LIMIT_PER_MIN:
            raise HTTPException(status_code=429, detail='Rate limit exceeded')
        window.append(now)
        _rate[ip] = window


def _read_rgb(data: bytes, max_side: int = 1600):
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert('RGB')
    w, h = img.size
    long_side = max(w, h)
    scale = 1.0
    if long_side > max_side:
        scale = max_side / long_side
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    return np.asarray(img), scale


def _downscale(rgb: np.ndarray, max_side: int = 480) -> np.ndarray:
    h, w = rgb.shape[:2]
    long_side = max(h, w)
    if long_side <= max_side:
        return rgb
    scale = max_side / long_side
    return cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def _round_cm(cm: float) -> float:
    return round(cm * 2) / 2.0


def _assert_mode(mode: str):
    if mode in ('paper', 'depth'):
        return
    if LAB_MODES and mode in ('card', 'both'):
        return
    raise HTTPException(
        status_code=400,
        detail='Supported modes: paper, depth. Set LAB_MODES=1 for card/both.',
    )


def _run_job(job_id: str):
    job = STORE.get(job_id)
    if not job:
        return
    STORE.update(job_id, status='running', started_at=time.time())
    mode = job['mode']
    out_dir = Path(job['out_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = job.get('rgb_paths') or [job['rgb_path']]
        rgbs = []
        for p in paths:
            rgb, _ = _read_rgb(Path(p).read_bytes())
            rgbs.append(rgb)

        if mode == 'paper':
            if len(rgbs) > 1:
                measured = measure_burst_median(rgbs, out_dir=out_dir)
            else:
                measured = measure_paper_ml(rgbs[0], out_dir=out_dir)
            cm = measured['cm']
            sizes = sizes_from_cm(cm)
            sizes['cm'] = _round_cm(cm)
            sizes['cm_raw'] = round(float(cm), 2)
            sizes['cm_spread'] = round(float(measured.get('cm_spread', 0.0)), 2)
            sizes['confidence'] = round(float(measured.get('confidence', 0.0)), 3)
            preview = None
            preview_file = out_dir / 'preview.jpg'
            if not preview_file.is_file():
                alt = out_dir / 'frame_0' / 'preview.jpg'
                if alt.is_file():
                    preview_file = alt
            if preview_file.is_file():
                preview = f'/output/jobs/{job_id}/{preview_file.relative_to(out_dir).as_posix()}'
            STORE.update(
                job_id,
                status='done',
                finished_at=time.time(),
                result=sizes,
                preview_url=preview,
                error=None,
                meta={
                    'seg_source': measured.get('seg_source'),
                    'paper_score': measured.get('paper_score'),
                    'foot_score': measured.get('foot_score'),
                    'n_ok': measured.get('n_ok', 1),
                },
            )
            return

        if mode == 'depth':
            from main import measure_with_depth

            depth_path = job.get('depth_path')
            if not depth_path:
                raise ValueError('Depth mode needs a depth map from LiDAR/AR capture')
            rgb = rgbs[0]
            fx = job.get('fx')
            fy = job.get('fy')
            cx = job.get('cx')
            cy = job.get('cy')
            # Re-read with scale for intrinsics if image was downscaled on load
            _, img_scale = _read_rgb(Path(job['rgb_path']).read_bytes())
            fx_s = fx * img_scale if fx is not None else None
            fy_s = fy * img_scale if fy is not None else None
            cx_s = cx * img_scale if cx is not None else None
            cy_s = cy * img_scale if cy is not None else None
            cm = measure_with_depth(
                rgb,
                depth_path,
                depth_scale=job.get('depth_scale'),
                fx=fx_s,
                fy=fy_s,
                cx=cx_s,
                cy=cy_s,
            )
            sizes = sizes_from_cm(cm)
            sizes['cm'] = _round_cm(cm)
            sizes['cm_raw'] = round(float(cm), 2)
            sizes['confidence'] = 0.85
            preview = None
            for name in ('depth_detect.jpg', 'depth_vis.jpg'):
                src = ROOT / 'output' / name
                if src.is_file():
                    dest = out_dir / name
                    dest.write_bytes(src.read_bytes())
                    preview = f'/output/jobs/{job_id}/{name}'
                    break
            STORE.update(
                job_id,
                status='done',
                finished_at=time.time(),
                result=sizes,
                preview_url=preview,
                error=None,
                meta={'mode': 'depth'},
            )
            return

        # Lab RGB modes
        from main import measure_with_both, measure_with_card

        rgb = rgbs[0]
        if mode == 'card':
            cm = measure_with_card(rgb)
        elif mode == 'both':
            cm = measure_with_both(rgb)
        else:
            raise ValueError(f'Unsupported mode: {mode}')
        sizes = sizes_from_cm(cm)
        sizes['cm'] = _round_cm(cm)
        STORE.update(
            job_id,
            status='done',
            finished_at=time.time(),
            result=sizes,
            preview_url=None,
            error=None,
        )
    except MeasureError as e:
        STORE.update(
            job_id,
            status='error',
            finished_at=time.time(),
            error=e.message,
            error_code=e.code,
        )
    except Exception as e:
        STORE.update(
            job_id,
            status='error',
            finished_at=time.time(),
            error=str(e),
            error_code='ERROR',
        )


@app.on_event('startup')
def _startup():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    load_model_card()
    model_loaded()  # warm attempt
    STORE.cleanup(ttl_seconds=float(os.environ.get('JOB_TTL_SECONDS', '86400')))


@app.get('/api/health')
def health():
    loaded = model_loaded()
    return {
        'ok': True,
        'service': 'foot-measure-api',
        'version': '3.0.0',
        'model_loaded': loaded,
        'model_error': model_load_error(),
        'lab_modes': LAB_MODES,
        'model_card': load_model_card().get('version'),
    }


@app.post('/api/validate')
async def api_validate(
    request: Request,
    frame: UploadFile = File(...),
    mode: str = Form('paper'),
):
    _check_rate(request)
    _assert_mode(mode)
    data = await frame.read()
    if not data:
        return {'ready': False, 'message': 'Empty frame', 'checks': {}, 'hints': []}
    rgb, _ = _read_rgb(data, max_side=960)
    rgb = _downscale(rgb, max_side=480)
    return validate_frame(rgb, mode=mode)


@app.post('/api/jobs')
async def create_job(
    request: Request,
    image: UploadFile | None = File(None),
    images: list[UploadFile] | None = File(None),
    mode: str = Form('paper'),
    depth: UploadFile | None = File(None),
    depth_scale: float | None = Form(None),
    fx: float | None = Form(None),
    fy: float | None = Form(None),
    cx: float | None = Form(None),
    cy: float | None = Form(None),
):
    _check_rate(request)
    _assert_mode(mode)

    files: list[UploadFile] = []
    if images:
        files.extend(images)
    if image is not None and image.filename:
        files.append(image)
    if not files:
        raise HTTPException(status_code=400, detail='Provide image or images')

    UPLOADS.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex[:12]
    out_dir = JOBS_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rgb_paths = []
    for i, f in enumerate(files[:3]):
        path = UPLOADS / f'{job_id}_{i}.jpg'
        path.write_bytes(await f.read())
        rgb_paths.append(str(path))

    depth_path = None
    if depth is not None and depth.filename:
        ext = Path(depth.filename).suffix.lower() or '.npy'
        depth_path = str(UPLOADS / f'{job_id}_depth{ext}')
        Path(depth_path).write_bytes(await depth.read())

    job = {
        'id': job_id,
        'status': 'queued',
        'mode': mode,
        'rgb_path': rgb_paths[0],
        'rgb_paths': rgb_paths,
        'out_dir': str(out_dir),
        'depth_path': depth_path,
        'depth_scale': depth_scale,
        'fx': fx,
        'fy': fy,
        'cx': cx,
        'cy': cy,
        'created_at': time.time(),
        'result': None,
        'preview_url': None,
        'error': None,
    }
    STORE.put(job_id, job)

    if mode == 'depth' and depth_path is None:
        STORE.update(
            job_id,
            status='awaiting_depth',
            message='No depth map received.',
        )
        return {'job_id': job_id, 'status': 'awaiting_depth'}

    threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    return {'job_id': job_id, 'status': 'queued'}


@app.get('/api/jobs/{job_id}')
def get_job(job_id: str):
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Unknown job')
    return {
        'id': job['id'],
        'status': job['status'],
        'mode': job['mode'],
        'message': job.get('message'),
        'result': job.get('result'),
        'preview_url': job.get('preview_url'),
        'error': job.get('error'),
        'error_code': job.get('error_code'),
        'meta': job.get('meta'),
    }


@app.get('/output/jobs/{job_id}/{name:path}')
def serve_job_output(job_id: str, name: str):
    path = (JOBS_DIR / job_id / name).resolve()
    if not str(path).startswith(str(JOBS_DIR.resolve())):
        raise HTTPException(status_code=400, detail='Invalid path')
    if not path.is_file():
        raise HTTPException(status_code=404, detail='not found')
    return FileResponse(path)


@app.get('/output/{name}')
def serve_output(name: str):
    path = ROOT / 'output' / name
    if not path.is_file():
        return JSONResponse({'error': 'not found'}, status_code=404)
    return FileResponse(path)
