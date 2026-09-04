import time
import ccxt
import pandas as pd
import pandas_ta as ta

# Initialize OKX exchange via CCXT
exchange = ccxt.okx()

symbol = 'BTC/USDT'  # OKX unified symbol (or BTC/USD depending on market type)
timeframe = '1h'  # Candle interval (e.g., 1m, 1h, 4h)


def fetch_and_analyze():
  # 1. Fetch OHLCV candles
  ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
  df = pd.DataFrame(
      ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
  )
  df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

  # 2. Calculate Indicators using Pandas-TA
  df['ema_50'] = ta.ema(df['close'], length=50)
  df['rsi'] = ta.rsi(df['close'], length=14)
  df['vol_ma'] = ta.sma(df['volume'], length=20)

  # 3. Evaluate latest closed candle
  last = df.iloc[-2]  # -1 is current incomplete candle, -2 is last closed

  is_bullish_trend = last['close'] > last['ema_50']
  is_rsi_favorable = 40 <= last['rsi'] <= 60  # Example pullback zone
  is_volume_spike = last['volume'] > (last['vol_ma'] * 1.5)

  if is_bullish_trend and is_rsi_favorable and is_volume_spike:
    print(
        f'[ALERT] Good Entry Setup Logged at {last["timestamp"]} | Price:'
        f' {last["close"]} | RSI: {last["rsi"]:.2f}'
    )
  else:
    print(
        f'[INFO] Scanning... No entry match at {last["timestamp"]} (RSI:'
        f' {last["rsi"]:.2f})'
    )


# Run loop every minute or matching your timeframe
while True:
  try:
    fetch_and_analyze()
    time.sleep(60)  # Check every 60 seconds
  except Exception as e:
    print(f'Error encountered: {e}')
    time.sleep(10)
