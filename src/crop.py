import cv2 as cv

# For cropped_questions_1-10.jpg
# PATH = 'sample/PaperWithoutLight.jpg'  # Replace with your image PATH

# For cropped_1-20.jpg
PATH = 'sample/SAMPLE1.jpg'  # Replace with your image PATH

img = cv.imread(PATH)

if img is None:
    raise FileNotFoundError('Image not found at the specified PATH.')

# The user wants to crop the section with questions 1-10
# I will define a region of interest (ROI) for that section.
# These coordinates are estimates and might need adjustment.
# Based on the image, the area for questions 1-10 is on the left side.
# The coordinates are in (y, x) format, so it's (start_row, end_row, start_col, end_col)
# Let's try to estimate the coordinates from the image.
# The top of question 1 is around 1/3 of the way down.
# The bottom of question 10 is around 1/2 of the way down.
# The left of the question numbers is around 1/3 of the way from the left.
# The right of the choices is around 2/3 of the way from the left.

height, width = img.shape[:2]

# Estimated coordinates for the crop
# y_start = int(height * 0.3)
# y_end = int(height * 0.5)
# x_start = int(width * 0.3)
# x_end = int(width * 0.5)

# Let's try more specific pixel values based on an image editor
# These values are for the original image size

# For cropped_questions_1-10.jpg
# y_start = 910
# y_end = 1320
# x_start = 810
# x_end = 1110

# For cropped_1-20.jpg
y_start = 900
y_end = 1400
x_start = 2100
x_end = 2470


cropped_img = img[y_start:y_end, x_start:x_end]

cv.imshow('Cropped Image', cropped_img)
cv.waitKey(0)
cv.destroyAllWindows()

# Save the cropped image
cv.imwrite('sample/cropped_P2_1-20.jpg', cropped_img)
