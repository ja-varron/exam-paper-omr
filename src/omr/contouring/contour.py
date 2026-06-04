from cv2.typing import MatLike
import cv2 as cv
import numpy as np
import imutils


def contour(img: MatLike):

  img_area = img.shape[0] * img.shape[1]
  MIN_DOC_AREA_RATIO = 0.20

  cnts = cv.findContours(img.copy(), cv.RETR_TREE, cv.CHAIN_APPROX_SIMPLE)
  cnts = imutils.grab_contours(cnts)

  documentContour = None

  print(f'Number of contours found: {len(cnts)}')
  if len(cnts) > 0:
    # Already sorted largest-first; use raw contour area for the size check
    cnts = sorted(cnts, key=cv.contourArea, reverse=True)

    for c in cnts:
      # --- Fast reject: skip contours that are clearly too small ---
      raw_area = cv.contourArea(c)
      if raw_area < MIN_DOC_AREA_RATIO * img_area:
        break  # list is sorted, so nothing larger remains

      peri = cv.arcLength(c, True)

      # Try progressively looser epsilons until we get a quadrilateral
      approx = None
      for eps_factor in (0.02, 0.03, 0.05, 0.08):
        candidate = cv.approxPolyDP(c, eps_factor * peri, True)
        if len(candidate) == 4:
          approx = candidate
          break

      # Fallback: force a quad via convex hull + tighter approx
      if approx is None:
        hull = cv.convexHull(c)
        hull_peri = cv.arcLength(hull, True)
        for eps_factor in (0.02, 0.05, 0.10):
          candidate = cv.approxPolyDP(hull, eps_factor * hull_peri, True)
          if len(candidate) == 4:
            approx = candidate
            break

      if approx is None:
        continue  # couldn't reduce this contour to a quad — skip it

      (x, y, w, h) = cv.boundingRect(approx)
      ar = w / float(h)

      # The document border must have a plausible aspect ratio
      # (not a tiny square or very thin sliver)
      if 0.3 <= ar <= 3.0:
        documentContour = approx
        print(f'Document border found: raw_area={raw_area:.0f} ({raw_area/img_area*100:.1f}% of image), AR={ar:.2f}')
        break
      

  if documentContour is None:
    raise ValueError('Could not find the document contour. Please check the image and adjust the parameters if necessary.')

  return documentContour
    



  