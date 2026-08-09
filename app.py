"""
Streamlit test-group UI for foot measurement.

Run:
  streamlit run app.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import cv2
import numpy as np
import streamlit as st
from PIL import Image

from main import (
    ensure_output_dir,
    load_image,
    measure_with_both,
    measure_with_card,
    measure_with_depth,
    measure_with_paper,
)
from shoe_size import sizes_from_cm

st.set_page_config(
    page_title='Foot Measure Lab',
    page_icon='👣',
    layout='wide',
)

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'output'
CHART = ROOT / 'images' / 'ShoeSizeChart.png'

MODE_HELP = {
    'paper': 'A4 sheet fully in frame; foot on the paper; top-down.',
    'card': 'Standard credit/debit card beside the foot; top-down; full foot visible.',
    'both': 'A4 + card on/near the paper (best RGB accuracy).',
    'depth': 'RGB + metric depth map (LiDAR/ToF export). Normal photos are not enough.',
}

CHECKLIST = {
    'paper': [
        'Full A4 visible (all four corners)',
        'Foot fully on the paper (heel to toes)',
        'Top-down, not angled',
        'Floor is not white',
        'Even light, little glare',
    ],
    'card': [
        'Full card visible, flat, not covered',
        'Full foot visible (heel to toes)',
        'Card beside the foot, not on top of it',
        'Top-down, dark floor preferred',
        'Even light, little flash glare',
    ],
    'both': [
        'Full A4 visible',
        'Card fully visible on/near the paper',
        'Foot fully on the paper',
        'Top-down, even light',
    ],
    'depth': [
        'RGB and depth are from the same capture',
        'Depth is metric (meters .npy or mm 16-bit PNG)',
        'Depth aligned to the RGB image',
        'Full foot in frame, top-down',
    ],
}


def validate_rgb_upload(file) -> list[str]:
    errors = []
    if file is None:
        errors.append('Upload a photo.')
        return errors
    name = file.name.lower()
    if not name.endswith(('.jpg', '.jpeg', '.png', '.webp')):
        errors.append('Use JPG, PNG, or WebP.')
    if file.size > 25 * 1024 * 1024:
        errors.append('File is larger than 25 MB.')
    return errors


def validate_depth_upload(file, scale_mode: str) -> list[str]:
    errors = []
    if file is None:
        errors.append('Depth mode requires a depth file (.npy / 16-bit .png / .tif).')
        return errors
    name = file.name.lower()
    if not name.endswith(('.npy', '.png', '.tif', '.tiff')):
        errors.append('Depth must be .npy, .png, or .tif.')
    return errors


def save_upload(file, folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(file.getvalue())
    return path


def load_result_image(name: str):
    path = OUTPUT / name
    if not path.is_file():
        return None
    img = cv2.imread(str(path))
    if img is None:
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def run_measure(ref: str, rgb_path: Path, depth_path: Path | None, depth_scale, fx, fy):
    ensure_output_dir()
    oimg, img_scale = load_image(str(rgb_path))
    if ref == 'paper':
        return measure_with_paper(oimg)
    if ref == 'card':
        return measure_with_card(oimg)
    if ref == 'both':
        return measure_with_both(oimg)
    if depth_path is None:
        raise ValueError('Depth file missing.')
    fx_s = fx * img_scale if fx else None
    fy_s = fy * img_scale if fy else None
    return measure_with_depth(
        oimg,
        str(depth_path),
        depth_scale=depth_scale,
        fx=fx_s,
        fy=fy_s,
        hfov_deg=60.0,
    )


def main_ui():
    st.title('Foot Measure Lab')
    st.caption('Test build — paper / credit card / depth. Not medical or retail fitting advice.')

    with st.sidebar:
        st.header('Mode')
        ref = st.radio(
            'Reference',
            options=['card', 'paper', 'both', 'depth'],
            format_func=lambda m: {
                'card': 'Credit card (recommended)',
                'paper': 'A4 paper',
                'both': 'Paper + card',
                'depth': 'Depth / LiDAR',
            }[m],
            index=0,
        )
        st.info(MODE_HELP[ref])
        st.markdown('**Photo checklist**')
        for item in CHECKLIST[ref]:
            st.markdown(f'- {item}')

        st.divider()
        st.caption('Share this app with testers via `streamlit run app.py` (local) or Streamlit Community Cloud / a small VPS.')

    left, right = st.columns([1, 1], gap='large')

    with left:
        st.subheader('1. Upload')
        rgb_file = st.file_uploader(
            'Foot photo',
            type=['jpg', 'jpeg', 'png', 'webp'],
            help='Top-down photo. Phone EXIF rotation is applied automatically.',
        )
        depth_file = None
        depth_scale = None
        fx = fy = None
        if ref == 'depth':
            depth_file = st.file_uploader(
                'Depth map',
                type=['npy', 'png', 'tif', 'tiff'],
                help='Aligned depth from LiDAR/ToF export.',
            )
            unit = st.selectbox(
                'Depth units in file',
                ['meters (.npy default)', 'millimeters (16-bit PNG)'],
            )
            depth_scale = 1.0 if unit.startswith('meters') else 0.001
            with st.expander('Camera intrinsics (optional)'):
                fx = st.number_input('fx (pixels)', min_value=0.0, value=0.0, step=10.0)
                fy = st.number_input('fy (pixels)', min_value=0.0, value=0.0, step=10.0)
                fx = fx or None
                fy = fy or None

        if rgb_file is not None:
            from PIL import ImageOps
            preview = ImageOps.exif_transpose(Image.open(rgb_file)).convert('RGB')
            st.image(preview, caption='Input preview', use_container_width=True)

        run = st.button('Measure', type='primary', use_container_width=True)

    with right:
        st.subheader('2. Result')
        if not run:
            st.write('Upload a valid photo, then hit **Measure**.')
            if CHART.is_file():
                st.image(str(CHART), caption='Reference shoe size chart', use_container_width=True)
            return

        errors = validate_rgb_upload(rgb_file)
        if ref == 'depth':
            errors += validate_depth_upload(depth_file, '')
        if errors:
            for e in errors:
                st.error(e)
            return

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rgb_path = save_upload(rgb_file, tmp_path, rgb_file.name)
            depth_path = None
            if ref == 'depth' and depth_file is not None:
                depth_path = save_upload(depth_file, tmp_path, depth_file.name)

            # Work from project root so output/ paths match CLI
            os.chdir(ROOT)
            try:
                with st.spinner('Measuring…'):
                    cm = run_measure(ref, rgb_path, depth_path, depth_scale, fx, fy)
            except ValueError as e:
                st.error(str(e))
                st.warning('Fix the photo using the checklist, then retry.')
                return
            except Exception as e:
                st.error(f'Unexpected error: {e}')
                return

        sizes = sizes_from_cm(cm)
        st.success('Measurement complete')
        m1, m2, m3, m4 = st.columns(4)
        m1.metric('Foot length', f"{sizes['cm']} cm")
        m2.metric('EU (approx)', sizes['eu'])
        m3.metric('US Men (approx)', sizes['us_men'])
        m4.metric('US Women (approx)', sizes['us_women'])
        st.caption(f"Mode: `{ref}` · UK approx {sizes['uk']} · sizes are rough conversions for testing only.")

        st.subheader('Detection preview')
        if ref == 'depth':
            panels = [
                ('depth_detect.jpg', 'Foot on RGB'),
                ('depth_foot_mask.jpg', 'Depth mask'),
                ('depth_vis.jpg', 'Depth colorized'),
            ]
        elif ref in ('card', 'both'):
            panels = [
                ('card_detect.jpg', 'Card + foot'),
                ('croppedImg.jpg', 'Crop / paper'),
            ]
        else:
            panels = [
                ('pdraw.jpg', 'Paper contours'),
                ('fdraw.jpg', 'Foot contours'),
                ('croppedImg.jpg', 'Paper crop'),
            ]

        cols = st.columns(len(panels))
        for col, (fname, label) in zip(cols, panels):
            img = load_result_image(fname)
            with col:
                if img is not None:
                    st.image(img, caption=label, use_container_width=True)
                else:
                    st.caption(f'{label}: not available')

        if CHART.is_file():
            with st.expander('Shoe size chart'):
                st.image(str(CHART), use_container_width=True)


if __name__ == '__main__':
    main_ui()
