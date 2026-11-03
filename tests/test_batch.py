"""API and workbook integration tests, with deterministic OCR/Ollama boundaries."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from api import main
from src.excel_export import write_export

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

    def test_all_items_from_single_and_five_receipts_download(self):
        # Exercise real preprocessing, normalization and rules extraction, with
        # deterministic recognition output containing twenty items per receipt.
        for method in ["rules", "llm"]:
            for count in [1, 5]:
                with self.subTest(method=method, receipts=count):
                    ocr_results, llm_results = [], []
                    for receipt_index in range(count):
                        vendor = f"Market {receipt_index}"
                        date = f"2026-01-{receipt_index + 1:02d}"
                        price = receipt_index + 1.25
                        receipt_items = [{"item_name": f"Product {item_index:02d}", "price": price}
                                         for item_index in range(20)]
                        rows = [(vendor, 0, 0), (date, 0, 30)]
                        for item_index, item in enumerate(receipt_items):
                            y = 60 + item_index * 30
                            rows.extend([(item["item_name"], 0, y), (f"{price:.2f}", 200, y)])
                        rows.extend([("TOTAL", 0, 690), (f"{price * 20:.2f}", 200, 690)])
                        ocr_results.append([{"text": text, "bbox": [x, y, x + 100, y + 20],
                                             "center_y": y + 10} for text, x, y in rows])
                        llm_results.append({"vendor": vendor, "date": date, "total": price * 20,
                                            "items": [{"name": item["item_name"], "price": item["price"]}
                                                      for item in receipt_items]})
                    self.engine.process.side_effect = ocr_results
                    with patch.object(main.llm_engine, "extract", side_effect=llm_results):
                        response = self.batch(method, files=[
                            ("files", (f"receipt{i}.jpg", SAMPLE, "image/jpeg")) for i in range(count)])
                    self.assertEqual(response.status_code, 200, response.text)
                    batch = response.json()
                    self.assertEqual(batch["successful_count"], count)
                    self.assertEqual(len(batch["items"]), count * 20)
                    download = self.client.get(batch["download_url"])
                    self.assertEqual(download.status_code, 200)
                    workbook = load_workbook(BytesIO(download.content), data_only=True)
                    expected_items, expected_summary = [], []
                    for receipt in batch["receipts"]:
                        data = receipt["data"]
                        self.assertEqual(len(data["items"]), 20)
                        expected_items.extend((receipt["filename"], data["vendor"], data["date"],
                                               item["item_name"], item["price"]) for item in data["items"])
                        expected_summary.append((receipt["filename"], data["vendor"], data["date"],
                                                 data["total"], "success", method))
                    self.assertEqual(list(workbook["Items"].values)[1:], expected_items)
                    self.assertEqual(list(workbook["Summary"].values)[1:-1], expected_summary)
                    expected_total = sum(result["total"] for result in llm_results)
                    self.assertEqual(batch["grand_total"], expected_total)
                    self.assertEqual(workbook["Summary"].cell(count + 2, 4).value, expected_total)
                    self.assertEqual(workbook["Items"].freeze_panes, "A2")
                    self.assertIn("0.00", workbook["Items"]["E2"].number_format)
                    self.assertEqual(workbook["Items"]["E2"].data_type, "n")
                    workbook.close()

    def test_export_uses_receipt_items_without_flattened_list(self):
        receipts = [{"filename": "same.jpg", "status": "success", "method": "rules", "data": {
            "vendor": "First", "date": "2026-01-01", "total": 3,
            "items": [{"item_name": "Repeated", "price": 1}, {"item_name": "Repeated", "price": 1},
                      {"item_name": None, "price": None}, {"price": 0}, {"item_name": "Missing price"}]}},
            {"filename": "same.jpg", "status": "success", "method": "llm", "data": {
                "vendor": "Second", "date": None, "total": 4,
                "items": [{"item_name": "Other", "price": 4}]}},
            {"filename": "failed.jpg", "status": "failed", "method": "rules", "error": "OCR failed",
             "data": {"items": [{"item_name": "Do not export", "price": 99}]}}]
        for flattened in [None, [], [{"item_name": "Stale item", "price": 999}]]:
            with self.subTest(flattened=flattened):
                batch = {"receipts": receipts, "grand_total": 7}
                if flattened is not None:
                    batch["items"] = flattened
                path = Path(self.directory.name) / "receipt_items.xlsx"
                write_export(batch, path)
                workbook = load_workbook(path, data_only=True)
                self.assertEqual(list(workbook["Items"].values)[1:], [
                    ("same.jpg", "First", "2026-01-01", "Repeated", 1),
                    ("same.jpg", "First", "2026-01-01", "Repeated", 1),
                    ("same.jpg", "First", "2026-01-01", None, None),
                    ("same.jpg", "First", "2026-01-01", None, 0),
                    ("same.jpg", "First", "2026-01-01", "Missing price", None),
                    ("same.jpg", "Second", None, "Other", 4)])
                self.assertEqual(workbook["Summary"]["D5"].value, 7)
                self.assertEqual(workbook["Errors"].max_row, 2)
                workbook.close()

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
