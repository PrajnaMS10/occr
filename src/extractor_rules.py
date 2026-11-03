import re
import statistics
from typing import List, Dict, Optional, Any
from dateutil import parser as dateutil_parser


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SKIP_ROW_KEYWORDS = {
    'subtotal', 'sub total', 'sub-total',
    'tax', 'hst', 'gst', 'pst', 'vat',
    'total', 'grand total', 'amount due', 'balance due',
    'tend', 'cash', 'change', 'debit', 'credit', 'visa', 'mastercard',
    'approval', 'ref #', 'ref#', 'trans id', 'trans #',
    'terminal', 'tc#', 'tc #', 'aid', 'validation', 'payment service',
    'change due', 'items sold', '# items',
    'st#', 'op#', 'te#', 'tr#',
    'manager', 'save money', 'low price', 'customer copy',
    'coupon', 'signature',
}

# Walmart trailing tax/flag chars after prices ("1.97 X", "5.47 N")
_WALMART_FLAGS = re.compile(r'^[XNFOIBHEKIKT]{1,2}$', re.IGNORECASE)

# UPC / item-code: 6+ digits optionally followed by 1-3 uppercase letters (e.g. 00000000004614KI)
_UPC_PATTERN = re.compile(r'^\d{6,}[A-Z]{0,3}$', re.IGNORECASE)

# Standalone price token (bare number, optional currency prefix)
_AMOUNT_RE = re.compile(r'^[\$£€]?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)$')

# Amount anywhere in a line
_AMOUNT_IN_LINE_RE = re.compile(r'[\$£€]?\s*(\d{1,3}(?:,\d{3})*\.\d{2})')

# Trailing single-letter tax flags in assembled item names ("CALZONE F" → "CALZONE")
_TRAILING_FLAG_RE = re.compile(r'\s+[FNIOXBHEK]{1,2}$', re.IGNORECASE)


def _is_skip_row(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _SKIP_ROW_KEYWORDS)


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------

def extract_vendor(lines: List[Dict[str, Any]]) -> Optional[str]:
    IGNORE_WORDS = {'receipt', 'welcome', 'tax invoice', 'copy', 'payment'}
    for line in lines[:5]:
        text = line['text'].strip()
        if len(text) < 2:
            continue
        if any(w in text.lower() for w in IGNORE_WORDS):
            continue
        return text
    return None


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------

def extract_date(lines: List[Dict[str, Any]]) -> Optional[str]:
    """
    Extract transaction date and return ISO format (YYYY-MM-DD).
    Handles MM/DD/YY (most common on US receipts like Walmart 07/28/17).
    """
    date_patterns = [
        (r'\d{4}-\d{2}-\d{2}',              False),   # ISO
        (r'\d{1,2}/\d{1,2}/\d{2}(?!\d)',    True),    # MM/DD/YY  ← Walmart
        (r'\d{1,2}/\d{1,2}/\d{4}',          False),   # MM/DD/YYYY
        (r'\d{2}-\d{2}-\d{4}',              False),   # DD-MM-YYYY
        (r'\d{1,2}\s+[A-Za-z]{3}\s+\d{4}', False),   # 28 Jul 2017
        (r'[A-Za-z]{3}\s+\d{1,2},?\s+\d{4}', False), # Jul 28, 2017
    ]

    texts = [line['text'] for line in lines]
    # Also scan adjacent-pair merges (OCR sometimes splits dates)
    extended = texts + [texts[i] + ' ' + texts[i + 1] for i in range(len(texts) - 1)]

    for text in extended:
        for pattern, is_2digit_year in date_patterns:
            m = re.search(pattern, text)
            if m:
                date_str = m.group(0)
                try:
                    if is_2digit_year:
                        dt = dateutil_parser.parse(date_str, dayfirst=False, yearfirst=False)
                        if dt.year > 2030:
                            dt = dt.replace(year=dt.year - 100)
                    else:
                        dt = dateutil_parser.parse(date_str, dayfirst=False)
                    return dt.strftime('%Y-%m-%d')
                except (ValueError, OverflowError):
                    continue
    return None


# ---------------------------------------------------------------------------
# Total
# ---------------------------------------------------------------------------

def extract_total(lines: List[Dict[str, Any]]) -> Optional[float]:
    def _amounts(text: str) -> List[float]:
        vals = []
        for m in _AMOUNT_IN_LINE_RE.finditer(text):
            try:
                vals.append(float(m.group(1).replace(',', '')))
            except ValueError:
                pass
        return vals

    # Join adjacent OCR tokens on the same row (TOTAL and price may be separate).
    rows = []
    for line in lines:
        if rows and abs(line.get('center_y', -1000) - rows[-1].get('center_y', 1000)) < 10:
            rows[-1]['text'] += ' ' + line['text']
        else:
            rows.append(dict(line))
    lines = rows
    # Pass 1: TOTAL keyword (not SUBTOTAL)
    candidates: List[float] = []
    for line in lines:
        lower = line['text'].lower()
        if re.search(r'\btotal\b', lower) and 'subtotal' not in lower and 'sub total' not in lower:
            candidates.extend(_amounts(line['text']))
    if candidates:
        return max(candidates)

    # Pass 2: TEND lines (Walmart payment tender)
    tend: List[float] = []
    for line in lines:
        if 'tend' in line['text'].lower():
            tend.extend(_amounts(line['text']))
    if tend:
        return max(tend)

    # Missing totals stay missing; an item or change amount is not a receipt total.
    return None


def extract_subtotal(lines: List[Dict[str, Any]]) -> float:
    """
    Extract SUBTOTAL specifically (before-tax total).
    Returns 0.0 if not found.
    """
    for line in lines:
        lower = line['text'].lower()
        if 'subtotal' in lower or 'sub total' in lower or 'sub-total' in lower:
            for m in _AMOUNT_IN_LINE_RE.finditer(line['text']):
                try:
                    return float(m.group(1).replace(',', ''))
                except ValueError:
                    pass
    return 0.0


# ---------------------------------------------------------------------------
# Price correction: fix OCR "0" → "8" misread
# ---------------------------------------------------------------------------

def _correct_prices(items: List[Dict[str, Any]], total: float,
                     subtotal: float = 0.0) -> List[Dict[str, Any]]:
    """
    Post-process items to fix a common OCR error where "0.XX" is read as "8.XX".

    Strategy (combinatorial + heuristic):
    1. Identify all items whose price is 8.XX (8.00 ≤ p < 9.00).
    2. Enumerate all 2^n correction combos; pick combo closest to anchor
       (SUBTOTAL preferred, else TOTAL).
    3. Heuristic pass: if ≥3 items originally shared the same 8.XX price and
       the majority were corrected, correct the rest too.  This catches cases
       where missing items (coupons, items OCR failed to detect) throw off
       the subtotal-based combinatorial search.
    4. With ≤15 candidates this is at most 2^15 = 32768 iterations — instant.
    """
    anchor = subtotal if subtotal > 0 else total
    if anchor <= 0:
        return items

    corrected = [dict(i) for i in items]  # shallow copy

    # Find indices of 8.XX candidates
    candidates = [i for i, it in enumerate(corrected) if 8.0 <= it['price'] < 9.0]

    if not candidates:
        return corrected

    # Cap at 15 to keep combinatorial search tractable
    if len(candidates) > 15:
        candidates = candidates[:15]

    base_sum = sum(it['price'] for it in corrected)
    best_mask = 0          # bitmask of which candidates to correct
    best_delta = abs(base_sum - anchor)

    n = len(candidates)
    for mask in range(1, 1 << n):
        adjustment = 0.0
        for bit in range(n):
            if mask & (1 << bit):
                adjustment += 8.0   # each 8.XX → 0.XX saves exactly 8.00
        new_sum = base_sum - adjustment
        delta = abs(new_sum - anchor)
        if delta < best_delta:
            best_delta = delta
            best_mask = mask

    # Apply the best correction
    corrected_indices = set()
    for bit in range(n):
        if best_mask & (1 << bit):
            idx = candidates[bit]
            corrected[idx]['price'] = round(corrected[idx]['price'] - 8.0, 2)
            corrected_indices.add(idx)

    # --- Heuristic pass ---
    # If ≥3 items shared the same original 8.XX price and majority were corrected,
    # correct any remaining ones too (OCR almost never misreads the same
    # digit differently across identical items).

    # Group candidates by their original 8.XX price
    price_groups: Dict[float, list] = {}
    for idx in candidates:
        p = items[idx]['price']
        price_groups.setdefault(p, []).append(idx)

    for price_val, group_indices in price_groups.items():
        if len(group_indices) < 3:
            continue
        num_corrected = sum(1 for idx in group_indices if idx in corrected_indices)
        # If majority were corrected, correct the rest
        if num_corrected >= len(group_indices) // 2:
            for idx in group_indices:
                if idx not in corrected_indices:
                    corrected[idx]['price'] = round(items[idx]['price'] - 8.0, 2)
                    corrected_indices.add(idx)

    return corrected


# ---------------------------------------------------------------------------
# Item extraction
# ---------------------------------------------------------------------------

def extract_items(lines: List[Dict[str, Any]], total: float = 0.0,
                  subtotal: float = 0.0) -> List[Dict[str, Any]]:
    """
    Extract line items:
    1. Adaptive Y-tolerance grouping
    2. Strip UPC codes (incl. alphanumeric like 00000000004614KI) and Walmart tax flags
    3. Strip trailing flag letters from assembled name ("CALZONE F" → "CALZONE")
    4. Post-process prices to correct OCR 0→8 misread
    """
    if not lines:
        return []

    # Adaptive line height
    heights = [abs(l['bbox'][3] - l['bbox'][1]) for l in lines if l['bbox'][3] > l['bbox'][1]]
    line_height = statistics.median(heights) if heights else 20.0
    tolerance   = line_height * 0.55

    # Group tokens into rows
    rows: List[List[Dict]] = []
    current_row = [lines[0]]
    for token in lines[1:]:
        if abs(token['center_y'] - current_row[-1]['center_y']) <= tolerance:
            current_row.append(token)
        else:
            rows.append(current_row)
            current_row = [token]
    rows.append(current_row)

    items: List[Dict[str, Any]] = []

    for row in rows:
        row_sorted = sorted(row, key=lambda t: t['bbox'][0])
        full_text = ' '.join(t['text'] for t in row_sorted)

        if _is_skip_row(full_text):
            continue

        # Remove UPC codes (long numeric or alphanumeric codes)
        meaningful = [t for t in row_sorted if not _UPC_PATTERN.match(t['text'])]

        # Remove trailing Walmart tax/flag tokens (X, N, F, O, KI …)
        while meaningful and _WALMART_FLAGS.match(meaningful[-1]['text']):
            meaningful.pop()

        if len(meaningful) < 2:
            continue

        # Last token should be the price
        last_token  = meaningful[-1]['text']
        price_match = _AMOUNT_RE.match(last_token)

        if not price_match:
            continue

        price_str = price_match.group(1).replace(',', '')
        try:
            price = float(price_str)
        except ValueError:
            continue

        # Build name from remaining tokens (also strip any UPCs that slipped through)
        name_tokens = [t for t in meaningful[:-1] if not _UPC_PATTERN.match(t['text'])]
        name = ' '.join(t['text'] for t in name_tokens).strip()

        # Strip trailing single-letter tax flags from the assembled name
        # e.g. "CALZONE F" → "CALZONE", "3 ORANGES F" → "3 ORANGES"
        name = _TRAILING_FLAG_RE.sub('', name).strip()

        if not name:
            continue

        # Safety guard: skip summary rows that slipped past keyword filter
        if any(kw in name.lower() for kw in ('total', 'tax', 'subtotal')):
            continue

        # Skip implausible prices (barcodes misread as prices)
        if price > 9999:
            continue

        items.append({'item_name': name, 'price': price})

    # Post-process: correct OCR 0→8 price misread using subtotal/total as anchor
    items = _correct_prices(items, total, subtotal=subtotal)

    return items


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_receipt_data(ocr_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Main entry point for rules-based extraction."""
    vendor   = extract_vendor(ocr_results)
    date     = extract_date(ocr_results)
    total    = extract_total(ocr_results)
    subtotal = extract_subtotal(ocr_results)
    items    = extract_items(ocr_results, total=total or 0.0, subtotal=subtotal)

    return {
        'vendor': vendor,
        'date':   date,
        'total':  total,
        'items':  items,
    }
