from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any, List, Literal, Optional
import logging
import math
import shutil
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from src.image_processor import preprocess_receipt
from src.extractor_rules import extract_receipt_data
from src.extractor_llm import ReceiptLLM
from src.excel_export import write_export

app = FastAPI(title="Receipt OCR API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"
EXPORT_DIR = BASE_DIR / "exports"
ALLOWED_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}
ocr_engine = None
llm_engine = ReceiptLLM()
pipeline_lock = Lock()
logger = logging.getLogger(__name__)

class HealthResponse(BaseModel):
    status: str
    version: str

class Item(BaseModel):
    item_name: Optional[str] = None
    price: Optional[float] = None

class ReceiptData(BaseModel):
    vendor: Optional[str] = None
    date: Optional[str] = None
    total: Optional[float] = None
    items: List[Item]

def get_ocr_engine():
    global ocr_engine
    if ocr_engine is None:
        from src.ocr_engine import ReceiptOCR
        ocr_engine = ReceiptOCR()
    return ocr_engine

def number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid numeric extraction value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite numeric extraction value")
    return result

def normalize(data):
    if not isinstance(data, dict) or not data or not any(
        key in data for key in ("vendor", "date", "total", "items")
    ):
        raise ValueError("Extraction returned no valid receipt data")
    items = data.get("items")
    if items is None:
        items = []
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("Extraction returned malformed items")
    return ReceiptData(
        vendor=data.get("vendor"), date=data.get("date"), total=number(data.get("total")),
        items=[Item(item_name=item.get("item_name") or item.get("name"),
                    price=number(item.get("price"))) for item in items],
    ).model_dump()

def process_upload(file: UploadFile, method: str):
    """One pipeline for legacy single uploads and batch records."""
    temp_path = None
    try:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_TYPES or file.content_type not in (
            ALLOWED_TYPES.get(suffix), "application/octet-stream", None
        ):
            raise ValueError("Unsupported file type. Use JPEG, PNG, WebP, BMP or TIFF.")
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        temp_path = TEMP_DIR / f"{uuid.uuid4().hex}{suffix}"
        with temp_path.open("wb") as destination:
            shutil.copyfileobj(file.file, destination)
        if temp_path.stat().st_size == 0:
            raise ValueError("Uploaded file is empty")
        image = preprocess_receipt(temp_path)
        with pipeline_lock:
            engine = get_ocr_engine()
            tokens = engine.process(image)
            if not tokens:
                raise ValueError("OCR found no readable text")
            data = (extract_receipt_data(tokens) if method == "rules"
                    else llm_engine.extract(engine.get_full_text(tokens)))
        return normalize(data)
    finally:
        file.file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

@app.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "healthy", "version": "1.0.0"}

@app.get("/")
def root():
    return {"message": "Receipt OCR API is running. Visit /docs for documentation."}

def analyze_single(file, method):
    try:
        return process_upload(file, method)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/analyze/rules", response_model=ReceiptData)
def analyze_rules(file: UploadFile = File(...)):
    return analyze_single(file, "rules")

@app.post("/analyze/llm", response_model=ReceiptData)
def analyze_llm(file: UploadFile = File(...)):
    return analyze_single(file, "llm")

@app.post("/analyze/batch/{method}")
def analyze_batch(method: Literal["rules", "llm"], files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one receipt image")
    receipts, items = [], []
    total = Decimal("0")
    for index, file in enumerate(files):
        record = {"receipt_id": index + 1, "filename": file.filename or "Unnamed",
                  "method": method, "status": "failed", "error": None, "data": None}
        try:
            data = process_upload(file, method)
            record.update(status="success", data=data)
            if data["total"] is not None:
                total += Decimal(str(data["total"]))
            items.extend({**item, "receipt_id": index + 1, "filename": record["filename"],
                          "vendor": data["vendor"], "date": data["date"]}
                         for item in data["items"])
        except Exception as exc:
            record["error"] = str(exc) or "Receipt processing failed"
        receipts.append(record)
    result = {"receipts": receipts, "items": items, "grand_total": float(total),
              "successful_count": sum(r["status"] == "success" for r in receipts),
              "failed_count": sum(r["status"] == "failed" for r in receipts),
              "export_filename": None, "download_url": None, "export_error": None}
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"receipts_{datetime.now(timezone.utc):%Y%m%d_%H%M%S_%f}_{uuid.uuid4().hex}.xlsx"
        write_export(result, EXPORT_DIR / filename)
        result.update(export_filename=filename, download_url=f"/exports/{filename}")
    except Exception:
        logger.exception("Excel export failed")
        result["export_error"] = "Excel generation failed. Your extraction results are still available."
    return result

@app.get("/exports/{filename}")
def download_export(filename: str):
    if Path(filename).name != filename or not filename.startswith("receipts_") or not filename.endswith(".xlsx"):
        raise HTTPException(status_code=404, detail="Export not found")
    path = EXPORT_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(path, filename=filename,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
