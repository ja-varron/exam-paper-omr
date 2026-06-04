import time

import cv2 as cv
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from preprop import process_image_bgr

MAX_UPLOAD_BYTES = 6 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png"}

app = FastAPI(title="OMR Answers API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported image type.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image too large.")

    np_data = np.frombuffer(data, np.uint8)
    img = cv.imdecode(np_data, cv.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image payload.")

    start = time.perf_counter()
    answers, warnings = process_image_bgr(img)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return {
        "answers": answers,
        "warnings": warnings,
        "processing_ms": elapsed_ms,
    }
