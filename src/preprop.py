"""
preprocess.py – OMR Pipeline for PRC Examination Answer Sheets
===============================================================
Entry point for automatically processing a photographed PRC answer sheet and
extracting each student's selected answer (A–E) for all 100 questions.

Usage
-----
    python backend/preprocess.py

Output
------
* Console table showing Q1→Q100 with their detected answer letters.
* OpenCV window displaying the perspective-corrected sheet with green circles
  marking each detected filled bubble.
* OpenCV debug window showing Canny edge detection output.

Answer Sheet Layout (PRC Format)
---------------------------------
The sheet contains **100 questions** arranged in **five bordered columns**.
Each column holds **20 questions** (stacked vertically), each with five
bubble choices (A, B, C, D, E):

          Col 0      Col 1      Col 2      Col 3      Col 4
        ┌──────────┬──────────┬──────────┬──────────┬──────────┐
        │  Q 1-20  │ Q 21-40  │ Q 41-60  │ Q 61-80  │ Q 81-100 │
        └──────────┴──────────┴──────────┴──────────┴──────────┘

Pipeline Overview
-----------------
┌─────────────────────────────────────────────────────────────────┐
│  Stage 1 – Image Acquisition & Preprocessing                    │
│    Load → Median-blur (salt-and-pepper removal) → Resize        │
├─────────────────────────────────────────────────────────────────┤
│  Stage 2 – Document Boundary Detection                          │
│    Grayscale → Canny edges → Largest quadrilateral contour      │
│    → Four-point homographic perspective warp                    │
├─────────────────────────────────────────────────────────────────┤
│  Stage 3 – Answer-Box Localisation                              │
│    Adaptive threshold → Morphological close → Contour filter    │
│    → 10 bounding boxes in reading order (row-major)             │
├─────────────────────────────────────────────────────────────────┤
│  Stage 4 – Bubble Detection (per box)                           │
│    Crop label column + header row → Otsu inverse threshold      │
│    → 10×5 cell grid → Fill-ratio per cell → Argmax per row      │
├─────────────────────────────────────────────────────────────────┤
│  Stage 5 – Result Compilation & Visualisation                   │
│    Map box answers → Q-number dict → Print table → Annotate img │
└─────────────────────────────────────────────────────────────────┘

Educational References
----------------------
- Rosebrock, A. (2016). "Bubble Sheet Multiple Choice Scanner and Test Grader
  Using OMR, Python and OpenCV." PyImageSearch.
- OpenCV – Image Thresholding:
  https://docs.opencv.org/4.x/d7/d4d/tutorial_py_thresholding.html
- Gonzalez, R. C. & Woods, R. E. (2018). Digital Image Processing, 4th ed.
"""

import cv2 as cv
import numpy as np

from utilities.utils import (
    find_sheet_contour,
    four_point_transform,
    find_answer_boxes,
    detect_filled_bubbles,
    compile_results,
    draw_answer_overlay,
    align_with_markers,
)

# ── Configuration ─────────────────────────────────────────────────────────────

PATH               = 'sample/PaperWithoutLight.jpg'  # Path to answer-sheet image
SCALE              = 0.4       # Down-scale factor (0.4 = 40% of original size)

# Answer-sheet grid dimensions
NUM_COLS           = 5         # Bordered answer columns on the sheet
QUESTIONS_PER_COL  = 20        # Questions per column (stacked vertically)
TOTAL_QUESTIONS    = NUM_COLS * QUESTIONS_PER_COL   # 100 questions

CHOICES            = 'ABCDE'   # Five answer choices per question

# Visualisation
WINDOW_ANSWERS   = 'OMR Result – Green circles mark detected answers'
WINDOW_DEBUG_EDGE = 'Debug – Canny Edge Map'
WINDOW_DEBUG_BOXES = 'Debug – Detected Answer Boxes'

# ── Pipeline Functions ─────────────────────────────────────────────────────────


def load_and_preprocess(path: str, scale: float):
    """
    Load the answer-sheet image, reduce noise, and scale to working size.

    Preprocessing Notes
    -------------------
    * **Median blur** – Replaces each pixel with the median of its 5×5
      neighbourhood.  It is preferred over Gaussian blur here because it
      removes salt-and-pepper noise (random dark/white pixels from camera
      sensor noise or JPEG artefacts) without blurring printed edges.
    * **Resize** – Reduces computation time.  At SCALE=0.4 a 3000×4000 px
      photo becomes 1200×1600 px – still high enough resolution for bubble
      detection.

    Parameters
    ----------
    path  : Filesystem path to the answer-sheet image.
    scale : Resize factor (< 1 shrinks; > 1 magnifies).

    Returns
    -------
    tuple(bgr, gray)
        Preprocessed colour image and its grayscale counterpart.
    """
    img = cv.imread(path)
    if img is None:
        raise FileNotFoundError(f'[ERROR] Image not found: {path}')

    return preprocess_bgr(img, scale)


def preprocess_bgr(img: np.ndarray, scale: float):
    """
    Prepare a BGR image for OMR: denoise, resize, and produce grayscale.
    """
    if img is None:
        raise ValueError('[ERROR] Input image is empty.')

    # Median blur: 5×5 kernel removes camera noise while preserving ink edges
    img = cv.medianBlur(img, 5)

    h, w = img.shape[:2]
    if scale != 1.0:
        img = cv.resize(
            img,
            (int(w * scale), int(h * scale)),
            interpolation=cv.INTER_AREA,
        )

    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
    return img, gray


def warp_sheet(img_bgr: np.ndarray, gray: np.ndarray):
    """
    Detect the sheet boundary and apply a perspective correction warp.

    Sanity Check
    ------------
    Strong overhead lighting (as in ``PaperWithLight.jpg``) can wash out the
    paper's outer edges, causing the contour detector to latch onto a thin
    interior stripe rather than the full sheet boundary.  The resulting warp
    would be a near-zero-height sliver, which ``cv2.imshow`` renders as a
    black box.

    After computing the prospective output dimensions, we validate that:

    * ``height ≥ 0.25 × width``  – prevents a degenerate flat strip.
    * ``(width × height) ≥ 0.15 × image_area`` – prevents a tiny crop that
      discards most of the sheet.

    If either check fails, the warp is skipped and the (already pre-processed)
    image is used as-is.

    Parameters
    ----------
    img_bgr : Colour image after preprocessing.
    gray    : Grayscale counterpart.

    Returns
    -------
    tuple(warped_bgr, warped_gray)
    """
    from utilities.utils import order_points as _order_pts

    sheet_cnt = find_sheet_contour(gray)
    img_area  = gray.shape[0] * gray.shape[1]

    if sheet_cnt is not None:
        pts  = sheet_cnt.reshape(4, 2).astype('float32')
        rect = _order_pts(pts)
        tl, tr, br, bl = rect
        est_w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        est_h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))

        # Reject degenerate warps (sliver or tiny crop)
        valid = (
            est_h >= 0.25 * est_w          # not a flat strip
            and (est_w * est_h) >= 0.15 * img_area  # covers enough of the sheet
        )

        if valid:
            warped_bgr  = four_point_transform(img_bgr, pts)
            warped_gray = four_point_transform(gray,    pts)
            print('[INFO] Perspective correction applied successfully.')
            return warped_bgr, warped_gray
        else:
            print(f'[WARN] Detected quad produced a degenerate warp '
                  f'({est_w}×{est_h}); skipping perspective correction.')

    else:
        print('[WARN] Sheet boundary not found; proceeding without warp.')

    return img_bgr.copy(), gray.copy()


def align_sheet(img_bgr: np.ndarray, gray: np.ndarray, prefer_markers: bool = True):
    """
    Align the sheet using markers when available; fall back to contour warp.
    """
    warnings = []

    if prefer_markers:
        aligned, marker_count = align_with_markers(img_bgr, gray)
        if aligned is not None:
            return aligned[0], aligned[1], warnings
        warnings.append(f'markers_not_found:{marker_count}')

    warped_bgr, warped_gray = warp_sheet(img_bgr, gray)
    return warped_bgr, warped_gray, warnings


def print_results_table(results: dict, cols_per_row: int = 5) -> None:
    """
    Print a neatly formatted table of question → detected answer pairs.

    Parameters
    ----------
    results     : {question_number: answer_letter} mapping.
    cols_per_row: Number of Q→A pairs to print per line.
    """
    separator = '─' * 62
    print(f'\n{separator}')
    print('  OMR RESULTS  –  Detected Answers (PRC Answer Sheet)')
    print(separator)

    items = sorted(results.items())
    for i in range(0, len(items), cols_per_row):
        row = items[i:i + cols_per_row]
        print('   '.join(f'Q{q:>3}: {a}' for q, a in row))

    answered   = sum(1 for a in results.values() if a != '?')
    unanswered = TOTAL_QUESTIONS - answered
    print(separator)
    print(f'  Answered: {answered} / {TOTAL_QUESTIONS}   '
          f'Unanswered / ambiguous: {unanswered}')
    print(separator + '\n')


def debug_show_boxes(warped_bgr: np.ndarray, box_rois: list) -> np.ndarray:
    """
    Draw bounding rectangles around each detected answer column (debug view).

    Parameters
    ----------
    warped_bgr : The corrected sheet in colour.
    box_rois   : List of (x, y, w, h) tuples.

    Returns
    -------
    np.ndarray  Annotated image.
    """
    debug = warped_bgr.copy()
    for col_idx, (bx, by, bw, bh) in enumerate(box_rois):
        cv.rectangle(debug, (bx, by), (bx + bw, by + bh), (255, 100, 0), 2)
        q_start = col_idx * QUESTIONS_PER_COL + 1
        label   = f'Q{q_start}-{q_start + QUESTIONS_PER_COL - 1}'
        cv.putText(debug, label, (bx + 4, by + 18),
                   cv.FONT_HERSHEY_SIMPLEX, 0.45, (0, 60, 255), 1)
    return debug


def run_pipeline(img_bgr: np.ndarray, scale: float = SCALE, prefer_markers: bool = True):
    """
    Run the full OMR pipeline and return intermediate outputs for debugging.
    """
    img_bgr, gray = preprocess_bgr(img_bgr, scale)
    warped_bgr, warped_gray, warnings = align_sheet(img_bgr, gray, prefer_markers)

    box_rois = find_answer_boxes(
        warped_gray,
        num_cols=NUM_COLS,
    )

    all_answers = []
    for bx, by, bw, bh in box_rois:
        box_crop = warped_gray[by: by + bh, bx: bx + bw]
        answers = detect_filled_bubbles(box_crop, n_rows=QUESTIONS_PER_COL)
        all_answers.append(answers)

    results = compile_results(
        all_answers,
        num_cols=NUM_COLS,
        questions_per_col=QUESTIONS_PER_COL,
        choices=CHOICES,
    )

    return results, warped_bgr, warped_gray, box_rois, all_answers, warnings


def process_image_bgr(img_bgr: np.ndarray, scale: float = SCALE, prefer_markers: bool = True):
    """
    Process a BGR image and return only the per-question answers.
    """
    results, _, _, _, _, warnings = run_pipeline(img_bgr, scale, prefer_markers)
    return results, warnings


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':

    # ── Stage 1: Image Acquisition & Preprocessing ───────────────────────────
    print('\n[Stage 1] Loading and preprocessing image…')
    img = cv.imread(PATH)
    if img is None:
        raise FileNotFoundError(f'[ERROR] Image not found: {PATH}')

    results, warped_bgr, warped_gray, box_rois, all_answers, warnings = run_pipeline(
        img,
        scale=SCALE,
        prefer_markers=True,
    )
    print(f'          Image size: {warped_bgr.shape[1]} × {warped_bgr.shape[0]} px')

    if warnings:
        print(f'[WARN] Alignment warnings: {", ".join(warnings)}')

    # ── Stage 3: Answer-Box Localisation ─────────────────────────────────────
    print('[Stage 3] Locating answer columns…')
    print(f'          Found {len(box_rois)} answer column(s).')

    # ── Stage 4: Bubble Detection ─────────────────────────────────────────────
    print('[Stage 4] Detecting filled bubbles in each answer column…')

    # ── Stage 5: Compile & Display Results ────────────────────────────────────
    print('[Stage 5] Compiling results…')
    print_results_table(results)

    # ── Annotated image ───────────────────────────────────────────────────────
    annotated = draw_answer_overlay(
        warped_bgr,
        box_rois,
        all_answers,
        choices=CHOICES,
    )
    debug_boxes = debug_show_boxes(warped_bgr, box_rois)

    # Canny edge map used during Stage 2 (shown for educational transparency)
    edge_debug = cv.Canny(cv.GaussianBlur(warped_gray, (5, 5), 0), 30, 200)

    # ── Display ───────────────────────────────────────────────────────────────
    cv.imshow(WINDOW_DEBUG_EDGE, cv.cvtColor(edge_debug, cv.COLOR_GRAY2BGR))
    cv.imshow(WINDOW_DEBUG_BOXES, debug_boxes)
    cv.imshow(WINDOW_ANSWERS, annotated)

    print('Press any key in an OpenCV window to close.')
    cv.waitKey(0)
    cv.destroyAllWindows()


