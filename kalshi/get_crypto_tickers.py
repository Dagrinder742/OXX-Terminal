# kalshi/get_crypto_tickers.py
from pathlib import Path
import requests
from auth import load_private_key_from_file, get_auth_headers

API_KEY_ID = "837934ae-214d-4a46-86ff-dbfb21619e49"
KEY_FILE_PATH = Path(__file__).resolve().parent / "main.txt"
BASE_URL = "https://external-api.kalshi.com"

def fetch_crypto_markets():
    private_key = load_private_key_from_file(str(KEY_FILE_PATH))
    path = "/trade-api/v2/markets"

    # Target series tickers for Bitcoin, Solana, and Hype
    target_series = ["KXBTC15M", "KXBTC", "KXSOL15M", "KXSOL", "KXHYPE15M", "KXHYPE"]

    headers = get_auth_headers(API_KEY_ID, private_key, "GET", path)

    for series in target_series:
        params = {
            "series_ticker": series,
            "status": "open",
            "limit": 5
        }
        response = requests.get(BASE_URL + path, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            markets = data.get("markets", [])
            print(f"\n--- Series: {series} (Active Markets: {len(markets)}) ---")
            for m in markets:
                print(f"  Ticker: {m.get('ticker')} | Title: {m.get('title')}")
        else:
            print(f"Error for {series}: {response.status_code} - {response.text}")

if __name__ == "__main__":
    fetch_crypto_markets()
