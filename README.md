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

## Backend API (Flask Scaffold)

The repository now includes a Flask backend scaffold in `backend/app` for frontend integration.

### Run API Server

Run commands from the `exam-paper-omr` folder.

For a small project, start with one of these and keep defaults:

```bash
# Development server
python backend/run.py

# Production-like WSGI server (recommended for deployment)
python backend/serve.py
```

Default API base URL:

```text
http://127.0.0.1:5000/api
```

### Environment Variables

For a small deployment, you usually only need these:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `ALLOWED_ORIGINS`
- `PORT` (optional; when using `backend/serve.py`)

The rest are optional and can stay at defaults.

All available variables:

- `FLASK_DEBUG` (default: `0`)
- `FLASK_SECRET_KEY` (default: `dev-secret-key`)
- `MAX_CONTENT_LENGTH` (default: `10485760`)
- `ALLOWED_ORIGINS` (default: `http://localhost:5173,http://127.0.0.1:5173`)
- `DATABASE_URL` (default: `sqlite:///exam_omr.db`)
- `SUPABASE_URL` (required for Supabase-backed endpoints)
- `SUPABASE_SERVICE_ROLE_KEY` (required for Supabase-backed endpoints)
- `AUTH_REQUIRED` (default: `0`; set to `1` to require bearer token for protected routes)
- `SMTP_HOST` (optional, required for real email sending)
- `SMTP_PORT` (default: `587`)
- `SMTP_USERNAME` (optional)
- `SMTP_PASSWORD` (optional)
- `SMTP_SENDER` (default: `no-reply@tuon.local`)
- `SMTP_USE_TLS` (default: `1`)
- `OMR_TEMPLATE_PATH` (optional absolute or relative file path to blank reference sheet)
- `WAITRESS_THREADS` (default: `4`, used by `backend/serve.py`)
- `WAITRESS_CONNECTION_LIMIT` (default: `200`, used by `backend/serve.py`)
- `WAITRESS_CHANNEL_TIMEOUT` (default: `60`, used by `backend/serve.py`)
- `PROFILE_CACHE_TTL_SECONDS` (default: `300`, instructor name cache TTL)
- `PROFILE_CACHE_MAX_ENTRIES` (default: `1000`, instructor name cache capacity)
- `ASSIGNED_EXAMS_CACHE_TTL_SECONDS` (default: `20`, assigned exams response cache TTL)
- `ASSIGNED_EXAMS_CACHE_MAX_ENTRIES` (default: `1500`, assigned exams response cache capacity)

### Small-Scale Recommendation (Around 500 Users)

Use the defaults above first. They are intentionally conservative and should be enough for a small deployment.

If you run `backend/serve.py`, you can keep configuration simple and only set `PORT` (optional):

```bash
# Linux/macOS
PORT=5000 python backend/serve.py

# Windows PowerShell
$env:PORT='5000'; python backend/serve.py
```

If traffic grows later, increase `WAITRESS_THREADS` and cache capacities gradually based on observed latency.

### Prototype Endpoints

- `GET /api/health`
- `POST /api/exams/<exam_id>/scan`
  - multipart/form-data:
    - `sheet` (required image file)
    - `studentId` (optional)
    - `studentName` (optional)
    - `answerKey` (optional JSON array or comma-separated answers)
- `GET /api/exams/<exam_id>/results`
- `GET /api/exams/<exam_id>/analytics`
- `POST /api/results/<result_id>/feedback`
- `POST /api/exams/<exam_id>/release`
  - JSON body supports `recipientEmails: string[]`
- `GET /api/students/<student_id>/assigned-exams`
- `GET /api/assignments/students/<student_id>/assigned-exams`
  - Optional query params:
    - `limit` (1-200)
    - `offset` (>= 0)
    - `fresh` (`1|true|yes`) to bypass the short-lived response cache

### Optional: Load Testing

Run the built-in assigned-exams load test script:

```bash
python backend/scripts/load_test_assigned_exams.py \
  --student-id <student-uuid> \
  --base-url http://127.0.0.1:5000 \
  --concurrency 8 \
  --requests-per-worker 10 \
  --timeout-seconds 30
```

### Important Note

Current OMR scoring in `omr_service.py` uses a grid-density extraction with fallback deterministic answers intended for integration testing.
Replace extraction internals with full contour-based bubble detection tuned for your official answer sheet template before production use.

