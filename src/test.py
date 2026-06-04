import cv2 as cv
import numpy as np
import os

from utilities.utils import (
    compile_results,
    detect_filled_bubbles,
    draw_answer_overlay,
    find_answer_boxes,
)

SCALE = 0.3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PATH: str = os.path.join(BASE_DIR, '..', 'sample', 'cropped.jpg')

img = cv.imread(PATH)

if img is None:
    print('Error: Image not found.')
    exit()


gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)

box_rois = find_answer_boxes(gray)
all_answers = []
for (x, y, w, h) in box_rois:
    box_gray = gray[y:y + h, x:x + w]
    answers = detect_filled_bubbles(
        box_gray,
        min_fill_ratio=0.10,
        min_fill_gap=0.03,
        block_size=25,
        thresh_c=6,
        cell_pad=0.10,
    )
    all_answers.append(answers)

results = compile_results(all_answers)
for q_num in sorted(results.keys()):
    print(f"Q{q_num:03d}: {results[q_num]}")

overlay = draw_answer_overlay(img, box_rois, all_answers)
display = cv.resize(
    overlay,
    (int(overlay.shape[1] * SCALE), int(overlay.shape[0] * SCALE)),
    interpolation=cv.INTER_AREA,
)

cv.imshow('Detected Answers', display)
cv.waitKey(0)
cv.destroyAllWindows()