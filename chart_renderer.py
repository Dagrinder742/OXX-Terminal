import requests
import plotext as plt
import logging
import datetime

class OKXChartEngine:
    """Fetches historical OHLCV candles from OKX REST API and renders terminal-grade ASCII charts."""

    BASE_URL = "https://us.okx.com"

    @classmethod
    def fetch_candles(cls, inst_id: str = "BTC-USD", bar: str = "15m", limit: int = 40) -> dict:
        endpoint = f"{cls.BASE_URL}/api/v5/market/candles"
        params = {"instId": inst_id, "bar": bar, "limit": limit}

        try:
            response = requests.get(endpoint, params=params, timeout=5)
            data = response.json()
            if data.get("code") == "0":
                raw_candles = data.get("data", [])
                raw_candles.reverse()  # Chronological order

                timestamps = []
                opens = []
                highs = []
                lows = []
                closes = []

                for c in raw_candles:
                    dt = datetime.datetime.fromtimestamp(int(c[0]) / 1000.0)
                    timestamps.append(dt.strftime("%H:%M" if bar in ["1m", "5m", "15m", "1H"] else "%m-%d"))
                    opens.append(float(c[1]))
                    highs.append(float(c[2]))
                    lows.append(float(c[3]))
                    closes.append(float(c[4]))

                return {
                    "success": True,
                    "time": timestamps,
                    "open": opens,
                    "high": highs,
                    "low": lows,
                    "close": closes
                }
            else:
                logging.error(f"Failed to fetch candles: {data.get('msg')}")
                return {"success": False, "msg": data.get('msg')}
        except Exception as e:
            logging.exception("Exception during candle fetch")
            return {"success": False, "msg": str(e)}

    @staticmethod
    def render_ascii_chart(candle_data: dict, inst_id: str, bar: str, width: int = 120, height: int = 16) -> str:
        """Renders an ASCII candlestick chart for Plotext v6.0.0+ using the new Object-Oriented 'figure' API."""
        if not candle_data.get("success"):
            return "Unable to load candlestick telemetry."

        try:
            # In Plotext v6, plotting methods have moved inside the 'figure' object/module
            # We determine the source (either top-level or inside 'figure')
            source = plt
            if hasattr(plt, "figure") and not hasattr(plt, "candlestick"):
                # If 'figure' exists but 'candlestick' doesn't, we are in the new OO API
                source = plt.figure

            # Clear
            if hasattr(source, "clear_figure"):
                source.clear_figure()
            elif hasattr(source, "clf"):
                source.clf()
            
            # Sizing
            if hasattr(source, "plot_size"):
                source.plot_size(width, height)
            elif hasattr(source, "plotsize"):
                source.plotsize(width, height)

            # Theme
            if hasattr(source, "theme"):
                source.theme("dark")

            times = candle_data["time"]
            x_indexes = list(range(len(times)))
            
            # Plot
            if hasattr(source, "candlestick"):
                prices = {
                    "open": candle_data["open"],
                    "high": candle_data["high"],
                    "low": candle_data["low"],
                    "close": candle_data["close"]
                }
                source.candlestick(x_indexes, prices)
            elif hasattr(source, "plot"):
                source.plot(x_indexes, candle_data["close"])
            else:
                # Still failing? Let's check attributes of source
                # Use str() to avoid potential issues with list comprehension in TUI context
                return f"Error: v6 API mismatch. Source attrs: {str(dir(source))[:60]}"

            if hasattr(source, "title"):
                source.title(f"{inst_id} [{bar}]")
            
            # Render
            if hasattr(source, "build"):
                return str(source.build())
            
            return "Error: .build() missing on source."

        except Exception as e:
            logging.error(f"Plotext v6 Render Crash: {str(e)}")
            return f"V6 Render Crash: {str(e)}"
