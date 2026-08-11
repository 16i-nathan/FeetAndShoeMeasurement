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

from analysis_store import AnalysisStore
from capture_validate import validate_frame
from gemini_measure import gemini_configured, gemini_model_name, measure_paper_gemini
from job_store import JobStore
from ml_measure import MeasureError, measure_burst_median, measure_paper_ml
from seg_infer import load_model_card, model_load_error, model_loaded
from shoe_size import sizes_from_cm

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / 'output' / 'uploads'
JOBS_DIR = ROOT / 'output' / 'jobs'
STORE = JobStore()
ANALYSIS = AnalysisStore()
DASHBOARD_HTML = ROOT / 'static' / 'dashboard.html'

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


def _pack_sizes(cm: float, confidence: float | None = None, **extra) -> dict:
    sizes = sizes_from_cm(cm)
    sizes['cm'] = _round_cm(cm)
    sizes['cm_raw'] = round(float(cm), 2)
    if confidence is not None:
        sizes['confidence'] = round(float(confidence), 3)
    sizes.update(extra)
    return sizes


def _assert_mode(mode: str):
    if mode in ('paper', 'depth'):
        return
    if mode in ('gemini', 'compare'):
        if gemini_configured():
            return
        raise HTTPException(
            status_code=400,
            detail='Gemini not configured. Set GEMINI_API_KEY.',
        )
    if LAB_MODES and mode in ('card', 'both'):
        return
    raise HTTPException(
        status_code=400,
        detail=(
            'Supported modes: paper, depth'
            + (', gemini, compare' if gemini_configured() else '')
            + '. Set LAB_MODES=1 for card/both.'
        ),
    )


def _run_compare(job_id: str, rgb: np.ndarray, out_dir: Path) -> None:
    """Local paper ML + Gemini in one job. Primary result prefers Gemini."""
    local_dir = out_dir / 'local'
    gemini_dir = out_dir / 'gemini'
    local_dir.mkdir(parents=True, exist_ok=True)
    gemini_dir.mkdir(parents=True, exist_ok=True)

    local_block: dict = {'cm': None, 'cm_raw': None, 'confidence': None, 'error': None}
    gemini_block: dict = {'cm': None, 'cm_raw': None, 'confidence': None, 'error': None}
    local_ok = False
    gemini_ok = False
    local_meta: dict = {}
    gemini_meta: dict = {}

    try:
        local_m = measure_paper_ml(rgb, out_dir=local_dir)
        local_ok = True
        local_block = {
            'cm': _round_cm(local_m['cm']),
            'cm_raw': round(float(local_m['cm']), 2),
            'confidence': round(float(local_m.get('confidence', 0.0)), 3),
            'error': None,
        }
        local_meta = {
            'seg_source': local_m.get('seg_source'),
            'paper_score': local_m.get('paper_score'),
            'foot_score': local_m.get('foot_score'),
        }
    except MeasureError as e:
        local_block['error'] = e.message
        local_meta = {'error_code': e.code}
    except Exception as e:
        local_block['error'] = str(e)
        local_meta = {'error_code': 'ERROR'}

    try:
        gemini_m = measure_paper_gemini(rgb, out_dir=gemini_dir)
        gemini_ok = True
        gemini_block = {
            'cm': _round_cm(gemini_m['cm']),
            'cm_raw': round(float(gemini_m['cm']), 2),
            'confidence': round(float(gemini_m.get('confidence', 0.0)), 3),
            'error': None,
        }
        gemini_meta = {
            'method': gemini_m.get('method'),
            'seg_source': gemini_m.get('seg_source'),
            'notes': gemini_m.get('notes') or '',
        }
    except MeasureError as e:
        gemini_block['error'] = e.message
        gemini_meta = {'error_code': e.code}
    except Exception as e:
        gemini_block['error'] = str(e)
        gemini_meta = {'error_code': 'ERROR'}

    if not local_ok and not gemini_ok:
        raise MeasureError(
            'COMPARE_FAIL',
            local_block.get('error') or gemini_block.get('error') or 'Both measures failed',
        )

    if gemini_ok:
        primary_cm = float(gemini_block['cm_raw'])
        primary_conf = gemini_block['confidence']
        backend = 'gemini'
    else:
        primary_cm = float(local_block['cm_raw'])
        primary_conf = local_block['confidence']
        backend = 'local'

    sizes = _pack_sizes(primary_cm, primary_conf)
    sizes['backend'] = backend
    sizes['method'] = 'compare_local_gemini'
    sizes['compare'] = {
        'local': local_block,
        'gemini': gemini_block,
        'truth_cm': None,
        'errors_mm': {'local': None, 'gemini': None},
        'scores': {'local': None, 'gemini': None},
    }

    preview = None
    local_prev = local_dir / 'preview.jpg'
    if local_prev.is_file():
        preview = f'/output/jobs/{job_id}/local/preview.jpg'

    STORE.update(
        job_id,
        status='done',
        finished_at=time.time(),
        result=sizes,
        preview_url=preview,
        error=None,
        truth_cm=None,
        meta={
            'local_ok': local_ok,
            'gemini_ok': gemini_ok,
            'backend': backend,
            'local': local_meta,
            'gemini': gemini_meta,
        },
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

        if mode == 'gemini':
            measured = measure_paper_gemini(rgbs[0], out_dir=out_dir)
            cm = measured['cm']
            sizes = sizes_from_cm(cm)
            sizes['cm'] = _round_cm(cm)
            sizes['cm_raw'] = round(float(cm), 2)
            sizes['confidence'] = round(float(measured.get('confidence', 0.0)), 3)
            STORE.update(
                job_id,
                status='done',
                finished_at=time.time(),
                result=sizes,
                preview_url=None,
                error=None,
                meta={
                    'method': measured.get('method'),
                    'seg_source': measured.get('seg_source'),
                    'notes': measured.get('notes') or '',
                },
            )
            return

        if mode == 'compare':
            _run_compare(job_id, rgbs[0], out_dir)
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
        'version': '3.1.0',
        'model_loaded': loaded,
        'model_error': model_load_error(),
        'lab_modes': LAB_MODES,
        'model_card': load_model_card().get('version'),
        'gemini_configured': gemini_configured(),
        'gemini_model': gemini_model_name(),
        # API always accepts mode=depth; device LiDAR/ARCore is checked on the phone.
        'depth_enabled': True,
        'modes': (
            ['paper', 'depth']
            + (['gemini', 'compare'] if gemini_configured() else [])
            + (['card', 'both'] if LAB_MODES else [])
        ),
    }


@app.get('/dashboard')
def dashboard():
    if not DASHBOARD_HTML.is_file():
        raise HTTPException(status_code=404, detail='Dashboard HTML missing')
    return FileResponse(DASHBOARD_HTML, media_type='text/html')


@app.get('/api/analysis/summary')
def analysis_summary():
    return ANALYSIS.summary()


@app.get('/api/analysis/tries')
def analysis_tries(limit: int = 200):
    limit = max(1, min(int(limit), 2000))
    return {'tries': ANALYSIS.list_tries(limit=limit)}


@app.get('/api/analysis/export')
def analysis_export():
    return JSONResponse(
        {
            'summary': ANALYSIS.summary(),
            'tries': ANALYSIS.list_tries(limit=5000),
        }
    )


@app.post('/api/jobs/{job_id}/truth')
async def submit_truth(job_id: str, request: Request):
    """Record manual ground-truth cm and score local / gemini / primary."""
    _check_rate(request)
    job = STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Unknown job')
    if job.get('status') != 'done':
        raise HTTPException(status_code=400, detail='Job is not done yet')
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail='JSON body required') from e
    try:
        truth_cm = float(body.get('truth_cm'))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail='truth_cm must be a number') from e
    if not (12.0 <= truth_cm <= 35.0):
        raise HTTPException(
            status_code=400,
            detail='truth_cm must be between 12 and 35 cm',
        )
    notes = str(body.get('notes') or '')

    result = dict(job.get('result') or {})
    compare = dict(result.get('compare') or {})
    local_cm = None
    gemini_cm = None
    if compare.get('local') and compare['local'].get('cm_raw') is not None:
        local_cm = float(compare['local']['cm_raw'])
    elif job.get('mode') == 'paper' and result.get('cm_raw') is not None:
        local_cm = float(result['cm_raw'])
    if compare.get('gemini') and compare['gemini'].get('cm_raw') is not None:
        gemini_cm = float(compare['gemini']['cm_raw'])
    elif job.get('mode') == 'gemini' and result.get('cm_raw') is not None:
        gemini_cm = float(result['cm_raw'])

    primary_cm = result.get('cm_raw')
    if primary_cm is not None:
        primary_cm = float(primary_cm)

    scored = ANALYSIS.upsert_truth(
        job_id=job_id,
        mode=job.get('mode') or 'unknown',
        truth_cm=truth_cm,
        local_cm=local_cm,
        gemini_cm=gemini_cm,
        primary_cm=primary_cm,
        confidence=result.get('confidence'),
        notes=notes,
        extra={'preview_url': job.get('preview_url')},
    )

    from analysis_store import error_mm

    errors = {
        'local': error_mm(local_cm, truth_cm),
        'gemini': error_mm(gemini_cm, truth_cm),
        'primary': error_mm(primary_cm, truth_cm),
    }
    if compare or job.get('mode') == 'compare':
        compare['truth_cm'] = round(truth_cm, 2)
        compare['errors_mm'] = {
            'local': errors['local'],
            'gemini': errors['gemini'],
        }
        compare['scores'] = {
            'local': scored.get('local_score'),
            'gemini': scored.get('gemini_score'),
        }
        result['compare'] = compare

    STORE.update(
        job_id,
        truth_cm=round(truth_cm, 2),
        result=result,
        analysis=scored,
    )
    return {
        'ok': True,
        'job_id': job_id,
        'truth_cm': round(truth_cm, 2),
        'errors_mm': errors,
        'scores': {
            'local': scored.get('local_score'),
            'gemini': scored.get('gemini_score'),
            'primary': scored.get('primary_score'),
        },
        'winner': scored.get('winner'),
        'result': result,
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
        'truth_cm': job.get('truth_cm'),
        'analysis': job.get('analysis'),
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
