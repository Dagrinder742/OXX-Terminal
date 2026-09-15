import time
from datetime import datetime, timezone
import requests
import websocket
import json
import threading

# Kalshi API endpoints
KALSHI_REST_API = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_API = "wss://api.elections.kalshi.com/trade-api/ws/v2"

SERIES_TICKER = "KXBTC15M"

def fetch_active_kxbtc_markets():
    """Fetches open 15-minute Bitcoin markets from Kalshi REST API."""
    url = f"{KALSHI_REST_API}/markets"
    params = {
        "series_ticker": SERIES_TICKER,
        "status": "open"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("markets", [])
    except requests.exceptions.RequestException as e:
        print(f"[API Error] Failed to fetch REST data: {e}")
        return []

def evaluate_market_math(market):
    """
    Applies the custom algorithm:
    - Checks if time remaining in the 15M window is < 5 minutes.
    - Checks if probability/price is >= 70% or <= 30% (0.70 / 0.30).
    """
    # Parse expiration time
    close_time_str = market.get("close_time")
    if not close_time_str:
        return None

    close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    
    time_remaining_minutes = (close_time - now).total_seconds() / 60.0
    
    # Only evaluate active windows with less than 5 minutes remaining
    if not (0 < time_remaining_minutes < 5.0):
        return None

    # Kalshi order book prices are typically provided in cents (0 to 100) or decimal probabilities
    yes_ask = market.get("yes_ask_dollars") or (market.get("yes_ask", 50) / 100.0)
    no_ask = market.get("no_ask_dollars") or (market.get("no_ask", 50) / 100.0)
    
    # Fallback to last price if asks aren't populated
    last_price = market.get("last_price_dollars") or 0.50

    # Evaluate 70% threshold conditions (0.70+ or <= 0.30)
    signal = None
    execution_price = 0.0

    if yes_ask >= 0.70:
        signal = "EXECUTE_BUY_YES (UP)"
        execution_price = yes_ask
    elif yes_ask <= 0.30:
        signal = "EXECUTE_BUY_NO (DOWN)"
        execution_price = no_ask
    elif no_ask >= 0.70:
        signal = "EXECUTE_BUY_NO (DOWN)"
        execution_price = no_ask

    if signal:
        return {
            "ticker": market.get("ticker"),
            "title": market.get("title"),
            "time_remaining_min": round(time_remaining_minutes, 2),
            "execution_direction": signal,
            "entry_price": execution_price,
            "target_price": market.get("floor_strike") or market.get("target_price", "N/A")
        }
    
    return None

def print_projection_card(card_data):
    """Prints a stylized terminal projection card for valid trade setups."""
    print("\n" + "="*54)
    print(" 📊 KALSHI KXBTC 15M - PROJECTION CARD ".center(54, "="))
    print("="*54)
    print(f" • Ticker ID        : {card_data['ticker']}")
    print(f" • Market Question  : {card_data['title']}")
    print(f" • Time Window Left : {card_data['time_remaining_min']} minutes")
    print(f" • Target / Strike  : ${card_data['target_price']}")
    print(f" • Entry Price      : ${card_data['entry_price']:.2f}")
    print(f" • Execution Signal : {card_data['execution_direction']}")
    print("="*54)
    print(" [ACTION STATUS]: CONDITIONS MET. READY FOR ROUTING.\n")

def run_analytics_loop():
    print(f"[*] Scanning {SERIES_TICKER} markets across quarter-hour cycles (:00, :15, :30, :45)...")
    markets = fetch_active_kxbtc_markets()
    
    if not markets:
        print("[*] No active open markets found for this cycle slice.")
        return

    for market in markets:
        result = evaluate_market_math(market)
        if result:
            print_projection_card(result)

# --- WebSocket Event Handlers for Real-Time Telemetry ---
def on_message(ws, message):
    data = json.loads(message)
    # Handle live order book or ticker delta updates here
    # Trigger lightweight re-evaluation when tick events arrive
    if data.get("type") == "orderbook_delta":
        run_analytics_loop()

def on_error(ws, error):
    print(f"[WebSocket Error]: {error}")

def on_close(ws, close_status_code, close_msg):
    print("[*] WebSocket connection closed. Reconnecting...")

def on_open(ws):
    print("[*] WebSocket successfully connected to Kalshi stream.")
    # Subscribe to KXBTC15M channel if required by schema
    sub_payload = {
        "id": 1,
        "cmd": "subscribe",
        "params": {"channels": [f"ticker:{SERIES_TICKER}"]}
    }
    ws.send(json.dumps(sub_payload))

def start_websocket():
    ws = websocket.WebSocketApp(
        KALSHI_WS_API,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()

if __name__ == "__main__":
    # Start WebSocket listener in a background thread for real-time telemetry updates
    ws_thread = threading.Thread(target=start_websocket, daemon=True)
    ws_thread.start()

    # Main polling and evaluation loop running continuously
    try:
        while True:
            run_analytics_loop()
            time.sleep(15)  # Poll REST endpoint every 15 seconds to stay aligned with cycle slices
    except KeyboardInterrupt:
        print("\n[*] Script terminated by user. Shutting down cleanly.")

