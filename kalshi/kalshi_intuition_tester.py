"""
KALSHI MULTI-CHECKPOINT 15M TRACKER
Tracks and logs price, odds, and volume at:
- 15m remaining (candle start)
- 7m remaining (midpoint check)
- 5m remaining (urgency check)
- 3m remaining (final decision window)
"""

import time
import requests
from datetime import datetime, timezone

KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"

def get_active_btc_market():
    url = f"{KALSHI_API_BASE}/markets"
    params = {"status": "open", "limit": 50}
    try:
        response = requests.get(url, params=params, timeout=10)
        markets = response.json().get("markets", [])
        btc_markets = [m for m in markets if "BTC" in m.get("ticker", "").upper() and ("15M" in m.get("ticker", "").upper() or "15" in m.get("title", ""))]
        return btc_markets[0] if btc_markets else (markets[0] if markets else None)
    except Exception as e:
        print(f"API Error: {e}")
        return None

def run_checkpoint_tracker():
    print("[*] Starting Kalshi Multi-Checkpoint Tracker...")
    current_ticker = None
    triggered_checkpoints = set() # Keeps track so we only log each checkpoint once per candle

    while True:
        market = get_active_btc_market()
        if not market:
            time.sleep(10)
            continue

        ticker = market.get("ticker")
        
        # Reset checkpoints if a new 15M market ticker rolls over
        if ticker != current_ticker:
            current_ticker = ticker
            triggered_checkpoints.clear()
            print(f"\n[+] New Active Ticker Detected: {ticker} - {market.get('title')}")

        close_time_str = market.get("close_time")
        if not close_time_str:
            time.sleep(5)
            continue

        close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        time_remaining_seconds = int((close_dt - now_dt).total_seconds())
        minutes_remaining = time_remaining_seconds // 60

        # Pull live pricing/odds
        yes_price = market.get("yes_bid", 50) or 50
        no_price = market.get("no_bid", 50) or 50
        volume = market.get("volume", 0) or 0
        
        total_cost = yes_price + no_price
        up_pct = round((yes_price / total_cost) * 100, 1) if total_cost > 0 else 50.0
        down_pct = round((no_price / total_cost) * 100, 1) if total_cost > 0 else 50.0

        # DEFINE YOUR CHECKPOINTS (in seconds remaining)
        # 15 min = ~900s, 7 min = 420s, 5 min = 300s, 3 min = 180s
        checkpoints = {
            900: "15-Min Start",
            420: "7-Min Midpoint",
            300: "5-Min Urgency",
            180: "3-Min Final Call"
        }

        for target_sec, label in checkpoints.items():
            # Trigger if we are within a 3-second window of the target checkpoint and haven't logged it yet
            if abs(time_remaining_seconds - target_sec) <= 3 and label not in triggered_checkpoints:
                triggered_checkpoints.add(label)
                print(f"\n========================================")
                print(f"  CHECKPOINT REACHED: {label}")
                print(f"  Ticker: {ticker}")
                print(f"  Time Left: {minutes_remaining}m ({time_remaining_seconds}s)")
                print(f"  Odds -> Up: {up_pct}% | Down: {down_pct}%")
                print(f"  Volume: ${volume:,}")
                print(f"========================================")

        # Poll every 3 seconds to catch the second-exact window
        time.sleep(3)

if __name__ == "__main__":
    run_checkpoint_tracker()

