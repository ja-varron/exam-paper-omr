import cv2 as cv
import numpy as np
import os

SCALE = 0.3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATH: str = os.path.join(BASE_DIR, '..', 'sample', 'S1.jpg')

img = cv.imread(PATH)

if img is None:
    print('Error: Image not found.')
    exit()


resized = cv.resize(
    img,
    (int(img.shape[1] * SCALE), int(img.shape[0] * SCALE)),
    interpolation=cv.INTER_AREA,   # best quality for down-scaling
)

gray = cv.cvtColor(resized, cv.COLOR_BGR2GRAY)
blur = cv.GaussianBlur(gray, (5, 5), 0)

thresh = cv.adaptiveThreshold(
    blur, 255,
    cv.ADAPTIVE_THRESH_GAUSSIAN_C,
    cv.THRESH_BINARY_INV,
    11, 2
)

thresh = cv.morphologyEx(
  thresh,
  cv.MORPH_CLOSE,
  cv.getStructuringElement(cv.MORPH_RECT, (3, 3)),
  iterations=1,
)

contours, _ = cv.findContours(thresh, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

marker_candidates = []

img_h, img_w = resized.shape[:2]
min_dim = min(img_h, img_w)
min_side = int(min_dim * 0.01)
max_side = int(min_dim * 0.08)

for cnt in contours:
    area = cv.contourArea(cnt)
    if area < 250:
      continue

    x, y, w, h = cv.boundingRect(cnt)
    if w < min_side or h < min_side or w > max_side or h > max_side:
      continue

    aspect = w / float(h)
    if not (0.8 <= aspect <= 1.25):
      continue

    rect_area = w * h
    fill_ratio = area / float(rect_area)
    if fill_ratio < 0.6:
      continue

    marker_candidates.append((cnt, (x, y, w, h)))

print(f'Found {len(marker_candidates)} marker candidates.')

def order_points(pts):
  rect = np.zeros((4, 2), dtype="float32")

  s = pts.sum(axis=1)
  rect[0] = pts[np.argmin(s)]
  rect[3] = pts[np.argmax(s)]

  diff = np.diff(pts, axis=1)
  rect[1] = pts[np.argmin(diff)]
  rect[2] = pts[np.argmax(diff)]

  return rect

corner_targets = [
  (0, 0),
  (img_w - 1, 0),
  (0, img_h - 1),
  (img_w - 1, img_h - 1),
]

selected = []
used = set()
for cx, cy in corner_targets:
  best_idx = None
  best_dist = None
  for i, (_, (x, y, w, h)) in enumerate(marker_candidates):
    if i in used:
      continue
    mx = x + w * 0.5
    my = y + h * 0.5
    dist = (mx - cx) ** 2 + (my - cy) ** 2
    if best_dist is None or dist < best_dist:
      best_dist = dist
      best_idx = i
  if best_idx is not None:
    used.add(best_idx)
    selected.append(marker_candidates[best_idx])

debug = resized.copy()
for cnt, (x, y, w, h) in marker_candidates:
  cv.rectangle(debug, (x, y), (x + w, y + h), (0, 165, 255), 1)

if len(selected) == 4:
  points = np.array(
    [[x + w * 0.5, y + h * 0.5] for _, (x, y, w, h) in selected],
    dtype="float32",
  )
  rect = order_points(points)

  xs = [x for _, (x, y, w, h) in selected]
  ys = [y for _, (x, y, w, h) in selected]
  xe = [x + w for _, (x, y, w, h) in selected]
  ye = [y + h for _, (x, y, w, h) in selected]
  pad = int(min_dim * 0.02)

  crop_x1 = max(min(xs) - pad, 0)
  crop_y1 = max(min(ys) - pad, 0)
  crop_x2 = min(max(xe) + pad, img_w - 1)
  crop_y2 = min(max(ye) + pad, img_h - 1)

  scale_x = img.shape[1] / float(img_w)
  scale_y = img.shape[0] / float(img_h)
  orig_x1 = int(crop_x1 * scale_x)
  orig_y1 = int(crop_y1 * scale_y)
  orig_x2 = int(crop_x2 * scale_x)
  orig_y2 = int(crop_y2 * scale_y)

  width = int(max(np.linalg.norm(rect[0] - rect[1]), np.linalg.norm(rect[2] - rect[3])))
  height = int(max(np.linalg.norm(rect[0] - rect[2]), np.linalg.norm(rect[1] - rect[3])))

  dst = np.array(
    [
      [0, 0],
      [width - 1, 0],
      [0, height - 1],
      [width - 1, height - 1],
    ],
    dtype="float32",
  )

  matrix = cv.getPerspectiveTransform(rect, dst)
  warped = cv.warpPerspective(resized, matrix, (width, height))

  for _, (x, y, w, h) in selected:
    cv.rectangle(debug, (x, y), (x + w, y + h), (0, 255, 0), 2)

  cv.imshow('Markers', debug)
#   cv.imshow('Warped', warped)
  if orig_x2 > orig_x1 and orig_y2 > orig_y1:
    cropped = img[orig_y1:orig_y2, orig_x1:orig_x2]
    cv.imshow('Cropped', cropped)
    cv.imwrite(os.path.join(BASE_DIR, '..', 'sample', 'cropped.jpg'), cropped)
else:
  cv.imshow('Markers', debug)

cv.waitKey(0)
cv.destroyAllWindows()
