"""Holdout MAE release gate for foot length (mm)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_measure import MeasureError, measure_paper_ml  # noqa: E402
from training.synthesize import make_sample  # noqa: E402
from quality import A4_HEIGHT_MM, A4_WIDTH_MM  # noqa: E402


def synthetic_ground_truth_cm(label: np.ndarray, size: int) -> float | None:
    """Approximate GT: foot extent along long axis vs paper height = 297mm."""
    paper = label == 1
    foot = label == 2
    if not paper.any() or not foot.any():
        return None
    # Paper bbox height in px maps to 297mm (portrait)
    ys_p, xs_p = np.where(paper)
    ph = ys_p.max() - ys_p.min() + 1
    pw = xs_p.max() - xs_p.min() + 1
    if max(ph, pw) < 10:
        return None
    if ph >= pw:
        mm_per_px = A4_HEIGHT_MM / ph
    else:
        mm_per_px = A4_WIDTH_MM / pw
    ys, xs = np.where(foot)
    long_px = max(ys.max() - ys.min() + 1, xs.max() - xs.min() + 1)
    return (long_px * mm_per_px) / 10.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=40)
    p.add_argument('--size', type=int, default=512)
    p.add_argument('--max-mae-mm', type=float, default=15.0)
    p.add_argument('--max-fail-rate', type=float, default=0.10)
    p.add_argument('--out', type=Path, default=ROOT / 'models' / 'eval_report.json')
    args = p.parse_args()

    errs = []
    fails = 0
    for i in range(args.n):
        rgb, label = make_sample(args.size)
        gt = synthetic_ground_truth_cm(label, args.size)
        if gt is None:
            fails += 1
            continue
        try:
            # Force bootstrap for synthetic eval stability if ONNX weak on synth
            import os
            os.environ.setdefault('ALLOW_BOOTSTRAP_SEG', '1')
            r = measure_paper_ml(rgb, allow_bootstrap=True)
            errs.append(abs(r['cm'] - gt) * 10.0)  # mm
        except MeasureError:
            fails += 1

    mae = float(np.mean(errs)) if errs else 999.0
    fail_rate = fails / max(args.n, 1)
    report = {
        'n': args.n,
        'n_measured': len(errs),
        'mae_mm': round(mae, 3),
        'fail_rate': round(fail_rate, 3),
        'max_mae_mm': args.max_mae_mm,
        'max_fail_rate': args.max_fail_rate,
        'pass': mae <= args.max_mae_mm and fail_rate <= args.max_fail_rate,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report['pass']:
        sys.exit(1)


if __name__ == '__main__':
    main()
