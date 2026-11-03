"""API and workbook integration tests, with deterministic OCR/Ollama boundaries."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from api import main

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = (ROOT / "images" / "receipt-ocr-original.jpg").read_bytes()

def tokens():
    return [{"text": text, "bbox": [x, y, x + 100, y + 20], "center_y": y + 10}
            for text, x, y in [("Market", 0, 0), ("2026-01-02", 0, 30),
                               ("Milk", 0, 60), ("2.25", 200, 60),
                               ("TOTAL", 0, 90), ("2.25", 200, 90)]]

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.export_patch = patch.object(main, "EXPORT_DIR", Path(self.directory.name) / "exports")
        self.export_patch.start()
        self.addCleanup(self.export_patch.stop)
        self.engine = Mock()
        self.engine.process.return_value = tokens()
        self.engine.get_full_text.return_value = "Market Milk 2.25 TOTAL 2.25"
        self.ocr_patch = patch.object(main, "get_ocr_engine", return_value=self.engine)
        self.ocr_patch.start()
        self.addCleanup(self.ocr_patch.stop)
        self.client = TestClient(main.app)

    def batch(self, method="rules", files=None):
        return self.client.post(f"/analyze/batch/{method}", files=files or [
            ("files", ("one.jpg", SAMPLE, "image/jpeg")),
            ("files", ("two.jpg", SAMPLE, "image/jpeg"))])

    def test_single_endpoints_preserve_shape(self):
        for method in ["rules", "llm"]:
            with patch.object(main.llm_engine, "extract", return_value={
                "vendor": "Market", "total": 2.25, "items": [{"name": "Milk", "price": 2.25}]
            }):
                response = self.client.post(f"/analyze/{method}", files={"file": ("one.jpg", SAMPLE, "image/jpeg")})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["total"], 2.25)
            self.assertEqual(response.json()["items"][0]["item_name"], "Milk")

    def test_batch_rules_excel_and_download(self):
        response = self.batch()
        self.assertEqual(response.status_code, 200, response.text)
        batch = response.json()
        self.assertEqual(batch["grand_total"], 4.5)
        self.assertEqual(batch["successful_count"], 2)
        self.assertEqual([i["filename"] for i in batch["items"]], ["one.jpg", "two.jpg"])
        download = self.client.get(batch["download_url"])
        self.assertEqual(download.status_code, 200)
        workbook = load_workbook(BytesIO(download.content), data_only=True)
        self.assertEqual(workbook.sheetnames, ["Summary", "Items"])
        self.assertEqual(workbook["Summary"]["D4"].value, 4.5)
        self.assertEqual(workbook["Items"].max_row, 3)
        self.assertEqual(workbook["Summary"].freeze_panes, "A2")
        self.assertEqual(workbook["Items"]["E2"].data_type, "n")
        self.assertIn("0.00", workbook["Items"]["E2"].number_format)
        workbook.close()
        second = self.batch(files=[("files", ("new.jpg", SAMPLE, "image/jpeg"))]).json()
        self.assertNotEqual(second["export_filename"], batch["export_filename"])
        self.assertEqual(second["grand_total"], 2.25)
        self.assertEqual(self.client.get(batch["download_url"]).status_code, 200)

    def test_invalid_unreadable_and_empty_files_are_isolated(self):
        response = self.batch(files=[("files", ("good.jpg", SAMPLE, "image/jpeg")),
                                     ("files", ("bad.txt", b"text", "text/plain")),
                                     ("files", ("bad.jpg", b"not an image", "image/jpeg")),
                                     ("files", ("empty.jpg", b"", "image/jpeg"))])
        batch = response.json()
        self.assertEqual(batch["successful_count"], 1)
        self.assertEqual(batch["failed_count"], 3)
        self.assertEqual(batch["grand_total"], 2.25)
        workbook = load_workbook(BytesIO(self.client.get(batch["download_url"]).content))
        self.assertEqual(workbook["Errors"].max_row, 4)
        self.assertEqual(workbook["Summary"].max_row, 6)
        workbook.close()

    def test_llm_nulls_decimal_total_and_text_safety(self):
        results = [{"vendor": "=1+1", "date": None, "total": "0.1", "items": [{"name": "=1+1", "price": None}]},
                   {"vendor": None, "total": "0.2", "items": None}]
        with patch.object(main.llm_engine, "extract", side_effect=results):
            batch = self.batch("llm").json()
        self.assertEqual(batch["grand_total"], 0.3)
        self.assertIsNone(batch["items"][0]["price"])
        workbook = load_workbook(BytesIO(self.client.get(batch["download_url"]).content))
        self.assertEqual(workbook["Items"]["D2"].data_type, "s")
        workbook.close()

    def test_llm_failures_and_malformed_outputs(self):
        for bad in [{}, [], {"items": ["bad"]}, {"total": "NaN"}, {"total": "invalid"}]:
            with patch.object(main.llm_engine, "extract", side_effect=[bad, {"total": 3, "items": []}]):
                batch = self.batch("llm").json()
            self.assertEqual(batch["failed_count"], 1)
            self.assertEqual(batch["grand_total"], 3)
        with patch.object(main.llm_engine, "extract", side_effect=RuntimeError("Ollama unavailable")):
            batch = self.batch("llm").json()
        self.assertEqual(batch["failed_count"], 2)

    def test_ocr_failure_and_missing_total(self):
        self.engine.process.side_effect = [RuntimeError("OCR failed"), tokens()]
        self.assertEqual(self.batch().json()["failed_count"], 1)
        self.engine.process.side_effect = None
        self.engine.process.return_value = tokens()[:-2]
        batch = self.batch().json()
        self.assertIsNone(batch["receipts"][0]["data"]["total"])
        self.assertEqual(batch["grand_total"], 0)
        self.engine.process.return_value = []
        self.assertEqual(self.batch().json()["failed_count"], 2)

    def test_export_error_preserves_results(self):
        with patch.object(main, "write_export", side_effect=OSError("disk full")):
            batch = self.batch().json()
        self.assertEqual(batch["successful_count"], 2)
        self.assertIsNone(batch["download_url"])
        self.assertTrue(batch["export_error"])

    def test_empty_upload_bad_method_and_missing_download(self):
        self.assertEqual(self.client.post("/analyze/batch/rules").status_code, 422)
        self.assertEqual(self.batch("invalid").status_code, 422)
        self.assertEqual(self.client.get("/exports/receipts_missing.xlsx").status_code, 404)
        self.assertEqual(self.client.get("/exports/..%5Cpyproject.toml").status_code, 404)

if __name__ == "__main__":
    unittest.main()
