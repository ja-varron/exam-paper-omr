import cv2 as cv
import numpy as np
import os

# ── Configuration ──────────────────────────────────────────────────────────────

ANSWER_KEY = {0: 1, 1: 4, 2: 0, 3: 3, 4: 1, 5: 2, 6: 0, 7: 3, 8: 4, 9: 1}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATH: str = os.path.join(BASE_DIR, '..', 'sample', 'cropped.jpg')

# Down-scale factor — keeps pixel density reasonable without losing bubble detail
SCALE = 0.3

# ── Gate parameters (calibrated from real data at SCALE=0.3) ──────────────────
# Run with DEBUG=True first on a new paper format to re-calibrate these.

# ── Size ─────────────────────────────────────────────────────────────────────
# At SCALE=0.3 the bounding box of each bubble border ring measures ~12 px wide.
# w=9..20 captures all 500 bubbles while excluding noise (w<9) and column
# borders (w>20).
MIN_BUBBLE_PX = 9
MAX_BUBBLE_PX = 20

# ── Aspect ratio ─────────────────────────────────────────────────────────────
# Square bubbles have w/h ≈ 1.0; allow ±40% for camera tilt / print distortion.
MIN_AR = 0.70
MAX_AR = 1.40

# ── Hierarchy depth (RETR_TREE) ───────────────────────────────────────────────
# With THRESH_BINARY_INV the ink forms closed white rings on a black background.
# Measured depth histogram for sample1.jpg:
#   depth 0 (33)  → outermost image / document borders
#   depth 1 (24)  → column box borders
#   depth 2 (946) → individual bubble rings  ← PRIMARY TARGET
#   depth 3 (119) → child contours inside bubble rings (inner black holes)
# Both depth 2 (ring outer) and depth 3 (ring hole) look like bubble-sized
# squares, so we keep both and rely on size+AR to discriminate from noise.
BUBBLE_DEPTH_MIN = 2
BUBBLE_DEPTH_MAX = 3

# ── Solidity & Extent ────────────────────────────────────────────────────────
# Bubble borders are HOLLOW RINGS in BINARY_INV.  The ring's contour area is
# just the ink thickness (low), while bounding-box area = full bubble size.
# Measured solidity distribution: peaks at 0.2–0.3 (ring) and 0.9–1.0 (solid).
# Setting MIN_SOLIDITY=0.15 passes rings; the size+AR+depth gates do the real
# heavy lifting.  Raising this above 0.5 would drop ~290 legitimate bubbles.
MIN_SOLIDITY = 0.15   # rings score ~0.2-0.3; raise only for solid-fill papers
MIN_EXTENT   = 0.10   # rings score ~0.2; solid fills score ~0.7-0.9

# ── Polygon ──────────────────────────────────────────────────────────────────
# Disabled: thin ring contours decompose into many points and don't reliably
# reduce to 4-6 vertices.  Size + AR + depth + solidity are sufficient.
USE_POLY_GATE    = False
MIN_POLY_PTS     = 4
MAX_POLY_PTS     = 6
POLY_EPS_FACTOR  = 0.04

# ── Debug ────────────────────────────────────────────────────────────────────
# Set True to print the depth histogram and per-gate drop-off counts.
DEBUG = True

# ── Image loading & preprocessing ─────────────────────────────────────────────

img = cv.imread(PATH)
if img is None:
    raise FileNotFoundError(f'Image not found: {PATH}')

print(f"[INFO] Original  – H: {img.shape[0]}, W: {img.shape[1]}")

resized = cv.resize(
    img,
    (int(img.shape[1] * SCALE), int(img.shape[0] * SCALE)),
    interpolation=cv.INTER_AREA,   # best quality for down-scaling
)
print(f"[INFO] Resized   – H: {resized.shape[0]}, W: {resized.shape[1]}")

cv.imshow('Resized', resized)

# ── Stage 1 – De-noise ────────────────────────────────────────────────────────
# Median blur removes salt-and-pepper noise from camera sensors / JPEG artefacts
# while preserving the sharp ink edges of the bubbles.
denoised = cv.medianBlur(resized, 3)

# cv.imshow('Denoised', denoised)

cv.imshow('Denoised', denoised)

# ── Stage 2 – Grayscale + adaptive threshold ──────────────────────────────────
# Adaptive (Gaussian) thresholding normalises for uneven lighting across the
# sheet — much better than global Otsu when one corner is in shadow.
# THRESH_BINARY_INV makes dark bubbles → white regions; paper → black.
# NOTE: use `denoised`, not `resized`, so median blur is applied before threshold.
gray = cv.cvtColor(denoised, cv.COLOR_BGR2GRAY)

thresh = cv.adaptiveThreshold(
    gray, 255,
    cv.ADAPTIVE_THRESH_GAUSSIAN_C,
    cv.THRESH_BINARY_INV,
    blockSize=15,   # neighbourhood size; increase if lighting is very uneven
    C=4,            # constant subtracted from mean; raise to reject light ink
)

# ── Stage 3 – Morphological clean-up ─────────────────────────────────────────
# MORPH_CLOSE: dilation followed by erosion.
# Goal: close tiny GAPS in printed bubble outlines so each bubble forms one
#       continuous white ring in the BINARY_INV image.
# WARNING: a kernel that is too large will MERGE adjacent bubble borders.
#   At SCALE=0.3 bubbles are ~20-30px wide with ~3-5px gaps between them.
#   A (3,3) kernel closes hairline breaks without merging neighbours.
kernel = cv.getStructuringElement(cv.MORPH_RECT, (3, 3))
cleaned = cv.morphologyEx(thresh, cv.MORPH_CLOSE, kernel, iterations=1)

# ── Stage 4 – Contour detection ───────────────────────────────────────────────
# RETR_TREE returns ALL contours with full parent/child relationships.
# hierarchy shape: (1, N, 4)  →  each row = [next, prev, firstChild, parent]
contours, hierarchy = cv.findContours(
    cleaned.copy(),
    cv.RETR_TREE,
    cv.CHAIN_APPROX_SIMPLE,
)
print(f"[INFO] Raw contours found: {len(contours)}")

# ── Stage 4b – Compute hierarchy depth for every contour ─────────────────────
# depth 0 = no parent (outermost), depth 1 = child of outermost, etc.
def compute_depths(hier: np.ndarray) -> list[int]:
    """Walk the parent chain for each contour and count its nesting depth."""
    h  = hier[0]                       # shape (N, 4)
    n  = len(h)
    depths: list[int] = [-1] * n
    for i in range(n):
        depth  = 0
        parent = h[i][3]               # index of parent contour (-1 = none)
        while parent != -1:
            depth += 1
            parent = h[parent][3]
        depths[i] = depth
    return depths

depths = compute_depths(hierarchy)

# Debug: print how many contours exist at each depth level
from collections import Counter
depth_hist = Counter(depths)
print("[INFO] Contour depth histogram:",
      {d: depth_hist[d] for d in sorted(depth_hist)})

# ── Stage 5 – Multi-gate bubble filter ────────────────────────────────────────

def is_bubble(c) -> bool:
    """
    Return True only if contour c passes all quality gates.

    Gate order (cheapest → most expensive):
    1. Hierarchy depth  – eliminates document / column borders & deep noise
    2. Bounding-box size – fast AABB reject
    3. Aspect ratio      – rejects thin / wide shapes
    4. Solidity          – rejects highly concave blobs
    5. Extent            – rejects very sparse blobs
    6. Polygon vertices  – optional; disabled for ring contours

    NOTE: bubbles appear as hollow ink RINGS in THRESH_BINARY_INV images.
    Rings have low solidity (≈0.2) and low extent (≈0.2).  The depth gate
    and tight size band are the primary discriminators at this paper layout.
    """
    # Gate 1 handled externally (depth filter at call site)

    # --- Gate 2: Bounding-box size -------------------------------------------
    x, y, w, h = cv.boundingRect(c)
    if not (MIN_BUBBLE_PX <= w <= MAX_BUBBLE_PX):
        return False
    if not (MIN_BUBBLE_PX <= h <= MAX_BUBBLE_PX):
        return False

    # --- Gate 3: Aspect ratio ------------------------------------------------
    ar = w / float(h)
    if not (MIN_AR <= ar <= MAX_AR):
        return False

    # --- Gate 4: Solidity (contour area / convex-hull area) -----------------
    # Rings score ~0.2-0.3; solid fills score ~0.9-1.0.
    # MIN_SOLIDITY is intentionally low (0.15) to pass ring-shaped borders.
    cnt_area  = cv.contourArea(c)
    if cnt_area == 0:
        return False
    hull_area = cv.contourArea(cv.convexHull(c))
    if hull_area == 0:
        return False
    solidity = cnt_area / hull_area
    if solidity < MIN_SOLIDITY:
        return False

    # --- Gate 5: Extent (contour area / bounding-rect area) ------------------
    # Rings score ~0.2; solid fills score ~0.7-0.9.
    # MIN_EXTENT is intentionally low (0.10) to pass ring-shaped borders.
    bb_area = w * h
    extent  = cnt_area / bb_area
    if extent < MIN_EXTENT:
        return False

    # --- Gate 6 (optional): Polygon approximation ----------------------------
    # Disabled by default: thin ring contours do not reduce reliably to 4-6
    # vertices.  Enable USE_POLY_GATE only for solid-fill bubble papers.
    if USE_POLY_GATE:
        peri   = cv.arcLength(c, True)
        approx = cv.approxPolyDP(c, POLY_EPS_FACTOR * peri, True)
        if not (MIN_POLY_PTS <= len(approx) <= MAX_POLY_PTS):
            return False

    return True


# Apply both the shape gates AND the hierarchy-depth gate.
# The depth gate is the first discriminator:
#   depth < BUBBLE_DEPTH_MIN  →  document borders / column box borders
#   depth > BUBBLE_DEPTH_MAX  →  deep nested noise inside individual rings
if DEBUG:
    after_depth = [c for i, c in enumerate(contours)
                   if BUBBLE_DEPTH_MIN <= depths[i] <= BUBBLE_DEPTH_MAX]
    after_size  = [c for c in after_depth
                   if MIN_BUBBLE_PX <= cv.boundingRect(c)[2] <= MAX_BUBBLE_PX
                   and MIN_BUBBLE_PX <= cv.boundingRect(c)[3] <= MAX_BUBBLE_PX]
    after_ar    = [c for c in after_size
                   if MIN_AR <= cv.boundingRect(c)[2] / float(cv.boundingRect(c)[3]) <= MAX_AR]
    print(f"[DEBUG] After depth gate  : {len(after_depth):5d}")
    print(f"[DEBUG] After size gate   : {len(after_size):5d}")
    print(f"[DEBUG] After AR gate     : {len(after_ar):5d}  ← target: 500")

question_bubbles = [
    c
    for i, c in enumerate(contours)
    if BUBBLE_DEPTH_MIN <= depths[i] <= BUBBLE_DEPTH_MAX and is_bubble(c)
]
print(f"[INFO] Bubble candidates after all gates: {len(question_bubbles)}  (expected 500)")

# ── Stage 5b – Group bubbles by question row ──────────────────────────────────
# Strategy: sort all bubble centres by y, then bucket into rows when the
# y-gap between successive centres exceeds ROW_GAP_PX (≈ half a bubble height).
# Each bucket is one question row; the question number is the bucket index + 1.

ROW_GAP_PX = MAX_BUBBLE_PX // 2   # gap that signals a new row

# Build (cy, cx, contour) tuples sorted top-to-bottom, then left-to-right.
bubble_centres = sorted(
    [(cv.boundingRect(c)[1] + cv.boundingRect(c)[3] // 2,   # cy
      cv.boundingRect(c)[0] + cv.boundingRect(c)[2] // 2,   # cx
      c)
     for c in question_bubbles],
    key=lambda t: (t[0], t[1]),
)

# Walk through sorted centres and split on large y-gaps.
rows: list[list[tuple]] = []
current_row: list[tuple] = []
for entry in bubble_centres:
    if current_row and (entry[0] - current_row[-1][0]) > ROW_GAP_PX:
        rows.append(current_row)
        current_row = []
    current_row.append(entry)
if current_row:
    rows.append(current_row)

# Print the per-question summary.
EXPECTED_CHOICES = 5   # bubbles expected per question row
print()
print(f"{'Question':>10}  {'Boxes Detected':>15}  {'Expected':>9}  {'Status':>8}")
print("-" * 50)
for q_idx, row in enumerate(rows):
    q_num    = q_idx + 1
    detected = len(row)
    status   = "OK" if detected == EXPECTED_CHOICES else "MISMATCH"
    print(f"{q_num:>10}  {detected:>15}  {EXPECTED_CHOICES:>9}  {status:>8}")
print("-" * 50)
print(f"{'TOTAL':>10}  {len(question_bubbles):>15}  {len(rows) * EXPECTED_CHOICES:>9}")
print()

# ── Stage 6 – Visualisation ───────────────────────────────────────────────────

debug_thresh  = cv.cvtColor(cleaned, cv.COLOR_GRAY2BGR)
debug_bubbles = resized.copy()

cv.drawContours(debug_thresh,  question_bubbles, -1, (0, 255,   0), 1)
cv.drawContours(debug_bubbles, question_bubbles, -1, (0, 255,   0), 1)

# Label each bubble with its question number (Q) and choice index (C)
for q_idx, row in enumerate(rows):
    q_num = q_idx + 1
    for c_idx, (cy_val, cx_val, c) in enumerate(row):
        x, y, w, h = cv.boundingRect(c)
        label = f"Q{q_num}"
        cv.putText(debug_bubbles, label, (x, y + h // 2 + 4),
                   cv.FONT_HERSHEY_SIMPLEX, 0.22, (0, 0, 255), 1)

cv.imshow('Adaptive Threshold (cleaned)', debug_thresh)
cv.imshow('Detected Bubbles (green)', debug_bubbles)

cv.waitKey(0)
cv.destroyAllWindows()
