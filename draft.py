import pandas as pd
import requests
from ta.momentum import RSIIndicator
from ta.trend import MACD

OKX_REST_HOST = "https://us.okx.com"

def get_price_data(symbol, time_frame="1H", limit=100):
    """Fetches clean OHLCV candles from the official OKX V5 API."""
    url = f"{OKX_REST_HOST}/api/v5/market/candles"
    params = {"instId": symbol, "bar": time_frame, "limit": limit}

    response = requests.get(url, params=params, timeout=5)
    if response.status_code == 200:
        res_json = response.json()
        if res_json.get("code") == "0":
            raw_data = res_json.get("data", [])
            # OKX returns data as: [ts, o, h, l, c, vol, volUsd, ...]
            # We map it into a proper DataFrame for technical analysis
            df = pd.DataFrame(raw_data, columns=[
                "timestamp", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"
            ])
            # Convert price columns to numeric floats
            for col in ["open", "high", "low", "close", "vol"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            # OKX returns latest first; reverse it so chronological order is oldest -> newest for TA
            return df.iloc[::-1].reset_index(drop=True)

    return pd.DataFrame()

def calculate_macd(close_series):
    """Calculate MACD using the proper 'ta' library trend module."""
    macd_indicator = MACD(close=close_series, window_fast=12, window_slow=26, window_sign=9)
    return {
        'MACD': macd_indicator.macd().iloc[-1],
        'MACD_Signal': macd_indicator.macd_signal().iloc[-1],
        'MACD_Diff': macd_indicator.macd_diff().iloc[-1]
    }

def calculate_rsi(close_series, period=14):
    """Calculate RSI using the proper 'ta' library momentum module."""
    rsi_indicator = RSIIndicator(close=close_series, window=period)
    return {
        'RSI': rsi_indicator.rsi().iloc[-1]
    }

def analyze_data(symbol, time_frame="1H"):
    """Orchestrates fetching live data and computing structural indicators."""
    df = get_price_data(symbol, time_frame)
    if df.empty:
        return {"error": f"Could not retrieve data for {symbol}"}

    # Ensure chronological order
    close_prices = df['close']

    macd_result = calculate_macd(close_prices)
    rsi_result = calculate_rsi(close_prices)

    return {
        "symbol": symbol,
        "time_frame": time_frame,
        "latest_close": close_prices.iloc[-1],
        "MACD_Metrics": macd_result,
        "RSI_Metrics": rsi_result
    }

def predict_trend(symbol, time_frame="1H"):
    """Quantitative research layer assessing market state without trade execution."""
    results = analyze_data(symbol, time_frame)
    return results

