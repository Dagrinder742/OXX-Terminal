# kalshi/get_crypto_markets.py
from pathlib import Path
import requests
from auth import load_private_key_from_file, get_auth_headers

API_KEY_ID = "837934ae-214d-4a46-86ff-dbfb21619e49"
KEY_FILE_PATH = Path(__file__).resolve().parent / "main.txt"
BASE_URL = "https://external-api.kalshi.com"

def get_crypto_series_and_markets():
    private_key = load_private_key_from_file(str(KEY_FILE_PATH))
    path = "/trade-api/v2/series"

    headers = get_auth_headers(API_KEY_ID, private_key, "GET", path)
    response = requests.get(BASE_URL + path, headers=headers)

    if response.status_code == 200:
        data = response.json()
        series_list = data.get("series", [])
        print(f"Found {len(series_list)} total series. Searching for crypto...")

        for s in series_list:
            ticker = s.get("ticker", "").upper()
            title = s.get("title", "").upper()
            if any(term in ticker or term in title for term in ["BTC", "BITCOIN", "ETH", "SOL", "SOLANA", "HYPE", "CRYPTO"]):
                print(f"Series Ticker: {s.get('ticker')} | Title: {s.get('title')}")
    else:
        print(f"Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    get_crypto_series_and_markets()
