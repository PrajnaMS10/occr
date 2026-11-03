# 📄 Receipt OCR

A **fully local, open-source** receipt OCR system that extracts structured data from receipt images using PaddleOCR and LLM-based extraction.

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)
![React](https://img.shields.io/badge/React-19+-61DAFB.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

---

## ✨ Features

- **🔍 Dual Extraction Modes**
  - **Rules-Based**: Fast, deterministic extraction using regex and heuristics
  - **LLM-Based**: Semantic extraction using local Llama 3.2 via Ollama
  
- **🖼️ Image Preprocessing**: Grayscale, adaptive thresholding, deskewing

- **🌐 Full-Stack Application**
  - FastAPI backend with REST endpoints
  - React frontend with drag-and-drop upload
  - Side-by-side comparison view

- **🔒 100% Local**: No cloud APIs, all processing on your machine

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- [Ollama](https://ollama.com/) with `llama3.2` model

### Installation

```bash
# Clone the repository
git clone https://github.com/jeffersonqiu/llm_ocr.git
cd llm_ocr

# Install Python dependencies
uv sync

# Install frontend dependencies
cd web && npm install && cd ..
```

### Running the Application

**1. Start the Backend API**
```bash
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**2. Start the Frontend** (in a new terminal)
```bash
cd web && npm run dev
```

**3. Open your browser**
- Frontend: http://localhost:5173
- API Docs: http://localhost:8000/docs

---

## 📁 Project Structure

```
llm_ocr/
├── README.md              # Project overview
├── docs/                  # Documentation
│   ├── IMPLEMENTATION_PLAN.md
│   ├── LEARNING_NOTES.md
│   └── TASKS_TRACKER.md
├── api/                   # FastAPI backend
│   └── main.py
├── src/                   # Core Python modules
│   ├── image_processor.py
│   ├── ocr_engine.py
│   ├── extractor_rules.py
│   └── extractor_llm.py
├── web/                   # React+Vite frontend
│   └── src/App.jsx
├── notebooks/             # Jupyter notebooks
├── tests/                 # Test files
│   └── verify_api.py
├── images/                # Sample images
└── data/                  # Ground truth data
```

---

## 🔌 API Endpoints

### Multiple receipts and Excel exports

Select or drop multiple JPEG, PNG, WebP, BMP or TIFF images in the upload panel.
Review the previews, remove unwanted images, and choose Rules, LLM or Compare.
The interface displays upload progress and a processing indicator while OCR runs.
Each receipt keeps its filename, vendor, date, items, total and success/error status.
The combined total sums successful receipt totals exactly once; missing totals
remain blank and are excluded. It does not sum item prices into receipt totals.
Compare runs independent batches with separate totals and downloads for each method.

`POST /analyze/batch/rules` and `POST /analyze/batch/llm` accept repeated multipart
`files` fields. Existing single-image endpoints still accept `file` and return the
original receipt shape (unknown values may now be null).

```bash
curl -X POST http://localhost:8000/analyze/batch/rules -F "files=@images/receipt-ocr-original.jpg" -F "files=@another.jpg"
```

Batch responses contain `receipts`, flattened `items` with source information,
`grand_total`, success/failure counts, `export_filename`, `download_url` and
`export_error`. Each receipt also has a batch-local `receipt_id`, distinguishing
uploads even if filenames repeat. A bad image does not stop the remaining images.
If export fails, extraction results remain available with an export error.

Workbooks are saved in the automatically created project-root `exports/` directory,
with UTC timestamps and UUIDs. Previous exports are retained and ignored by Git.
Click **Download Excel (.xlsx)** beneath the current method's results to retrieve
that batch via `GET /exports/{filename}`. Download failures are shown with a retry
available through the same button. New selections and processing runs clear old results.

Each workbook has Summary and Items sheets plus Errors when needed. Prices are
numeric with dollar formatting, matching the application's existing dollar display;
no currency conversion is performed. Headers are frozen, columns sized, and OCR
text is stored as text rather than executable Excel formulas.

Install the new backend dependency with `uv sync` (or `python -m pip install
openpyxl` in an existing environment). Run `python -m unittest discover -s tests
-p test_batch.py` for deterministic API/export integration tests. These use the
sample receipt for real OpenCV preprocessing and mock the OCR and Ollama boundaries.
Real model verification still requires PaddleOCR model files and a running Ollama
server with `llama3.2` installed. Set `VITE_API_URL` when the backend is not at
`http://localhost:8000`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/analyze/rules` | POST | Analyze receipt using rules-based extraction |
| `/analyze/llm` | POST | Analyze receipt using LLM-based extraction |

### Example Request

```bash
curl -X POST "http://localhost:8000/analyze/rules" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@images/receipt.jpg"
```

### Example Response

```json
{
  "vendor": "Walmart",
  "date": "2017-07-28",
  "total": 98.21,
  "items": [
    {"item_name": "MILK", "price": 3.98},
    {"item_name": "BANANAS", "price": 1.25}
  ]
}
```

---

## 📊 Performance

| Mode | Response Time | Accuracy |
|------|---------------|----------|
| Rules-Based | ~35-40s | Good for simple receipts |
| LLM-Based | ~70-80s | Better for complex layouts |

*Note: First request takes longer due to PaddleOCR model loading.*

---

## 🛠️ Development

### Running Tests
```bash
# Test API endpoints
uv run python -m tests.verify_api
```

### Jupyter Notebooks
```bash
uv run jupyter lab
```

---

## 📖 Documentation

Additional documentation is available in the [`docs/`](docs/) folder:

- [`TASKS_TRACKER.md`](docs/TASKS_TRACKER.md) - Progress tracking
- [`IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) - Technical design
- [`LEARNING_NOTES.md`](docs/LEARNING_NOTES.md) - Key learnings

---

## 🔧 Tech Stack

**Backend:**
- PaddleOCR v3.x
- FastAPI
- Ollama (Llama 3.2)
- OpenCV

**Frontend:**
- React 19
- Vite 7
- Axios

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.
