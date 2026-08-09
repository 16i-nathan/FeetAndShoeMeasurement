from sklearn.cluster import KMeans
import random as rng
import cv2
import imutils
import argparse
from skimage.io import imread
import numpy as np
import matplotlib.pyplot as plt



def preprocess(img):

    img = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)

    img = cv2.GaussianBlur(img, (9, 9), 0)
    img = img/255

    return img

def plotImage(img):
    
    plt.imshow(img)
    #plt.title('Clustered Image')
    plt.show()

def cropOrig(bRect, oimg):
    # x (Horizontal), y (Vertical Downwards) are start coordinates
    # img.shape[0] = height of image
    # img.shape[1] = width of image

    x,y,w,h = bRect

    print(x,y,w,h)
    pcropedImg = oimg[y:y+h,x:x+w]

    x1, y1, w1, h1 = 0, 0, pcropedImg.shape[1], pcropedImg.shape[0]

    y2 = int(h1/10)

    x2 = int(w1/10)

    crop1 = pcropedImg[y1+y2:h1-y2,x1+x2:w1-x2]

    #cv2_imshow(crop1)

    ix, iy, iw, ih = x+x2, y+y2, crop1.shape[1], crop1.shape[0]

    croppedImg = oimg[iy:iy+ih,ix:ix+iw]

    return croppedImg, pcropedImg



def overlayImage(croppedImg, pcropedImg):


    x1, y1, w1, h1 = 0, 0, pcropedImg.shape[1], pcropedImg.shape[0]

    y2 = int(h1/10)

    x2 = int(w1/10)

    new_image = np.zeros((pcropedImg.shape[0], pcropedImg.shape[1], 3), np.uint8)
    new_image[:, 0:pcropedImg.shape[1]] = (255, 0, 0) # (B, G, R)

    new_image[ y1+y2:y1+y2+croppedImg.shape[0], x1+x2:x1+x2+croppedImg.shape[1]] = croppedImg

    return new_image



def kMeans_cluster(img):

    # For clustering the image using k-means, we first need to convert it into a 2-dimensional array
    # (H*W, N) N is channel = 3
    image_2D = img.reshape(img.shape[0]*img.shape[1], img.shape[2])

    # tweak the cluster size and see what happens to the Output
    kmeans = KMeans(n_clusters=2, random_state=0).fit(image_2D)
    clustOut = kmeans.cluster_centers_[kmeans.labels_]

    # Reshape back the image from 2D to 3D image
    clustered_3D = clustOut.reshape(img.shape[0], img.shape[1], img.shape[2])

    clusteredImg = np.uint8(clustered_3D*255)

    return clusteredImg


def edgeDetection(clusteredImage):
  #gray = cv2.cvtColor(hsvImage, cv2.COLOR_BGR2GRAY)
  edged1 = cv2.Canny(clusteredImage, 0, 255)
  edged = cv2.dilate(edged1, None, iterations=1)
  edged = cv2.erode(edged, None, iterations=1)
  return edged

def getBoundingBox(img):

    contours, _ = cv2.findContours(img, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    #print(len(contours))
    contours = sorted(contours, key=lambda x: cv2.contourArea(x), reverse=True)
    
    

    contours_poly = [None]*len(contours)
    boundRect = [None]*len(contours)

    for i, c in enumerate(contours):
        contours_poly[i] = cv2.approxPolyDP(c, 3, True)
        boundRect[i] = cv2.boundingRect(contours_poly[i])

    
    return boundRect, contours, contours_poly, img


def drawCnt(bRect, contours, cntPoly, img):

    drawing = np.zeros((img.shape[0], img.shape[1], 3), dtype=np.uint8)   


    paperbb = bRect

    for i in range(len(contours)):
      color = (rng.randint(0,256), rng.randint(0,256), rng.randint(0,256))
      cv2.drawContours(drawing, cntPoly, i, color)
      #cv2.rectangle(drawing, (int(boundRect[i][0]), int(boundRect[i][1])), \
              #(int(boundRect[i][0]+boundRect[i][2]), int(boundRect[i][1]+boundRect[i][3])), color, 2)
    cv2.rectangle(drawing, (int(paperbb[0]), int(paperbb[1])), \
              (int(paperbb[0]+paperbb[2]), int(paperbb[1]+paperbb[3])), color, 2)
    
    return drawing


def calcFeetSize(pcropedImg, fboundRect):
  x1, y1, w1, h1 = 0, 0, pcropedImg.shape[1], pcropedImg.shape[0]

  y2 = int(h1/10)

  x2 = int(w1/10)

  fh = y2 + fboundRect[2][3]
  fw = x2 + fboundRect[2][2]
  ph = pcropedImg.shape[0]
  pw = pcropedImg.shape[1]

  opw = 210
  oph = 297

  ofs = 0.0

  if fw>fh:
    ofs = (opw/pw)*fw
  else :
    ofs = (oph/ph)*fh



  return ofs


# ISO/IEC 7810 ID-1 (credit/debit card)
CARD_LENGTH_MM = 85.60
CARD_WIDTH_MM = 53.98
CARD_ASPECT = CARD_LENGTH_MM / CARD_WIDTH_MM  # ~1.586


def _rect_aspect(w, h):
    if min(w, h) <= 0:
        return 0.0
    return max(w, h) / min(w, h)


def _contour_rectangularity(contour):
    area = cv2.contourArea(contour)
    if area <= 0:
        return 0.0
    x, y, w, h = cv2.boundingRect(contour)
    box_area = float(w * h)
    return area / box_area if box_area else 0.0


def find_credit_card(edged_or_gray, min_area_ratio=0.002, aspect_tol=0.08):
    """
    Find a credit-card-sized rectangle by aspect ratio (ID-1 ~1.586).
    Returns (bbox_xywh, min_area_rect, score) or raises ValueError.

    aspect_tol is tight on purpose so A4 (~1.414) is not mistaken for a card.
    """
    if edged_or_gray.ndim == 3:
        gray = cv2.cvtColor(edged_or_gray, cv2.COLOR_RGB2GRAY)
    else:
        gray = edged_or_gray

    edged = cv2.Canny(gray, 50, 150)
    edged = cv2.dilate(edged, None, iterations=2)
    edged = cv2.erode(edged, None, iterations=1)

    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    img_area = gray.shape[0] * gray.shape[1]
    min_area = img_area * min_area_ratio
    # Cards are small vs a full frame / A4 sheet
    max_area = img_area * 0.20

    best = None
    best_score = -1.0

    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue

        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)
        rect = cv2.minAreaRect(c)
        (cx, cy), (rw, rh), angle = rect
        if rw <= 1 or rh <= 1:
            continue

        aspect = _rect_aspect(rw, rh)
        aspect_err = abs(aspect - CARD_ASPECT) / CARD_ASPECT
        if aspect_err > aspect_tol:
            continue

        rectangularity = _contour_rectangularity(c)
        if rectangularity < 0.55:
            continue

        # Prefer 4-vertex quads, low aspect error, decent size
        quad_bonus = 0.35 if len(approx) == 4 else 0.0
        score = (1.0 - aspect_err) + rectangularity + quad_bonus + min(area / img_area, 0.2)

        if score > best_score:
            best_score = score
            box = cv2.boundingRect(c)
            best = (box, rect, score)

    if best is None:
        raise ValueError(
            "Could not find a credit card. Place an ID-1 card (standard credit/debit) "
            "fully visible, flat, and high-contrast against the background."
        )
    return best


def mm_per_pixel_from_card(min_area_rect):
    """Scale from card minAreaRect: long side = 85.60 mm, short = 53.98 mm."""
    (_, _), (rw, rh), _ = min_area_rect
    long_px, short_px = (rw, rh) if rw >= rh else (rh, rw)
    # Average both axes for a slightly stabler scale
    scale_long = CARD_LENGTH_MM / long_px
    scale_short = CARD_WIDTH_MM / short_px
    return 0.5 * (scale_long + scale_short)


def _overlaps_box(box, other, frac=0.25):
    x, y, w, h = box
    ex, ey, ew, eh = other
    ix1, iy1 = max(x, ex), max(y, ey)
    ix2, iy2 = min(x + w, ex + ew), min(y + h, ey + eh)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return False
    return inter > frac * min(w * h, ew * eh)


def _mask_card_region(edged, card_box, pad=15):
    out = edged.copy()
    x, y, w, h = card_box
    out[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad] = 0
    return out


def _foot_edge_maps(rgb_img, card_box):
    """Build complementary edge maps; dark feet on dark floors need more than k-means."""
    maps = []

    # 1) Original pipeline: HSV blur → 2-means → Canny
    pre = preprocess(rgb_img)
    clustered = kMeans_cluster(pre)
    maps.append(_mask_card_region(edgeDetection(clustered), card_box))

    # 2) Multi-scale Canny on CLAHE gray (helps low-contrast skin vs wood)
    gray = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    blur = cv2.GaussianBlur(clahe, (5, 5), 0)
    e = cv2.bitwise_or(
        cv2.Canny(blur, 20, 60),
        cv2.bitwise_or(cv2.Canny(blur, 40, 100), cv2.Canny(blur, 60, 140)),
    )
    e = cv2.dilate(e, None, iterations=2)
    e = cv2.morphologyEx(
        e, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
        iterations=2,
    )
    e[gray > 210] = 0  # drop flash glare / card shine
    maps.append(_mask_card_region(e, card_box))

    return maps


def _score_foot_candidates(edge_maps, card_box, card_rect, img_shape):
    """Rank elongated blobs whose long side is ~2–4× the credit card."""
    img_area = img_shape[0] * img_shape[1]
    (_, _), (cw, ch), _ = card_rect
    card_long = max(cw, ch)
    ranked = []

    for edged in edge_maps:
        contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < 0.002 * img_area or area > 0.45 * img_area:
                continue
            box = cv2.boundingRect(c)
            if _overlaps_box(box, card_box):
                continue
            x, y, w, h = box
            aspect = _rect_aspect(w, h)
            if aspect < 1.25:
                continue
            long_px = max(w, h)
            ratio = long_px / card_long
            # Adult foot ≈ 22–32 cm → about 2.5–3.8× card length (85.6 mm)
            if ratio < 1.8 or ratio > 4.5:
                continue
            length_score = float(np.exp(-0.5 * ((ratio - 3.0) / 0.9) ** 2))
            score = length_score * aspect * np.sqrt(area)
            ranked.append((score, box, c))

    ranked.sort(key=lambda t: t[0], reverse=True)
    return ranked


def find_foot_bbox(rgb_img, card_box, card_rect):
    """
    Find the foot next to a detected credit card.
    Uses k-means edges + CLAHE multi-scale Canny, scored vs card size.
    Returns (bbox_xywh, contour).
    """
    edge_maps = _foot_edge_maps(rgb_img, card_box)
    ranked = _score_foot_candidates(edge_maps, card_box, card_rect, rgb_img.shape)

    if not ranked:
        raise ValueError(
            "Could not find a foot contour. Use a top-down photo with the full foot "
            "visible, card beside it, and enough contrast against the floor."
        )
    _, box, contour = ranked[0]
    return box, contour


def calc_feet_size_from_card(foot_bbox, min_area_rect, foot_contour=None):
    """Foot length in mm using credit-card scale."""
    if foot_contour is not None and len(foot_contour) >= 5:
        (_cx, _cy), (rw, rh), _angle = cv2.minAreaRect(foot_contour)
        foot_long_px = max(rw, rh)
    else:
        _, _, fw, fh = foot_bbox
        foot_long_px = max(fw, fh)
    return foot_long_px * mm_per_pixel_from_card(min_area_rect)


def draw_box(img, box, color=(0, 255, 0), label=None):
    """Draw an axis-aligned box on a BGR/RGB/uint8 image copy."""
    out = img.copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    x, y, w, h = [int(v) for v in box]
    cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
    if label:
        cv2.putText(out, label, (x, max(0, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return out