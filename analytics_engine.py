#!/usr/bin/env python3.13
import time
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime
from zoneinfo import ZoneInfo

# Native OKX REST endpoint
OKX_REST_HOST = "https://us.okx.com"
INSTRUMENT_ID = "BTC-USD"
BAR_TIMEFRAME = "15m"  # Tactical execution chart
MACRO_TIMEFRAME = "1H"  # Boss / Macro trend filter chart
LOCAL_TZ = ZoneInfo("America/New_York")

LAST_PROCESSED_TIME = None
LAST_PRINTED_CANDLE_TS = None  # Tracks the last unique candle printed to avoid spam

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

def fetch_native_candles(timeframe: str, limit: int = 250) -> pd.DataFrame:
    """Fetches raw OHLCV candles directly from OKX V5 REST API for any timeframe."""
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/candles"
        params = {
            "instId": INSTRUMENT_ID,
            "bar": timeframe,
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
        print(f"[ERROR] Failed to fetch REST candles for {timeframe}: {e}")
    return pd.DataFrame()

def evaluate_macro_boss() -> bool:
    """
    1H Macro Trend Filter (The Boss):
    Returns True only if the 1-hour macro trend is bullish:
    - Price > 200 EMA on the 1H chart
    - 50 EMA > 200 EMA on the 1H chart
    """
    df_1h = fetch_native_candles(timeframe=MACRO_TIMEFRAME, limit=250)
    if df_1h.empty or len(df_1h) < 200:
        return False  # Fail-safe lock if data is insufficient
    
    df_1h['ema_50'] = ta.ema(df_1h['close'], length=50)
    df_1h['ema_200'] = ta.ema(df_1h['close'], length=200)
    
    # Evaluate the latest closed 1H candle (-2) to avoid repainting
    last_1h = df_1h.iloc[-2]
    
    macro_bullish = (last_1h['close'] > last_1h['ema_200']) and (last_1h['ema_50'] > last_1h['ema_200'])
    return macro_bullish

def analyze_15m_setup():
    global LAST_PROCESSED_TIME, LAST_PRINTED_CANDLE_TS
    
    # 1. Fetch live ticker for the top header bar
    ticker = fetch_live_ticker()
    
    # 2. Fetch 15m candle history for tactical quantitative analysis (extended depth for 200 EMA)
    df = fetch_native_candles(timeframe=BAR_TIMEFRAME, limit=250)
    if df.empty or len(df) < 200:
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

    # Target the latest fully closed 15m candle (-2) to avoid repainting on live ticks
    last = df.iloc[-2]
    prev = df.iloc[-3]
    prev_prev = df.iloc[-4]

    current_candle_ts = last['timestamp']
    is_new_candle = current_candle_ts != LAST_PRINTED_CANDLE_TS

    # If it's not a new candle, skip printing entirely to keep the terminal clean
    if not is_new_candle:
        return

    LAST_PRINTED_CANDLE_TS = current_candle_ts

    # Convert UTC candle timestamp to local Georgia time (EDT)
    local_candle_time = last['timestamp'].tz_localize('UTC').astimezone(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')

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
    prev_prev_hist = prev_prev['macd_hist']

    # --- HIERARCHICAL GATING: THE 1H BOSS ---
    macro_approved = evaluate_macro_boss()

    # --- SYSTEMATIC QUANTITATIVE CONFLUENCE GATES ---
    gate_trend = (price > ema_200) and (ema_50 > ema_200)
    gate_momentum = (macd_hist > 0) and (macd_hist > prev_hist) and (prev_hist > prev_prev_hist)
    gate_volume = vol > (vol_ma * 1.4) if vol_ma > 0 else False
    
    bar_range = high - low
    close_location = (price - low) / bar_range if bar_range > 0 else 0
    gate_strength = close_location >= 0.60

    tactical_score = sum([gate_trend, gate_momentum, gate_volume, gate_strength])

    # --- RENDER TUI-STYLE LIVE HEADER BAR ---
    print("─" * 75)
    print(f" OXX TUI > {INSTRUMENT_ID} | Live Price: ${ticker['price']:,.1f} | High: ${ticker['high']:,.1f} | Low: ${ticker['low']:,.1f}")
    print("─" * 75)

    # --- TERMINAL SETUP CARD OUTPUT & FILE LOGGER ---
    if macro_approved and tactical_score == 4:
        flash_alert = "\a\a\a"
        card_text = (
            flash_alert +
            "\n" + "█" * 65 + "\n"
            f"  [ELITE HIERARCHICAL 4/4 SETUP] — {INSTRUMENT_ID} ({BAR_TIMEFRAME})\n"
            f" Candle Close Time : {local_candle_time} (EDT)\n"
            f" Candle Close Price: ${price:,.2f}\n"
            f" 1H Macro Gate     : APPROVED (Boss Filter Bullish)\n"
            f" Alignment Status  : 100% QUANTITATIVE LOCK (4/4)\n"
            "-" * 65 + "\n"
            f" • Structural Trend : BULLISH ALIGNED\n"
            f" • Momentum Persist : Hist {macd_hist:.2f} > {prev_hist:.2f} > {prev_prev_hist:.2f} (Accelerating)\n"
            f" • Relative Volume  : {vol:,.0f} vs 20MA {vol_ma:,.0f} (SURGE)\n"
            f" • Bar Close Strength: {close_location*100:.1f}% of range high\n"
            "█" * 65 + "\n"
        )
        print(card_text)
        with open("trade_signals_ledger.md", "a", encoding="utf-8") as f:
            f.write(card_text)

    elif tactical_score >= 3:
        card_text = (
            "\n" + "█" * 65 + "\n"
            f"  [15M QUANTITATIVE SETUP ({tactical_score}/4)] — {INSTRUMENT_ID} ({BAR_TIMEFRAME})\n"
            f" Candle Close Time : {local_candle_time} (EDT)\n"
            f" Candle Close Price: ${price:,.2f}\n"
            f" 1H Macro Gate     : {'APPROVED' if macro_approved else 'BLOCKED (Bearish 1H)'}\n"
            f" Confluence Score  : {tactical_score}/4 Vectors Aligned\n"
            "-" * 65 + "\n"
            f" • Structural Trend : {'BULLISH ALIGNED' if gate_trend else 'NEUTRAL/BEARISH'}\n"
            f" • Momentum Persist : Hist {macd_hist:.2f} (Persist Check: {gate_momentum})\n"
            f" • Relative Volume  : {vol:,.0f} vs 20MA {vol_ma:,.0f} ({'SURGE' if gate_volume else 'NORMAL'})\n"
            f" • Bar Close Strength: {close_location*100:.1f}% of range high\n"
            "█" * 65 + "\n"
        )
        print(card_text)
        with open("trade_signals_ledger.md", "a", encoding="utf-8") as f:
            f.write(card_text)
            
    else:
        macro_status = "BULL" if macro_approved else "BEAR/CHOP"
        print(f"[15M SCAN] Time: {local_candle_time} EDT | 1H Macro: {macro_status} | Close: ${price:,.2f} | MACD Hist: {macd_hist:.2f} | Score: {tactical_score}/4 (Monitoring)")
    print("\n")

if __name__ == "__main__":
    print(f"[*] Starting Clean Hierarchical OKX Analytics Engine for {INSTRUMENT_ID}...")
    print(f"[*] Output Mode: Prints strictly on new 15m candle closes. Running loop active...\n")
    try:
        while True:
            analyze_15m_setup()
            time.sleep(30)  # Checks every 30 seconds for the new candle boundary cleanly
    except KeyboardInterrupt:
        print("\n[*] Analytics engine gracefully stopped by user. Shutting down cleanly.")
