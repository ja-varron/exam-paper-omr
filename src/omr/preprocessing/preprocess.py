from cv2.typing import MatLike
from imutils.perspective import four_point_transform
from matplotlib.pyplot import draw
import numpy as np
import cv2 as cv
# import argparse
import imutils

# Preprocess the image to find the document border and bubble contours
def preprocessing(img: MatLike) -> MatLike:

	if img is None:
		raise FileNotFoundError('Image not found at the specified PATH.', image_path)
	
	gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
	blurred = cv.GaussianBlur(gray, (5, 5), 0)
	edged = cv.Canny(blurred, 75, 200)

	return edged


def thresholding(img: MatLike) -> MatLike:
	thresh = cv.adaptiveThreshold(img, 255, cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY_INV, 21, 5)
	return thresh


if __name__ == '__main__':
	ANSWER_KEY = {0: 1, 1: 4, 2: 0, 3: 3, 4: 1, 5: 2, 6: 0, 7: 3, 8: 4, 9: 1}

	PATH = 'sample/cropped_P2_1-20.jpg'  # Replace with your image PATH

	img = cv.imread(PATH)

	if img is None:
		raise FileNotFoundError('Image not found at the specified PATH.')

	# load the image, convert it to grayscale, blur it slightly, then find edges in the image
	gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
	blurred = cv.GaussianBlur(gray, (5, 5), 0)
	edged = cv.Canny(blurred, 75, 200)

	# Apply bilateral filter to reduce noise while preserving edges (used for thresholding later)
	bilateral = cv.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)

	# find contours in the edge map, then initialize the contour that corresponds to the document
	cnts = cv.findContours(edged.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
	cnts = imutils.grab_contours(cnts)
	docCnt = None
	rectCnts = []  # collect ALL rectangle-shaped contours

	# Image area used to filter out tiny rectangles that can't be the document border
	img_area = img.shape[0] * img.shape[1]
	MIN_DOC_AREA_RATIO = 0.20  # document border must cover at least 20% of the image

	# Ensure that at least one contour was found
	if len(cnts) > 0:
		# Sort the contours according to their size in descending order
		cnts = sorted(cnts, key=cv.contourArea, reverse=True)

		print(f"Number of contours found: {len(cnts)}")

		# Loop over the sorted contours and collect ALL quadrilaterals
		for c in cnts:
			# Approximate the contour
			peri = cv.arcLength(c, True)
			approx = cv.approxPolyDP(c, 0.02 * peri, True)

			# Must be a quadrilateral
			if len(approx) != 4:
				continue

			rectCnts.append(approx)

			# --- Document border candidate filters ---
			area = cv.contourArea(approx)
			(x, y, w, h) = cv.boundingRect(approx)
			ar = w / float(h)  # aspect ratio

			# The document border must:
			#   1. Be large enough relative to the full image
			#   2. Have a plausible aspect ratio (not a tiny square or very thin sliver)
			if area >= MIN_DOC_AREA_RATIO * img_area and 0.3 <= ar <= 3.0:
				if docCnt is None:
					docCnt = approx  # first (largest) qualifying rectangle is the doc border
					print(f"Document border found: area={area:.0f} ({area/img_area*100:.1f}% of image), AR={ar:.2f}")

		print(f"Number of rectangle contours found: {len(rectCnts)}")

	if docCnt is None:
		raise ValueError('Could not find the document contour. Please check the image and adjust the parameters if necessary.')

	# Draw ALL detected rectangle contours on a copy of the original image
	rect_display = img.copy()
	colors = [
		(0, 255, 0),    # green
		(0, 0, 255),    # red
		(255, 0, 0),    # blue
		(0, 255, 255),  # yellow
		(255, 0, 255),  # magenta
		(255, 165, 0),  # orange
	]
	for i, rc in enumerate(rectCnts):
		color = colors[i % len(colors)]
		cv.drawContours(rect_display, [rc], -1, color, 2)

	# Highlight the detected document border in thick white on a separate display
	doc_display = img.copy()
	cv.drawContours(doc_display, [docCnt], -1, (255, 255, 255), 4)
	M = cv.moments(docCnt)
	if M["m00"] != 0:
		cx = int(M["m10"] / M["m00"])
		cy = int(M["m01"] / M["m00"])
		cv.putText(doc_display, "DOC BORDER", (cx - 60, cy),
				cv.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

	# cv.imshow('Edged', edged)
	# cv.imshow('All Rectangle Contours', rect_display)
	# cv.imshow('Document Border', doc_display)
	# cv.waitKey(0)














# For cropped_questions_1-10.jpg


# # load the image, convert it to grayscale, blur it
# # slightly, then find edges in the image
# gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
# blurred = cv.GaussianBlur(gray, (5, 5), 0)
# edged = cv.Canny(blurred, 75, 200)


# # apply bilateral filter to reduce noise while preserving edges (used for thresholding later)
# bilateral = cv.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)


# # find contours in the edge map, then initialize
# # the contour that corresponds to the document
# cnts = cv.findContours(edged.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)  
# cnts = imutils.grab_contours(cnts)
# docCnt = None

# # Ensure that at least one contour was found
# if len(cnts) > 0:
# 	# Sort the countours according to their size in descending order
# 	cnts = sorted(cnts, key=cv.contourArea, reverse=True)

# 	# Loop over the sorted contours
# 	for c in cnts:
# 		# Approximate the contour
# 		peri = cv.arcLength(c, True)
# 		approx = cv.approxPolyDP(c, 0.02 * peri, True)
		
# 		# If our approximated contour has four points, then we can assume that we have found the paper
# 		if len(approx) == 4:
# 			docCnt = approx 
# 			break



# if docCnt is None:
# 	raise ValueError('Could not find the document contour. Please check the image and adjust the parameters if necessary.')

# # apply the four-point transform to obtain a top-down
# # view of the original image
# paper = four_point_transform(img, docCnt.reshape(4, 2))
# warped = four_point_transform(gray, docCnt.reshape(4, 2))


# # apply bilateral filter on the warped grayscale image to reduce noise while preserving edges
# warped_bilateral = cv.bilateralFilter(warped, d=9, sigmaColor=75, sigmaSpace=75)

# # apply adaptive thresholding with BINARY_INV so that filled (dark) bubbles
# # become WHITE regions — required for correct pixel counting in OMR grading
# thresh = cv.adaptiveThreshold(warped_bilateral, 255, cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY_INV, 21, 5)

# # morphological opening: erode then dilate to remove small noise speckles
# kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (3, 3))
# thresh = cv.morphologyEx(thresh, cv.MORPH_OPEN, kernel, iterations=1)


# # find contours in the thresholded image, then initialize
# # the list of contours that correspond to questions
# cnts = cv.findContours(thresh.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
# cnts = imutils.grab_contours(cnts)
# questionCnts = []

# # loop over the contours
# for c in cnts:
# 	# compute the bounding box of the contour, then use the
# 	# bounding box to derive the aspect ratio
# 	(x, y, w, h) = cv.boundingRect(c)
# 	ar = w / float(h)

# 	# in order to label the contour as a question, region
# 	# should be sufficiently wide, sufficiently tall, and
# 	# have an aspect ratio approximately equal to 1
# 	# tighten size filter: bubbles should be at least 15px wide/tall, not too large,
# 	# and have a roughly square aspect ratio (0.7 to 1.4)
# 	if w >= 15 and h >= 15 and w <= 80 and h <= 80 and ar >= 0.7 and ar <= 2.4:
# 		questionCnts.append(c)
		


# NUM_QUESTIONS = 10
# NUM_CHOICES   = 5

# # ---------------------------------------------------------------------------
# # Grid-based contour sorting: snap detected bubbles into a strict 10x5 grid
# # ---------------------------------------------------------------------------
# def sort_contours_into_grid(cnts_list, num_rows, num_cols, row_tol_factor=0.5):
# 	"""
# 	Sort bubble contours into a strict num_rows x num_cols grid.

# 	Strategy:
# 		1. Compute the centroid (cx, cy) of each contour.
# 		2. Sort all centroids top-to-bottom by cy.
# 		3. Estimate row height from the vertical spread, then group
# 				contours whose cy values are within `row_tol_factor * row_height`
# 				of each other into the same row.
# 		4. Within each row group, sort left-to-right by cx.
# 		5. Return a 2-D list grid[row][col] = contour (or None if missing).
# 	"""
# 	if not cnts_list:
# 		return [[None] * num_cols for _ in range(num_rows)]

# 	# Step 1 – compute centroids
# 	centroids = []
# 	for c in cnts_list:
# 			M = cv.moments(c)
# 			if M["m00"] != 0:
# 					cx = int(M["m10"] / M["m00"])
# 					cy = int(M["m01"] / M["m00"])
# 			else:
# 					(x, y, w, h) = cv.boundingRect(c)
# 					cx, cy = x + w // 2, y + h // 2
# 			centroids.append((cx, cy, c))

# 	# Step 2 – sort top-to-bottom
# 	centroids.sort(key=lambda t: t[1])

# 	# Step 3 – estimate row height and cluster into rows
# 	ys = [t[1] for t in centroids]
# 	row_height = (max(ys) - min(ys)) / max(num_rows - 1, 1)
# 	row_tol = max(row_tol_factor * row_height, 5)  # at least 5px tolerance

# 	rows = []
# 	current_row = [centroids[0]]
# 	for item in centroids[1:]:
# 			if abs(item[1] - current_row[-1][1]) <= row_tol:
# 					current_row.append(item)
# 			else:
# 					rows.append(current_row)
# 					current_row = [item]
# 	rows.append(current_row)

# 	# Step 4 – sort each row left-to-right
# 	for row in rows:
# 			row.sort(key=lambda t: t[0])

# 	# Step 5 – build the grid; warn on missing / extra cells
# 	print(f"[GRID] Detected {len(rows)} row groups from {len(cnts_list)} bubbles.")
# 	grid = [[None] * num_cols for _ in range(num_rows)]

# 	for r_idx, row in enumerate(rows):
# 			if r_idx >= num_rows:
# 					print(f"[WARN] Extra row group {r_idx} beyond expected {num_rows} rows – skipped.")
# 					break
# 			if len(row) != num_cols:
# 					print(f"[WARN] Row {r_idx + 1} has {len(row)} bubble(s) instead of {num_cols}.")
# 			for c_idx, (cx, cy, cnt) in enumerate(row):
# 					if c_idx >= num_cols:
# 							print(f"[WARN] Extra bubble in row {r_idx + 1}, col {c_idx + 1} – skipped.")
# 							break
# 					grid[r_idx][c_idx] = cnt

# 	return grid


# print(f"[INFO] Candidate bubble contours found: {len(questionCnts)}")

# grid = sort_contours_into_grid(questionCnts, NUM_QUESTIONS, NUM_CHOICES)

# # ---------------------------------------------------------------------------
# # OMR grading: for each row (question), pick the most-filled bubble
# # ---------------------------------------------------------------------------
# correct = 0
# for q, row_cnts in enumerate(grid):
# 	bubbled = None  # (pixel_count, choice_index)

# 	for j, c in enumerate(row_cnts):
# 		if c is None:
# 			print(f"[WARN] Q{q + 1}, choice {j + 1}: bubble contour missing.")
# 			continue

# 		# Build a filled mask for this bubble
# 		mask = np.zeros(thresh.shape, dtype="uint8")
# 		cv.drawContours(mask, [c], -1, 255, -1)
# 		mask = cv.bitwise_and(thresh, thresh, mask=mask)
# 		total = cv.countNonZero(mask)

# 		if bubbled is None or total > bubbled[0]:
# 			bubbled = (total, j)

# 	if bubbled is None:
# 		print(f"[WARN] Q{q + 1}: no valid bubbles detected – skipping.")
# 		continue

# 	# Check against the answer key
# 	k = ANSWER_KEY[q]
# 	color = (0, 255, 0) if k == bubbled[1] else (0, 0, 255)
# 	if k == bubbled[1]:
# 		correct += 1

# 	# Draw outline: green = correct, red = wrong
# 	chosen_cnt = row_cnts[bubbled[1]]
# 	correct_cnt = row_cnts[k]
# 	if chosen_cnt is not None:
# 		cv.drawContours(paper, [chosen_cnt], -1, color, 3)
# 	if color == (0, 0, 255) and correct_cnt is not None:
# 		cv.drawContours(paper, [correct_cnt], -1, (0, 255, 0), 3)  # show correct in green

# # Score
# score = (correct / NUM_QUESTIONS) * 100
# print(f"[INFO] Score: {correct}/{NUM_QUESTIONS} = {score:.2f}%")
# cv.putText(paper, f"{score:.2f}%", (10, 30), cv.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)


# cv.imshow("Threshold", thresh)
# cv.imshow("Graded Exam", paper)
# cv.waitKey(0)
