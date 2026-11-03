from paddleocr import PaddleOCR
import cv2
import os
import statistics
import numpy as np
from pathlib import Path
from typing import List, Dict, Union


class ReceiptOCR:
    """
    OCR wrapper for receipt images (PaddleOCR v3.x).

    Usage:
        ocr = ReceiptOCR()
        results = ocr.process("path/to/receipt.jpg")   # or numpy array
        text    = ocr.get_full_text(results)
    """

    def __init__(self, lang: str = 'en'):
        os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

        self.engine = PaddleOCR(
            use_textline_orientation=False,  # We already deskew — skipping saves ~30% time
            enable_mkldnn=False,             # Avoid unsupported oneDNN PIR attrs on Windows
            lang=lang,
        )

    def process(self, image: Union[str, Path, np.ndarray]) -> List[Dict]:
        """
        Run OCR on an image (file path OR pre-loaded numpy array) and return
        parsed, sorted results.

        Accepting numpy arrays avoids a disk round-trip when the caller has
        already preprocessed the image in memory.

        Note: PaddleOCR v3.x requires 3-channel BGR images internally.
              Grayscale arrays are automatically converted here.

        Returns:
            List of dicts: text, confidence, bbox [x1,y1,x2,y2], center_y, center_x
        """
        if isinstance(image, Path):
            src = str(image)
        elif isinstance(image, np.ndarray):
            # PaddleOCR v3.x internal pipeline requires 3-channel BGR —
            # convert grayscale (H, W) or single-channel (H, W, 1) to BGR
            if image.ndim == 2:
                src = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            elif image.ndim == 3 and image.shape[2] == 1:
                src = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            else:
                src = image  # already BGR
        else:
            src = image  # string path

        results = self.engine.ocr(src)
        return self._parse_results(results)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_full_text(self, parsed_results: List[Dict]) -> str:
        """
        Reconstruct the receipt as a human-readable string preserving
        the two-column layout (item name left, price right).

        Args:
            parsed_results: Output of process()

        Returns:
            Multi-line string suitable for feeding to an LLM.
        """
        rows = self._group_into_rows(parsed_results)
        lines = []
        for row in rows:
            row_sorted = sorted(row, key=lambda t: t['bbox'][0])
            lines.append("  ".join(t['text'] for t in row_sorted))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal parsing helpers
    # ------------------------------------------------------------------

    def _parse_results(self, results) -> List[Dict]:
        """Parse raw PaddleOCR v3.x output into a clean, sorted token list."""
        parsed = []

        if not results or results[0] is None:
            return parsed

        page_result = results[0]

        # ---------- PaddleOCR v3.x dict-like format ----------
        if 'rec_texts' in page_result:
            texts  = page_result['rec_texts']
            scores = page_result['rec_scores']
            boxes  = page_result['rec_boxes']   # ndarray (N, 4)

            for i in range(len(texts)):
                text = texts[i].strip()
                if not text:
                    continue

                confidence = scores[i]
                box = boxes[i]
                x1, y1, x2, y2 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
                center_y = (y1 + y2) / 2
                center_x = (x1 + x2) / 2

                parsed.append({
                    'text':       text,
                    'confidence': round(confidence, 3),
                    'bbox':       [round(x1), round(y1), round(x2), round(y2)],
                    'center_y':   round(center_y, 1),
                    'center_x':   round(center_x, 1),
                })

        # ---------- Legacy format fallback (PaddleOCR v2.x) ----------
        else:
            for line in page_result:
                bbox_points = line[0]
                text, confidence = line[1]
                text = text.strip()
                if not text:
                    continue

                x_coords = [p[0] for p in bbox_points]
                y_coords = [p[1] for p in bbox_points]
                x1, x2 = min(x_coords), max(x_coords)
                y1, y2 = min(y_coords), max(y_coords)
                center_y = (y1 + y2) / 2
                center_x = (x1 + x2) / 2

                parsed.append({
                    'text':       text,
                    'confidence': round(float(confidence), 3),
                    'bbox':       [round(x1), round(y1), round(x2), round(y2)],
                    'center_y':   round(center_y, 1),
                    'center_x':   round(center_x, 1),
                })

        parsed.sort(key=lambda t: (t['center_y'], t['center_x']))
        return parsed

    def _compute_line_height(self, tokens: List[Dict]) -> float:
        heights = [abs(t['bbox'][3] - t['bbox'][1]) for t in tokens
                   if t['bbox'][3] > t['bbox'][1]]
        if not heights:
            return 20.0
        return statistics.median(heights)

    def _group_into_rows(self, tokens: List[Dict]) -> List[List[Dict]]:
        """Group tokens into visual rows using an adaptive Y-tolerance (55% of median line height)."""
        if not tokens:
            return []

        tolerance = self._compute_line_height(tokens) * 0.55

        rows: List[List[Dict]] = []
        current_row = [tokens[0]]

        for token in tokens[1:]:
            if abs(token['center_y'] - current_row[-1]['center_y']) <= tolerance:
                current_row.append(token)
            else:
                rows.append(current_row)
                current_row = [token]

        rows.append(current_row)
        return rows
