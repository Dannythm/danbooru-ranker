
import requests
import json

BASE_URL = "http://127.0.0.1:8001"

def verify():
    print("Verifying API endpoints...")
    
    # 1. Get Categories
    try:
        resp = requests.get(f"{BASE_URL}/api/categories")
        if resp.status_code == 200:
            cats = resp.json()
            print(f"Categories found: {len(cats)}")
            print(f"Sample categories: {cats[:5]}")
        else:
            print(f"Error fetching categories: {resp.status_code}")
    except Exception as e:
        print(f"Request failed: {e}")

    # 2. Get Authors with Style
    try:
        resp = requests.get(f"{BASE_URL}/api/authors?limit=5")
        if resp.status_code == 200:
            authors = resp.json()
            print(f"Fetched {len(authors)} authors.")
            for a in authors:
                print(f"  - {a['name']}: {a.get('style_category', 'N/A')}")
        else:
            print(f"Error fetching authors: {resp.status_code}")
    except Exception as e:
        print(f"Request failed: {e}")

    # 3. Filter by Category
    if cats:
        cat = cats[0]
        print(f"Filtering by category: {cat}")
        try:
            resp = requests.get(f"{BASE_URL}/api/authors?category={cat}&limit=5")
            if resp.status_code == 200:
                authors = resp.json()
                print(f"Fetched {len(authors)} authors in category '{cat}'.")
                for a in authors:
                    print(f"  - {a['name']}: {a.get('style_category', 'N/A')}")
            else:
                print(f"Error filtering authors: {resp.status_code}")
        except Exception as e:
            print(f"Request failed: {e}")

if __name__ == "__main__":
    verify()
