#!/usr/bin/env python3.13
import time
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime
from zoneinfo import ZoneInfo

# Native OKX REST endpoint (matching your api_client.py pattern)
OKX_REST_HOST = "https://us.okx.com"
INSTRUMENT_ID = "BTC-USD"
BAR_TIMEFRAME = "15m"  # Hardcoded to your 15m execution chart
LOCAL_TZ = ZoneInfo("America/New_York")

LAST_PROCESSED_TIME = None

def fetch_live_ticker() -> dict:
    """Fetches real-time ticker stats for the live header bar."""
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/ticker"
        params = {"instId": INSTRUMENT_ID}
        response = requests.get(url, params=params, timeout=3)
        if response.status_code == 200:
            data = response.json().get("data", [])
            if data:
                t = data[0]
                return {
                    "price": float(t.get("last", 0)),
                    "high": float(t.get("high24h", 0)),
                    "low": float(t.get("low24h", 0)),
                    "vol": float(t.get("vol24h", 0))
                }
    except Exception:
        pass
    return {"price": 0.0, "high": 0.0, "low": 0.0, "vol": 0.0}

def fetch_native_candles(limit: int = 250) -> pd.DataFrame:
    """Fetches raw 15m OHLCV candles directly from OKX V5 REST API."""
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/candles"
        params = {
            "instId": INSTRUMENT_ID,
            "bar": BAR_TIMEFRAME,
            "limit": limit
        }
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("code") == "0":
                raw_data = res_json.get("data", [])
                if not raw_data:
                    return pd.DataFrame()
                
                # OKX returns data newest-first. Reverse to chronological order (oldest -> newest)
                raw_data.reverse()
                
                # OKX format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
                df = pd.DataFrame(raw_data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume', 'volCcy', 'volCcyQuote', 'confirm'
                ])
                
                # Type conversions
                df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                    
                return df
    except Exception as e:
        print(f"[ERROR] Failed to fetch REST candles: {e}")
    return pd.DataFrame()

def analyze_15m_setup():
    global LAST_PROCESSED_TIME
    
    # 1. Fetch live ticker for the top header bar[cite: 3]
    ticker = fetch_live_ticker()
    
    # 2. Fetch candle history for quantitative analysis (extended depth for 200 EMA)
    df = fetch_native_candles(limit=250)
    if df.empty or len(df) < 200:
        print("[WARNING] Insufficient candle data returned.")
        return

    # --- QUANTITATIVE TECHNICAL INDICATOR SUITE ---
    df['ema_50'] = ta.ema(df['close'], length=50)
    df['ema_200'] = ta.ema(df['close'], length=200)
    
    # MACD for precise momentum acceleration tracking
    macd_df = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['macd_hist'] = macd_df['MACDh_12_26_9']
    
    # Volume Moving Average
    df['vol_ma'] = ta.sma(df['volume'], length=20)
    
    # Optional supplementary RSI reference
    df['rsi'] = ta.rsi(df['close'], length=14)

    # Target the latest fully closed 15m candle (-2) to avoid repainting on live ticks[cite: 3]
    last = df.iloc[-2]
    prev = df.iloc[-3]

    # Convert UTC candle timestamp to local Georgia time (EDT)[cite: 3]
    local_candle_time = last['timestamp'].tz_localize('UTC').astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')

    # Prevent duplicate prints on the same 15m candle boundary[cite: 3]
    is_new_candle = last['timestamp'] != LAST_PROCESSED_TIME
    if is_new_candle:
        LAST_PROCESSED_TIME = last['timestamp']

    price = last['close']
    high = last['high']
    low = last['low']
    ema_50 = last['ema_50']
    ema_200 = last['ema_200']
    rsi = last['rsi']
    vol = last['volume']
    vol_ma = last['vol_ma']
    macd_hist = last['macd_hist']
    prev_hist = prev['macd_hist']

    # --- SYSTEMATIC QUANTITATIVE CONFLUENCE GATES ---
    # 1. Structural Trend: Price and Fast EMA both above macro baseline
    gate_trend = (price > ema_200) and (ema_50 > ema_200)
    
    # 2. Momentum Acceleration: MACD histogram is positive and expanding upward
    gate_momentum = (macd_hist > 0) and (macd_hist > prev_hist)
    
    # 3. Institutional Volume: Volume exceeds 1.4x of the 20-period average
    gate_volume = vol > (vol_ma * 1.4) if vol_ma > 0 else False
    
    # 4. Bar Close Strength: Candle closed in the upper 60% of its total range (No upper wick distribution traps)
    bar_range = high - low
    close_location = (price - low) / bar_range if bar_range > 0 else 0
    gate_strength = close_location >= 0.60

    score = sum([gate_trend, gate_momentum, gate_volume, gate_strength])

    # --- RENDER TUI-STYLE LIVE HEADER BAR ---
    print("─" * 75)
    print(f" OXX TUI > {INSTRUMENT_ID} | Live Price: ${ticker['price']:,.1f} | High: ${ticker['high']:,.1f} | Low: ${ticker['low']:,.1f}")
    print("─" * 75)

    # --- TERMINAL SETUP CARD OUTPUT & FILE LOGGER ---
    if is_new_candle and score == 4:
        # Trigger terminal visual bell / screen flash sequence (\a) + max alert card
        flash_alert = "\a\a\a"
        card_text = (
            flash_alert +
            "\n" + "█" * 65 + "\n"
            f"  [MAX CONFLUENCE 4/4 SETUP] — {INSTRUMENT_ID} ({BAR_TIMEFRAME})\n"
            f" Candle Close Time : {local_candle_time} (EDT)\n"
            f" Candle Close Price: ${price:,.2f}\n"
            f" Alignment Status  : 100% QUANTITATIVE LOCK (4/4)\n"
            "-" * 65 + "\n"
            f" • Structural Trend : BULLISH ALIGNED\n"
            f" • MACD Acceleration: Hist {macd_hist:.2f} (Expanding Fast)\n"
            f" • Relative Volume  : {vol:,.0f} vs 20MA {vol_ma:,.0f} (SURGE)\n"
            f" • Bar Close Strength: {close_location*100:.1f}% of range high\n"
            "█" * 65 + "\n"
        )
        print(card_text)
        with open("trade_signals_ledger.md", "a", encoding="utf-8") as f:
            f.write(card_text)

    elif is_new_candle and score == 3:
        card_text = (
            "\n" + "█" * 65 + "\n"
            f"  [15M QUANTITATIVE SETUP (3/4)] — {INSTRUMENT_ID} ({BAR_TIMEFRAME})\n"
            f" Candle Close Time : {local_candle_time} (EDT)\n"
            f" Candle Close Price: ${price:,.2f}\n"
            f" Confluence Score  : {score}/4 Vectors Aligned\n"
            "-" * 65 + "\n"
            f" • Structural Trend : {'BULLISH ALIGNED' if gate_trend else 'NEUTRAL/BEARISH'}\n"
            f" • MACD Acceleration: Hist {macd_hist:.2f} (Expanding)\n"
            f" • Relative Volume  : {vol:,.0f} vs 20MA {vol_ma:,.0f} ({'SURGE' if gate_volume else 'NORMAL'})\n"
            f" • Bar Close Strength: {close_location*100:.1f}% of range high\n"
            "█" * 65 + "\n"
        )
        print(card_text)
        with open("trade_signals_ledger.md", "a", encoding="utf-8") as f: #[cite: 3]
            f.write(card_text)
            
    else:
        print(f"[15M SCAN] Time: {local_candle_time} EDT | Close: ${price:,.2f} | MACD Hist: {macd_hist:.2f} | Score: {score}/4 (Monitoring)")
    print("\n")

if __name__ == "__main__":
    print(f"[*] Starting Quantitative Native 15m OKX Analytics Engine for {INSTRUMENT_ID}...\n")
    try:
        while True:
            analyze_15m_setup()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[*] Analytics engine gracefully stopped by user. Shutting down cleanly.")
