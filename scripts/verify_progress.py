
import requests
import time
import sys

BASE_URL = "http://127.0.0.1:8000"

def test_status_endpoint():
    print("Testing /api/status...")
    try:
        resp = requests.get(f"{BASE_URL}/api/status")
        if resp.status_code == 200:
            data = resp.json()
            print("Status response structure:")
            for key, val in data.items():
                print(f"  - {key}: {val.get('status')} (Progress: {val.get('progress')}%)")
            
            required_keys = ["scraper", "generator", "style_analyzer", "aggregator"]
            for k in required_keys:
                if k not in data:
                    print(f"FAILED: Missing key {k} in status response")
                    return False
            return True
        else:
            print(f"FAILED: Status endpoint returned {resp.status_code}")
            return False
    except Exception as e:
        print(f"FAILED: Request failed: {e}")
        return False

def test_trigger_endpoint(name, url, method="POST"):
    print(f"Testing {name} trigger ({url})...")
    try:
        if method == "POST":
            resp = requests.post(f"{BASE_URL}{url}")
        else:
            resp = requests.get(f"{BASE_URL}{url}")
            
        if resp.status_code == 200:
            print(f"SUCCESS: {name} triggered.")
            return True
        else:
            print(f"FAILED: {name} returned {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"FAILED: Request failed: {e}")
        return False

def main():
    if not test_status_endpoint():
        sys.exit(1)
        
    # We won't actually trigger heavy tasks as they might block or take long, 
    # but we can try to trigger the aggregation as it should be fast if no changes, 
    # or just rely on the fact that the endpoint exists.
    # Actually, let's trigger aggregation, it should be safe.
    
    if not test_trigger_endpoint("Aggregation", "/api/style/aggregate"):
        sys.exit(1)
        
    print("\nWaiting a bit to see if status updates...")
    time.sleep(2)
    test_status_endpoint()
    
    print("\nVerification Complete!")

if __name__ == "__main__":
    main()
