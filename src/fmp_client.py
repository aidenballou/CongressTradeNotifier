import os, requests
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

API_KEY = os.getenv("FMP_API_KEY")
BASE_URL = "https://financialmodelingprep.com"

def fetch_senate_trades():
    url = f"{BASE_URL}/stable/senate-latest?page=0&limit=10&apikey={API_KEY}"
    print(f"[Senate] Making request to: {url}")
    
    try:
        response = requests.get(url)
        print(f"[Senate] HTTP Status Code: {response.status_code}")
        print(f"[Senate] Response Headers: {dict(response.headers)}")
        
        if response.status_code != 200:
            print(f"[Senate] Error response: {response.text}")
            return []
        
        data = response.json()
        print(f"[Senate] Response type: {type(data)}")
        print(f"[Senate] Response content: {data}")
        
        if isinstance(data, list):
            print(f"[Senate] List length: {len(data)}")
            if data:
                print(f"[Senate] First item: {data[0]}")
            # Add source field to each trade
            for trade in data:
                trade['source'] = 'senate'
        else:
            print(f"[Senate] Not a list, keys: {data.keys() if isinstance(data, dict) else 'N/A'}")
        
        return data if isinstance(data, list) else []
        
    except Exception as e:
        print(f"[Senate] Exception: {e}")
        return []

def fetch_house_trades():
    url = f"{BASE_URL}/stable/house-latest?page=0&limit=10&apikey={API_KEY}"
    print(f"[House] Making request to: {url}")
    
    try:
        response = requests.get(url)
        print(f"[House] HTTP Status Code: {response.status_code}")
        print(f"[House] Response Headers: {dict(response.headers)}")
        
        if response.status_code != 200:
            print(f"[House] Error response: {response.text}")
            return []
        
        data = response.json()
        print(f"[House] Response type: {type(data)}")
        print(f"[House] Response content: {data}")
        
        if isinstance(data, list):
            print(f"[House] List length: {len(data)}")
            if data:
                print(f"[House] First item: {data[0]}")
            # Add source field to each trade
            for trade in data:
                trade['source'] = 'house'
        else:
            print(f"[House] Not a list, keys: {data.keys() if isinstance(data, dict) else 'N/A'}")
        
        return data if isinstance(data, list) else []
        
    except Exception as e:
        print(f"[House] Exception: {e}")
        return []

def main():
    new, _ = run_delta()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    # Only keep trades disclosed today
    trades_today = [t for t in new if t.get("disclosureDate") == today]
    if trades_today:
        send_summary(trades_today)
    else:
        print("No trades disclosed today.")