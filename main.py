import argparse
import os

import cv2
import numpy as np
from PIL import Image, ImageOps

from depth_measure import (
    colorize_depth,
    load_depth,
    measure_foot_cm_from_depth,
    resolve_depth_path,
)
from utils import (
    calcFeetSize,
    calc_feet_size_from_card,
    cropOrig,
    drawCnt,
    draw_box,
    edgeDetection,
    find_credit_card,
    find_foot_bbox,
    getBoundingBox,
    kMeans_cluster,
    overlayImage,
    preprocess,
)

# Cap long edge so phone photos behave like the sample (~1600px)
MAX_IMAGE_SIDE = 1600


def load_image(path, max_side=MAX_IMAGE_SIDE):
    """
    Load image with EXIF orientation applied, optionally downscaled.
    Returns (rgb_uint8, scale) where scale is the resize factor applied to width/height.
    """
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert('RGB')
        w, h = img.size
        long_side = max(w, h)
        scale = 1.0
        if long_side > max_side:
            scale = max_side / long_side
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        return np.asarray(img), scale


def ensure_output_dir():
    if not os.path.exists('output'):
        os.makedirs('output')


def measure_with_paper(oimg):
    """Original A4-paper reference pipeline. Returns feet size in cm."""
    preprocessedOimg = preprocess(oimg)
    cv2.imwrite('output/preprocessedOimg.jpg', preprocessedOimg)

    clusteredImg = kMeans_cluster(preprocessedOimg)
    cv2.imwrite('output/clusteredImg.jpg', clusteredImg)

    edgedImg = edgeDetection(clusteredImg)
    cv2.imwrite('output/edgedImg.jpg', edgedImg)

    boundRect, contours, contours_poly, img = getBoundingBox(edgedImg)
    if len(boundRect) < 2:
        raise ValueError("Could not find paper contour. Keep a full A4 sheet visible.")

    pdraw = drawCnt(boundRect[1], contours, contours_poly, img)
    cv2.imwrite('output/pdraw.jpg', pdraw)

    croppedImg, pcropedImg = cropOrig(boundRect[1], clusteredImg)
    cv2.imwrite('output/croppedImg.jpg', croppedImg)

    newImg = overlayImage(croppedImg, pcropedImg)
    cv2.imwrite('output/newImg.jpg', newImg)

    fedged = edgeDetection(newImg)
    fboundRect, fcnt, fcntpoly, fimg = getBoundingBox(fedged)
    if len(fboundRect) < 3:
        raise ValueError("Could not find foot contour on the paper.")

    fdraw = drawCnt(fboundRect[2], fcnt, fcntpoly, fimg)
    cv2.imwrite('output/fdraw.jpg', fdraw)

    return calcFeetSize(pcropedImg, fboundRect) / 10.0


def measure_with_card(oimg, search_img=None):
    """
    Credit-card reference pipeline (ISO/IEC 7810 ID-1).
    Optional search_img limits card/foot search (e.g. paper crop).
    Returns feet size in cm.
    """
    region = search_img if search_img is not None else oimg
    if region.dtype != np.uint8:
        region_u8 = np.clip(region, 0, 255).astype(np.uint8)
    else:
        region_u8 = region

    if region_u8.ndim == 3:
        gray = cv2.cvtColor(region_u8, cv2.COLOR_RGB2GRAY)
    else:
        gray = region_u8

    card_box, card_rect, score = find_credit_card(gray)
    print(f"credit card detected (score={score:.2f}): {card_box}")

    rgb = region_u8 if region_u8.ndim == 3 else cv2.cvtColor(region_u8, cv2.COLOR_GRAY2RGB)
    foot_box, foot_contour = find_foot_bbox(rgb, card_box, card_rect)
    print(f"foot detected: {foot_box}")

    vis = rgb.copy()
    vis = draw_box(vis, card_box, color=(255, 200, 0), label='card')
    vis = draw_box(vis, foot_box, color=(0, 255, 0), label='foot')
    cv2.drawContours(vis, [foot_contour], -1, (0, 180, 255), 2)
    cv2.imwrite('output/card_detect.jpg', cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))

    return calc_feet_size_from_card(foot_box, card_rect, foot_contour) / 10.0


def measure_with_both(oimg):
    """
    Use A4 paper to localize the foot, credit card for absolute scale.
    Card may sit on the paper or next to the foot in the full frame.
    """
    preprocessedOimg = preprocess(oimg)
    clusteredImg = kMeans_cluster(preprocessedOimg)
    edgedImg = edgeDetection(clusteredImg)
    boundRect, _, _, _ = getBoundingBox(edgedImg)
    if len(boundRect) < 2:
        raise ValueError("Could not find paper contour for --ref both.")

    _, pcropedImg = cropOrig(boundRect[1], oimg)
    cv2.imwrite('output/croppedImg.jpg', cv2.cvtColor(pcropedImg, cv2.COLOR_RGB2BGR))

    try:
        return measure_with_card(oimg, search_img=pcropedImg)
    except ValueError:
        print("card not found on paper crop; searching full image...")
        return measure_with_card(oimg, search_img=oimg)


def measure_with_depth(oimg, depth_path, depth_scale=None, fx=None, fy=None,
                       cx=None, cy=None, hfov_deg=60.0):
    """LiDAR / depth-map pipeline. Returns feet size in cm."""
    depth_m = load_depth(depth_path, depth_scale=depth_scale)
    # Match depth to the (possibly downscaled) RGB without a second resize pass issues
    cm, foot_box, foot_mask, foot_pts = measure_foot_cm_from_depth(
        oimg, depth_m, fx=fx, fy=fy, cx=cx, cy=cy, hfov_deg=hfov_deg
    )
    print(f"depth points on foot: {len(foot_pts)}")
    print(f"foot detected: {foot_box}")

    depth_vis = colorize_depth(cv2.resize(depth_m, (oimg.shape[1], oimg.shape[0]),
                                          interpolation=cv2.INTER_NEAREST))
    cv2.imwrite('output/depth_vis.jpg', depth_vis)
    cv2.imwrite('output/depth_foot_mask.jpg', foot_mask)

    vis = oimg.copy()
    vis = draw_box(vis, foot_box, color=(0, 255, 0), label='foot')
    overlay = vis.copy()
    overlay[foot_mask > 0] = (0, 180, 255)
    vis = cv2.addWeighted(vis, 0.65, overlay, 0.35, 0)
    cv2.imwrite('output/depth_detect.jpg', cv2.cvtColor(vis, cv2.COLOR_RGB2BGR))
    return cm


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            'Measure foot length using A4 paper, a credit card, and/or a '
            'depth/LiDAR map.'
        )
    )
    p.add_argument(
        'image',
        nargs='?',
        default='data/barefeet1.jpeg',
        help='Path to RGB image (default: data/barefeet1.jpeg)',
    )
    p.add_argument(
        '--ref',
        choices=('paper', 'card', 'both', 'depth'),
        default='paper',
        help=(
            'Scale reference: '
            'paper = A4 (210x297mm), '
            'card = ISO credit card (85.60x53.98mm), '
            'both = paper ROI + card scale, '
            'depth = LiDAR/ToF/RGB-D metric depth'
        ),
    )
    p.add_argument(
        '--depth',
        default=None,
        help='Depth map path (.npy meters, or 16-bit .png/.tif). '
             'If omitted with --ref depth, looks for <image>_depth.npy/png.',
    )
    p.add_argument(
        '--depth-scale',
        type=float,
        default=None,
        help='Multiply raw depth by this to get meters '
             '(default: 1.0 for .npy, 0.001 for 16-bit images).',
    )
    p.add_argument('--fx', type=float, default=None, help='Camera fx (pixels)')
    p.add_argument('--fy', type=float, default=None, help='Camera fy (pixels)')
    p.add_argument('--cx', type=float, default=None, help='Camera cx (pixels)')
    p.add_argument('--cy', type=float, default=None, help='Camera cy (pixels)')
    p.add_argument(
        '--hfov',
        type=float,
        default=60.0,
        help='Horizontal FOV degrees used when fx/fy omitted (default: 60)',
    )
    return p.parse_args()


def main():
    args = parse_args()
    ensure_output_dir()
    oimg, img_scale = load_image(args.image)

    try:
        if args.ref == 'paper':
            cm = measure_with_paper(oimg)
        elif args.ref == 'card':
            cm = measure_with_card(oimg)
        elif args.ref == 'both':
            cm = measure_with_both(oimg)
        else:
            depth_path = resolve_depth_path(args.image, args.depth)
            print(f"using depth map: {depth_path}")
            fx = args.fx * img_scale if args.fx is not None else None
            fy = args.fy * img_scale if args.fy is not None else None
            cx = args.cx * img_scale if args.cx is not None else None
            cy = args.cy * img_scale if args.cy is not None else None
            cm = measure_with_depth(
                oimg,
                depth_path,
                depth_scale=args.depth_scale,
                fx=fx,
                fy=fy,
                cx=cx,
                cy=cy,
                hfov_deg=args.hfov,
            )
    except ValueError as e:
        raise SystemExit(f"Error: {e}") from e

    print(f"feet size (cm): {cm:.2f}  [ref={args.ref}]")


if __name__ == '__main__':
    main()
