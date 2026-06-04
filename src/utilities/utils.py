"""
OMR Utility Functions
=====================
Helper functions for the Optical Mark Recognition (OMR) pipeline used to
process PRC (Professional Regulation Commission) examination answer sheets.

Module Contents
---------------
order_points          – Order four corner points for perspective transform.
four_point_transform  – Apply a homographic perspective warp to a document.
find_sheet_contour    – Detect the answer-sheet boundary as a quadrilateral.
find_answer_boxes     – Locate the ten bordered answer boxes on the sheet.
detect_filled_bubbles – Grid-based detection of shaded answer bubbles.
draw_answer_overlay   – Annotate a sheet image with the detected answers.

Educational References
----------------------
- Rosebrock, A. (2016). "Bubble Sheet Multiple Choice Scanner and Test Grader
  Using OMR, Python and OpenCV." PyImageSearch.
  https://www.pyimagesearch.com/2016/10/03/bubble-sheet-multiple-choice-scanner-and-test-grader-using-omr-python-and-opencv/
- OpenCV Documentation – Contour Features:
  https://docs.opencv.org/4.x/dd/d49/tutorial_py_contour_features.html
- OpenCV Documentation – Perspective Transform:
  https://docs.opencv.org/4.x/da/d6e/tutorial_py_geometric_transformations.html
- Gonzalez, R. C. & Woods, R. E. (2018). Digital Image Processing, 4th ed.
  Pearson. (Chapters 10–11: Image Segmentation & Representation)
"""

import cv2 as cv
import numpy as np
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Perspective Correction Utilities
# ---------------------------------------------------------------------------

def order_points(pts: np.ndarray) -> np.ndarray:
    """
    Sort four (x, y) corner points into a consistent clockwise order:
    [top-left, top-right, bottom-right, bottom-left].

    Background
    ----------
    ``cv2.getPerspectiveTransform`` requires source and destination points in
    the same relative order.  An arbitrary quadrilateral contour may return
    points in any order, so we normalise them first using two properties:

    * **Top-left** has the smallest (x + y) sum.
    * **Bottom-right** has the largest (x + y) sum.
    * **Top-right** has the smallest (y − x) difference.
    * **Bottom-left** has the largest (y − x) difference.

    Parameters
    ----------
    pts : np.ndarray, shape (4, 2)
        Unordered corner coordinates.

    Returns
    -------
    np.ndarray, shape (4, 2), dtype float32
        Ordered [TL, TR, BR, BL].
    """
    rect = np.zeros((4, 2), dtype='float32')

    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # top-left:     smallest x+y
    rect[2] = pts[np.argmax(s)]   # bottom-right: largest  x+y

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right:    smallest y-x
    rect[3] = pts[np.argmax(diff)]  # bottom-left:  largest  y-x

    return rect


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    Correct perspective distortion using a four-point planar homography.

    Background
    ----------
    A **homography** (perspective transform) is a 3×3 matrix **H** that maps
    points in one plane to another.  Given four source points and their
    desired destination positions (the corners of an upright rectangle), we
    solve for **H** and apply it via ``cv2.warpPerspective`` to produce a
    bird's-eye ("top-down") view of the document.

    This removes the trapezoidal distortion introduced when a camera is not
    perfectly parallel to the scanned sheet.

    Parameters
    ----------
    image : np.ndarray
        Source BGR or grayscale image.
    pts : np.ndarray, shape (4, 2)
        Four corner points of the region of interest (any order).

    Returns
    -------
    np.ndarray
        Warped, perspective-corrected view of the bounded region.
    """
    rect = order_points(pts)
    tl, tr, br, bl = rect

    # Output width = longest of the two horizontal edges
    width = int(max(
        np.linalg.norm(br - bl),
        np.linalg.norm(tr - tl),
    ))

    # Output height = longest of the two vertical edges
    height = int(max(
        np.linalg.norm(tr - br),
        np.linalg.norm(tl - bl),
    ))

    # Destination corners form an axis-aligned rectangle
    dst = np.array([
        [0,         0],
        [width - 1, 0],
        [width - 1, height - 1],
        [0,         height - 1],
    ], dtype='float32')

    M = cv.getPerspectiveTransform(rect, dst)
    return cv.warpPerspective(image, M, (width, height))


# ---------------------------------------------------------------------------
# 2. Sheet Boundary Detection
# ---------------------------------------------------------------------------

def find_sheet_contour(gray: np.ndarray) -> Optional[np.ndarray]:
    """
    Detect the answer-sheet boundary as the largest four-sided contour.

    Algorithm
    ---------
    1. **Gaussian blur** reduces high-frequency noise so edge detection is
       less likely to fire on texture or print grain.
    2. **Canny edge detector** finds pixel-level transitions that correspond
       to the sheet's physical border.
    3. **Dilation** closes small gaps in the edge map so the outer contour
       forms a fully closed polygon.
    4. **Contour approximation** (Ramer-Douglas-Peucker, RDP) — We try a
       range of epsilon values (``0.02`` to ``0.10`` × perimeter) on the
       largest contour.  Photographed paper borders are often slightly curved
       or crumpled, so a strict ``epsilon=0.02`` may leave 5–8 vertices.
       Increasing epsilon aggressively simplifies the outline to 4 vertices.
    5. **Convex hull fallback** — If no epsilon value yields exactly 4
       vertices, the 4 extremal points of the convex hull are used as
       the sheet corners (top-left, top-right, bottom-right, bottom-left).

    Parameters
    ----------
    gray : np.ndarray
        Single-channel grayscale image.

    Returns
    -------
    np.ndarray or None
        Shape (4, 1, 2) contour of the sheet corners, or None if not found.
    """
    blurred = cv.GaussianBlur(gray, (5, 5), 0)
    edged   = cv.Canny(blurred, 30, 200)

    # Close small gaps so the sheet outline forms a sealed contour
    kernel = np.ones((3, 3), np.uint8)
    edged  = cv.dilate(edged, kernel, iterations=2)

    contours, _ = cv.findContours(edged, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv.contourArea, reverse=True)

    # ── Strategy 1: RDP approximation with escalating epsilon ─────────────
    # Photographed paper may have slightly rounded/crumpled edges; a strict
    # epsilon=0.02 can leave 5-8 vertices.  We try up to epsilon=0.10 on the
    # top candidates.
    epsilon_fracs = [0.02, 0.03, 0.05, 0.08, 0.10]
    for c in contours[:5]:
        peri = cv.arcLength(c, True)
        for eps in epsilon_fracs:
            approx = cv.approxPolyDP(c, eps * peri, True)
            if len(approx) == 4:
                return approx

    # ── Strategy 2: Convex hull extremal-point extraction ─────────────────
    # Take the 4 extreme corners of the convex hull of the largest contour.
    if contours:
        hull = cv.convexHull(contours[0]).reshape(-1, 2)
        s    = hull.sum(axis=1)
        diff = np.diff(hull, axis=1).flatten()
        corners = np.array([
            hull[np.argmin(s)],    # top-left
            hull[np.argmin(diff)], # top-right
            hull[np.argmax(s)],    # bottom-right
            hull[np.argmax(diff)], # bottom-left
        ], dtype='float32')
        return corners.reshape(4, 1, 2).astype(np.int32)

    return None


# ---------------------------------------------------------------------------
# 2b. Marker-Based Alignment (Edge Squares)
# ---------------------------------------------------------------------------

def find_square_markers(
    gray: np.ndarray,
    min_area: int = 250,
    min_dim_ratio: float = 0.01,
    max_dim_ratio: float = 0.08,
    aspect_range: tuple = (0.8, 1.25),
    fill_ratio_min: float = 0.6,
) -> list:
    """
    Detect filled square markers in a grayscale image.

    The markers are expected to be small, roughly square, and dark-filled.
    Returns a list of bounding boxes (x, y, w, h) in image coordinates.
    """
    blur = cv.GaussianBlur(gray, (5, 5), 0)
    thresh = cv.adaptiveThreshold(
        blur, 255,
        cv.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv.THRESH_BINARY_INV,
        11, 2,
    )
    thresh = cv.morphologyEx(
        thresh,
        cv.MORPH_CLOSE,
        cv.getStructuringElement(cv.MORPH_RECT, (3, 3)),
        iterations=1,
    )

    contours, _ = cv.findContours(thresh, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

    img_h, img_w = gray.shape[:2]
    min_dim = min(img_h, img_w)
    min_side = int(min_dim * min_dim_ratio)
    max_side = int(min_dim * max_dim_ratio)

    markers = []
    for cnt in contours:
        area = cv.contourArea(cnt)
        if area < min_area:
            continue

        x, y, w, h = cv.boundingRect(cnt)
        if w < min_side or h < min_side or w > max_side or h > max_side:
            continue

        aspect = w / float(h)
        if not (aspect_range[0] <= aspect <= aspect_range[1]):
            continue

        rect_area = w * h
        fill_ratio = area / float(rect_area) if rect_area > 0 else 0.0
        if fill_ratio < fill_ratio_min:
            continue

        markers.append((x, y, w, h))

    return markers


def select_corner_markers(
    markers: list,
    image_shape: tuple,
) -> list:
    """
    Pick the closest marker to each image corner.

    Returns up to four markers ordered by TL, TR, BL, BR target proximity.
    """
    img_h, img_w = image_shape[:2]
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
        for i, (x, y, w, h) in enumerate(markers):
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
            selected.append(markers[best_idx])

    return selected


def align_with_markers(
    img_bgr: np.ndarray,
    gray: np.ndarray,
) -> tuple[Optional[tuple], int]:
    """
    Attempt perspective correction using four square edge markers.

    Returns (warped_bgr, warped_gray) and the number of marker candidates.
    If fewer than four corner markers are found, returns (None, count).
    """
    markers = find_square_markers(gray)
    selected = select_corner_markers(markers, gray.shape)

    if len(selected) != 4:
        return None, len(markers)

    points = np.array(
        [[x + w * 0.5, y + h * 0.5] for (x, y, w, h) in selected],
        dtype='float32',
    )

    warped_bgr = four_point_transform(img_bgr, points)
    warped_gray = four_point_transform(gray, points)
    return (warped_bgr, warped_gray), len(markers)


# ---------------------------------------------------------------------------
# 3. Answer-Box Localisation
# ---------------------------------------------------------------------------

def find_answer_boxes(
    warped_gray:        np.ndarray,
    num_cols:           int   = 5,
    header_ratio:       float = 0.40,
    min_area_ratio:     float = 0.05,
    max_area_ratio:     float = 0.15,
) -> list:
    """
    Locate the five bordered answer columns in the perspective-corrected sheet.

    PRC Answer Sheet Layout
    -----------------------
    The answer section spans the lower ~60 % of the sheet and contains
    **five bordered columns**, each holding **20 questions** stacked vertically:

          Col 0      Col 1      Col 2      Col 3      Col 4
        ┌─────────┬─────────┬─────────┬─────────┬─────────┐
        │  Q 1-20 │ Q 21-40 │ Q 41-60 │ Q 61-80 │ Q81-100 │
        └─────────┴─────────┴─────────┴─────────┴─────────┘

    Each column contains 20 rows (one per question) × 5 cells (A–E).
    The first ~25 % of each column's width contains the question-number labels
    and a narrow left border; the rightmost ~10 % is the right border.

    Detection Strategy
    ------------------
    1. Crop the lower portion of the sheet (below ``header_ratio``).
    2. Apply adaptive thresholding and morphological closing to solidify borders.
    3. Extract external contours and keep those whose area and aspect ratio
       are consistent with a tall answer column (taller than wide, area ≈ 6–14 %
       of the sheet).
    4. Sort retained candidates by x-position.
    5. **Extrapolation** – On this sheet the leftmost 1–2 columns are hidden
       because their borders merge with the outer-section boundary contour.
       If ≥ 3 boxes are found with consistent x-spacing, missing columns are
       reconstructed from the average spacing and box dimensions.
    6. Fall back to a uniform grid if fewer than 3 candidates are found.

    Parameters
    ----------
    warped_gray     : Grayscale perspective-corrected sheet.
    num_cols        : Number of answer columns expected (5 for a 100-Q sheet).
    header_ratio    : Fraction of sheet height above the answer area.
    min_area_ratio  : Minimum column area as a fraction of total sheet area.
    max_area_ratio  : Maximum column area as a fraction of total sheet area.

    Returns
    -------
    list of (x, y, w, h) tuples, length == num_cols
        Bounding rectangles sorted left → right in absolute coordinates
        (relative to ``warped_gray``).
    """
    sh, sw = warped_gray.shape
    answer_y = int(sh * header_ratio)
    roi = warped_gray[answer_y:, :]

    # Binarise: highlights printed borders and bubble outlines
    thresh = cv.adaptiveThreshold(
        roi, 255,
        cv.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv.THRESH_BINARY_INV,
        blockSize=15, C=4,
    )
    kernel  = cv.getStructuringElement(cv.MORPH_RECT, (3, 3))
    morphed = cv.morphologyEx(thresh, cv.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv.findContours(morphed, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

    sheet_area = sh * sw
    min_area   = sheet_area * min_area_ratio
    max_area   = sheet_area * max_area_ratio

    candidates = []
    for c in contours:
        area = cv.contourArea(c)
        if not (min_area < area < max_area):
            continue
        x, y, bw, bh = cv.boundingRect(c)
        aspect = bh / bw if bw > 0 else 0
        # Answer columns are noticeably taller than wide
        if aspect > 1.5 and bw > sw * 0.08:
            candidates.append((x, y + answer_y, bw, bh))

    candidates.sort(key=lambda r: r[0])  # left → right

    # ── Extrapolation from consistently-spaced detected boxes ──────────────
    # On this sheet the left 1-2 boxes often merge into the outer border
    # contour and are not independently detectable.  We reconstruct them from
    # the average spacing of the boxes that ARE found.
    if len(candidates) >= 3:
        x_positions = [c[0] for c in candidates]
        spacings = [x_positions[i + 1] - x_positions[i]
                    for i in range(len(x_positions) - 1)]
        avg_spacing = float(np.mean(spacings))

        if np.std(spacings) < avg_spacing * 0.30:  # Consistent enough
            avg_w = int(np.mean([c[2] for c in candidates]))
            avg_h = int(np.mean([c[3] for c in candidates]))
            avg_y = int(np.mean([c[1] for c in candidates]))

            # Extend leftward until we have num_cols boxes
            while len(candidates) < num_cols:
                leftmost_x = candidates[0][0]
                new_x = leftmost_x - int(avg_spacing)
                candidates.insert(0, (max(0, new_x), avg_y, avg_w, avg_h))

            return candidates[:num_cols]

    # ── Fallback: uniform vertical strips ─────────────────────────────────
    print('[WARN] Auto-detection failed; using uniform fallback grid.')
    cell_w = sw // num_cols
    return [
        (i * cell_w, answer_y, cell_w, sh - answer_y)
        for i in range(num_cols)
    ]


# ---------------------------------------------------------------------------
# 4. Bubble (Mark) Detection
# ---------------------------------------------------------------------------

def detect_filled_bubbles(
    box_gray:          np.ndarray,
    n_rows:            int   = 20,
    n_cols:            int   = 5,
    q_num_ratio:       float = 0.25,
    right_margin_ratio:float = 0.09,
    header_row_ratio:  float = 0.07,
    cell_pad:          float = 0.10,
    min_fill_ratio:    float = 0.09,
    min_fill_gap:      float = 0.03,
    block_size:        int   = 25,
    thresh_c:          int   = 6,
) -> list:
    """
    Identify the selected answer bubble in each question row of one answer column.

    Algorithm – Fill-Ratio Method
    ------------------------------
    1. **Crop** the label areas from the box:

       * *Left*  – ``q_num_ratio`` of width: printed question-number column.
       * *Right* – ``right_margin_ratio`` of width: right-side box border.
         Without this strip the border's high dark-pixel count would bias
         every row toward answer E (rightmost column).
       * *Top*   – ``header_row_ratio`` of height: A–E column label header.

     2. Apply **adaptive threshold** (inverted) so that dark pencil marks
         become white foreground pixels even with uneven lighting.

       Otsu's method automatically selects the optimal threshold *t* by
       maximising the inter-class variance between foreground and background
       pixel intensities, making it robust to moderate lighting variation.

    3. Divide the binary bubble grid into an ``n_rows × n_cols`` cell grid.
    4. For each cell, compute the **fill ratio**:

           fill_ratio = (number of foreground pixels) / (total cell pixels)

    5. In each row, the cell with the highest fill ratio above
       ``min_fill_ratio`` is classified as the student's choice.  If no cell
       exceeds the threshold the question is marked as unanswered (``None``).

    Parameters
    ----------
    box_gray           : Grayscale crop of one answer column (full box incl. labels).
    n_rows             : Number of question rows per column (20 for PRC sheet).
    n_cols             : Number of answer choices (5: A B C D E).
    q_num_ratio        : Fraction of box width for the question-number column.
    right_margin_ratio : Fraction of box width to discard from the right edge
                         (excludes the printed right border from analysis).
    header_row_ratio   : Fraction of box height for the A–E label header row.
    cell_pad           : Fractional inset within each bubble cell (avoids
                         counting grid-line edges as foreground marks).
    min_fill_ratio     : Minimum fill ratio to classify a bubble as shaded.
    min_fill_gap       : Minimum difference between best and second-best
                         fill ratios to accept a selection.
    block_size         : Adaptive threshold neighborhood size (odd number).
    thresh_c           : Adaptive threshold constant subtracted from mean.

    Returns
    -------
    list of (int | None), length n_rows
        0-based answer index (0=A, 1=B, 2=C, 3=D, 4=E) or None (unanswered).
    """
    bh, bw = box_gray.shape

    # Define the pure-bubble sub-region (strip labels and borders)
    x_left  = int(bw * q_num_ratio)
    x_right = bw - int(bw * right_margin_ratio)
    y_top   = int(bh * header_row_ratio)
    bubbles = box_gray[y_top:, x_left:x_right]

    # Adaptive threshold: robust to shadows and non-uniform lighting
    blur = cv.GaussianBlur(bubbles, (3, 3), 0)
    thresh = cv.adaptiveThreshold(
        blur,
        255,
        cv.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv.THRESH_BINARY_INV,
        block_size,
        thresh_c,
    )

    kernel = cv.getStructuringElement(cv.MORPH_RECT, (3, 3))
    thresh = cv.morphologyEx(thresh, cv.MORPH_OPEN, kernel, iterations=1)

    ah, aw = thresh.shape
    cell_h = ah / n_rows
    cell_w = aw / n_cols

    answers = []
    for row in range(n_rows):
        fill_ratios = []
        for col in range(n_cols):
            # Inner cell coordinates (padded to avoid border contamination)
            y1 = int(row * cell_h       + cell_h * cell_pad)
            y2 = int((row + 1) * cell_h - cell_h * cell_pad)
            x1 = int(col * cell_w       + cell_w * cell_pad)
            x2 = int((col + 1) * cell_w - cell_w * cell_pad)

            cell  = thresh[y1:y2, x1:x2]
            ratio = np.sum(cell > 0) / cell.size if cell.size > 0 else 0.0
            fill_ratios.append(ratio)

        best_col = int(np.argmax(fill_ratios))
        best_val = fill_ratios[best_col]
        second_val = sorted(fill_ratios, reverse=True)[1] if len(fill_ratios) > 1 else 0.0

        if best_val >= min_fill_ratio and (best_val - second_val) >= min_fill_gap:
            answers.append(best_col)
        else:
            answers.append(None)

    return answers


# ---------------------------------------------------------------------------
# 5. Result Compilation
# ---------------------------------------------------------------------------

def compile_results(
    all_answers:        list,
    num_cols:           int = 5,
    questions_per_col:  int = 20,
    choices:            str = 'ABCDE',
) -> dict:
    """
    Map per-column answer index lists to a flat question-number → letter dict.

    The ``all_answers`` list must be sorted left → right, matching the order
    produced by ``find_answer_boxes``.

    Question-number Formula
    -----------------------
    Column ``col_idx`` (0-based) holds questions:

        q_start = col_idx × questions_per_col + 1

    Example for 5 columns × 20 questions each:

        col_idx=0 → Q1-20
        col_idx=1 → Q21-40
        col_idx=2 → Q41-60
        col_idx=3 → Q61-80
        col_idx=4 → Q81-100

    Parameters
    ----------
    all_answers      : List[List[int | None]] – one inner list per column.
    num_cols         : Number of answer columns (5).
    questions_per_col: Questions per column (20).
    choices          : Answer-choice label string ('ABCDE').

    Returns
    -------
    dict[int, str]
        Maps question number (1-based) to the detected answer letter,
        or '?' for unanswered questions.
    """
    results = {}
    for col_idx, col_answers in enumerate(all_answers):
        q_start = col_idx * questions_per_col + 1
        for row, ans in enumerate(col_answers):
            results[q_start + row] = choices[ans] if ans is not None else '?'
    return results


# ---------------------------------------------------------------------------
# 6. Visualisation
# ---------------------------------------------------------------------------

def draw_answer_overlay(
    sheet_bgr:          np.ndarray,
    box_rois:           list,
    all_answers:        list,
    choices:            str   = 'ABCDE',
    q_num_ratio:        float = 0.25,
    right_margin_ratio: float = 0.09,
    header_row_ratio:   float = 0.07,
) -> np.ndarray:
    """
    Render detected answers onto the sheet image for visual verification.

    Visual Encoding
    ---------------
    * **Green circle** – A bubble was detected as filled at this position.
    * **Magenta '?'**  – No bubble exceeded the fill-ratio threshold; the
                         question is unanswered or ambiguous.

    The overlay positions mirror the bubble grid used by
    ``detect_filled_bubbles`` (same margin ratios applied).

    Parameters
    ----------
    sheet_bgr           : BGR perspective-corrected sheet image.
    box_rois            : List of (x, y, w, h) from ``find_answer_boxes``.
    all_answers         : Parallel list of answer-index lists.
    choices             : Answer-choice label string ('ABCDE').
    q_num_ratio         : Fraction of box width for question-number labels.
    right_margin_ratio  : Fraction of box width excluded at right (border).
    header_row_ratio    : Fraction of box height for A–E header row.

    Returns
    -------
    np.ndarray
        Annotated copy of ``sheet_bgr``.
    """
    overlay = sheet_bgr.copy()
    n_cols  = len(choices)

    for (bx, by, bw, bh), answers in zip(box_rois, all_answers):
        # Mirror the same crop used in detect_filled_bubbles
        x_left   = bx + int(bw * q_num_ratio)
        x_right  = bx + bw - int(bw * right_margin_ratio)
        y_origin = by + int(bh * header_row_ratio)
        aw = x_right - x_left
        ah = bh - int(bh * header_row_ratio)

        cell_h = ah / len(answers)
        cell_w = aw / n_cols

        for row, ans in enumerate(answers):
            cy = int(y_origin + (row + 0.5) * cell_h)

            if ans is not None:
                cx     = int(x_left + (ans + 0.5) * cell_w)
                radius = max(4, int(min(cell_h, cell_w) * 0.28))
                cv.circle(overlay, (cx, cy), radius, (0, 220, 0), 2)
                cv.putText(
                    overlay, choices[ans],
                    (cx - 5, cy + 4),
                    cv.FONT_HERSHEY_SIMPLEX, 0.32, (0, 180, 0), 1,
                )
            else:
                cx = int(x_left + aw // 2)
                cv.putText(
                    overlay, '?',
                    (cx - 4, cy + 4),
                    cv.FONT_HERSHEY_SIMPLEX, 0.35, (255, 0, 255), 1,
                )

    return overlay
