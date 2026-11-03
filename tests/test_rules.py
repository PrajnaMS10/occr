from src.extractor_rules import extract_receipt_data

# Mock OCR results
mock_results = [
    {'text': 'SENG SHIONG SUPERMARKET', 'confidence': 0.98, 'bbox': [100, 50, 400, 80], 'center_y': 65},
    {'text': '20 Jalan Afidi', 'confidence': 0.95, 'bbox': [100, 90, 400, 110], 'center_y': 100},
    {'text': 'Date: 01/02/2026', 'confidence': 0.99, 'bbox': [100, 150, 300, 170], 'center_y': 160},
    {'text': 'APPLES RED', 'confidence': 0.90, 'bbox': [50, 200, 200, 220], 'center_y': 210},
    {'text': '5.00', 'confidence': 0.95, 'bbox': [400, 200, 450, 220], 'center_y': 210},
    {'text': 'MILK 2L', 'confidence': 0.90, 'bbox': [50, 240, 200, 260], 'center_y': 250},
    {'text': '6.50', 'confidence': 0.95, 'bbox': [400, 240, 450, 260], 'center_y': 250},
    {'text': 'TOTAL', 'confidence': 0.98, 'bbox': [50, 300, 100, 320], 'center_y': 310},
    {'text': '11.50', 'confidence': 0.98, 'bbox': [400, 300, 450, 320], 'center_y': 310}
]

data = extract_receipt_data(mock_results)
print(data)

assert data['vendor'] == 'SENG SHIONG SUPERMARKET'
# The extractor documents month/day/year for slash-separated US receipts.
assert data['date'] == '2026-01-02'
assert data['total'] == 11.50
assert len(data['items']) == 2
assert data['items'][0]['item_name'] == 'APPLES RED'
assert data['items'][0]['price'] == 5.00
assert data['items'][1]['item_name'] == 'MILK 2L'
assert data['items'][1]['price'] == 6.50

print("Verification passed!")
