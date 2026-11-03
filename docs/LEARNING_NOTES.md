# 📚 Receipt OCR Learning Notes

> **Project:** Local Receipt OCR → Full-Stack Application  
> **Status:** ✅ Complete (All Phases)

---

## 🗺️ Project Phases

```
Phase 1: Setup    →  Phase 2: Notebooks  →  Phase 3: Modules  →  Phase 4: API  →  Phase 5: Frontend
   ✅                     ✅                     ✅                  ✅               ✅
```

---

## 📖 Key Learnings

### 1. Image Preprocessing Matters
- Grayscale + adaptive thresholding significantly improves OCR accuracy
- Deskewing rotated receipts prevents text line fragmentation
- Simple preprocessing often beats complex model tuning

### 2. PaddleOCR v3.x Changes
**Breaking Change:** Output format changed from tuples to `OCRResult` dict-like objects.

```python
# v2.x format (old)
line = [[bbox_points], (text, confidence)]

# v3.x format (new) - OCRResult object
result['rec_texts']   # List of texts
result['rec_scores']  # List of confidences  
result['rec_boxes']   # numpy array of boxes
```

### 3. Rules vs LLM Trade-offs

| Approach | Speed | Accuracy | Best For |
|----------|-------|----------|----------|
| Rules | ~35s | Good | Simple, structured receipts |
| LLM | ~75s | Better | Complex layouts, varied formats |

### 4. Local LLM Integration
- Ollama provides easy local LLM deployment
- Llama 3.2 (3B) runs well on consumer hardware
- Structured JSON prompts work well for extraction tasks

---

## 🏗️ Architecture Decisions

### Backend
- **FastAPI** for async performance
- **Single-file API** (`api/main.py`) for simplicity
- **Shared `src/` modules** between API and notebooks

### Frontend
- **Vite + React** for fast development
- **Vanilla CSS** with modern design (glassmorphism, dark theme)
- **Three modes**: Rules, LLM, Compare

---

## 📊 Output Schema

```json
{
  "vendor": "string",
  "date": "YYYY-MM-DD",
  "total": 0.00,
  "items": [
    {"item_name": "string", "price": 0.00}
  ]
}
```

---

## 🎯 Success Criteria (All Met ✅)

- [x] Full-stack application with UI
- [x] Two extraction modes (Rules + LLM)
- [x] Side-by-side comparison
- [x] 100% local processing
- [x] Well-documented codebase
