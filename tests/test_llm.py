from src.extractor_llm import ReceiptLLM
import json
from unittest.mock import MagicMock, patch

# Mock response from Ollama
mock_response = {
    'message': {
        'content': '''
        ```json
        {
            "vendor": "SuperMart",
            "date": "2023-10-27",
            "total": 25.50,
            "items": [
                {"name": "Milk", "qty": 1, "price": 5.50},
                {"name": "Bread", "qty": 2, "price": 10.00}
            ]
        }
        ```
        '''
    }
}

# Patch ollama.chat to avoid actual API call
with patch('ollama.chat', return_value=mock_response):
    llm = ReceiptLLM()
    result = llm.extract("Sample OCR text")
    
    print("Extracted Data:", result)
    
    assert result['vendor'] == "SuperMart"
    assert result['total'] == 25.50
    assert len(result['items']) == 2
    
    print("Verification passed!")
