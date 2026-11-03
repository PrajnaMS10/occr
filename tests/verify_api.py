import requests
from pathlib import Path
import time

API_URL = "http://localhost:8000"
IMAGE_PATH = Path("images/receipt-ocr-original.jpg")

def test_health():
    try:
        r = requests.get(f"{API_URL}/health")
        print(f"Health: {r.status_code} - {r.json()}")
    except Exception as e:
        print(f"Health Check Failed: {e}")

def test_analyze_rules():
    print("\nTesting /analyze/rules ...")
    start = time.time()
    try:
        with open(IMAGE_PATH, "rb") as f:
            files = {"file": f}
            r = requests.post(f"{API_URL}/analyze/rules", files=files)
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                print(f"Response: {r.json()}")
            else:
                print(f"Error: {r.text}")
    except Exception as e:
        print(f"Rules Test Failed: {e}")
    print(f"Time taken: {time.time() - start:.2f}s")

def test_analyze_llm():
    print("\nTesting /analyze/llm ...")
    start = time.time()
    try:
        with open(IMAGE_PATH, "rb") as f:
            files = {"file": f}
            # verify=False for local
            r = requests.post(f"{API_URL}/analyze/llm", files=files)
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                print(f"Response: {r.json()}")
            else:
                print(f"Error: {r.text}")
    except Exception as e:
        print(f"LLM Test Failed: {e}")
    print(f"Time taken: {time.time() - start:.2f}s")

if __name__ == "__main__":
    test_health()
    test_analyze_rules()
    # Uncomment to test LLM
    test_analyze_llm()
