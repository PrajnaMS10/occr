import json
import re
import ollama
from typing import Dict, Any, Optional


class ReceiptLLM:
    """
    LLM wrapper for receipt data extraction using local Ollama models.
    """

    SYSTEM_PROMPT = """\
You are an expert receipt parser specialising in US grocery and retail receipts.

Your task: extract structured data from OCR text of a receipt and return ONLY valid JSON.
No markdown code fences. No explanation. No commentary. Just the raw JSON object.

--- Receipt format notes ---
• Item lines look like:  ITEM NAME   UPC-CODE   PRICE  FLAG
  - UPC-CODE: a long (8–14 digit) barcode number — IGNORE it.
  - FLAG: a 1–2 letter suffix after the price (X, N, F, O, KI, B, H …) — IGNORE it.
    X = taxable, N = non-taxable, F = food-exempt, O = other. They are NOT part of the price.
  - PRICE: the dollar amount immediately before the flag (e.g. "1.97", "19.77").
  - COUPON lines reduce the total — include them as negative-price items.
• Date often appears near the bottom as  MM/DD/YY  (e.g. "07/28/17" = 2017-07-28).
• SUBTOTAL ≠ TOTAL. Use the TOTAL (or VISA TEND amount) as the grand total.
• If a field cannot be determined, use null.

--- JSON schema (return exactly this shape) ---
{
  "vendor": "string or null",
  "date": "YYYY-MM-DD or null",
  "total": number or null,
  "items": [
    {"name": "string", "price": number}
  ]
}

--- Example ---
Receipt text:
  Walmart
  07/28/17  02:39:48
  PET TOY  004747571846  1.97 X
  COUPON 23100  52310037000  -1.00 O
  SUBTOTAL  93.62
  TAX 1  6.750 %  4.59
  TOTAL  98.21
  VISA TEND  98.21

Expected JSON:
{
  "vendor": "Walmart",
  "date": "2017-07-28",
  "total": 98.21,
  "items": [
    {"name": "PET TOY", "price": 1.97},
    {"name": "COUPON 23100", "price": -1.00}
  ]
}
"""

    def __init__(self, model_name: str = "llama3.2"):
        self.model_name = model_name

    def extract(self, ocr_text: str) -> Dict[str, Any]:
        """
        Extract structured data from raw OCR text using the local LLM.
        """
        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': self.SYSTEM_PROMPT},
                    {'role': 'user',   'content': self._build_user_prompt(ocr_text)},
                ],
                options={
                    'temperature': 0.0,   # Deterministic — no creative hallucination
                    'num_predict': 2048,  # Allow enough tokens for long receipts
                }
            )
            content = response['message']['content']
            return self._parse_json(content)

        except Exception as e:
            print(f"LLM Extraction failed: {e}")
            return {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_user_prompt(self, text: str) -> str:
        return (
            "Receipt text (from OCR — may contain minor misreads):\n\n"
            f"{text}\n\n"
            "Extract the data and return ONLY the JSON object."
        )

    def _parse_json(self, response_text: str) -> Dict[str, Any]:
        """
        Robustly parse JSON from LLM response.

        Attempts (in order):
        1. Strip markdown fences and parse directly.
        2. Find the first '{...}' block and parse that.
        3. Return empty dict.
        """
        s = response_text.strip()

        # Remove markdown code fences
        s = re.sub(r'^```(?:json)?\s*', '', s)
        s = re.sub(r'\s*```$', '', s.strip())
        s = s.strip()

        # Attempt 1: direct parse
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

        # Attempt 2: find first JSON object in the response
        m = re.search(r'\{.*\}', s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        print(f"[LLM] Failed to parse JSON. Raw output:\n{response_text[:500]}")
        return {}
