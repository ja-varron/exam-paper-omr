# Exam Paper OMR

## 📝 Project Description

Exam Paper OMR is an Optical Mark Recognition (OMR) system designed to automatically detect and grade answer sheets, such as those used in standardized tests. It processes scanned images of answer sheets, identifies filled-in bubbles, and extracts responses for efficient and accurate result computation.

## 🛠️ Tech Stack

- **Python 3.12+**
- **OpenCV** (image processing and computer vision)
- **NumPy** (numerical operations)
- **imutils** (image processing utilities)
- **Pillow** (image file handling)
- **matplotlib** (visualization and debugging)

## 📋 Pre-requisites

Before you begin, ensure you have:
  - Python 3.12 and above
  - Git installed on your machine

## ✅ Installation Guide

1. **Clone the repository**
```bash
git clone https://github.com/ja-varron/exam-paper-omr.git
cd exam-paper-omr
```

2. **Create and activate a virtual environment**
```bash
source bin/activate # Linux/Mac
bin\activate # Windows
```

3. **Install required packages**
```bash
pip install -r backend/requirements.txt
```

The main packages installed are:
  - opencv-python
  - numpy
  - imutils
  - Pillow
  - matplotlib

#### Note: Refer to feature/documentation branch for latest documentation update

## 🚀 Usage Instructions (DISREGARD FOR NOW)

1. **Prepare your answer sheet images**
  - Place scanned or photographed answer sheets (e.g., in JPG or PNG format) into the `sample/` directory.

2. **Run the OMR script**
  - Make sure your virtual environment is activated.
  - Execute your OMR processing script. For example:
    ```bash
    python3 backend/omr_main.py --input sample/sample.jpg
    ```
  - Replace `omr_main.py` and `sample.jpg` with your actual script and image filenames.

3. **View Results**
  - The script will output the detected answers, scores, or any relevant results to the console or a results file, depending on your implementation.

### Example Command

```bash
python backend/omr_main.py --input backend/sample.jpg --output results.csv
```

- `--input`: Path to the answer sheet image.
- `--output`: (Optional) Path to save the extracted results.

> **Note:** If your script or arguments differ, update the instructions accordingly.

---

Let me know if you want this inserted directly into your README or need a sample OMR script template!

