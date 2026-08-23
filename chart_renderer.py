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
        """Renders an ASCII candlestick chart with extremely defensive attribute checks for Plotext 6.0.0 compatibility."""
        if not candle_data.get("success"):
            return "Unable to load candlestick telemetry."

        try:
            # Step 1: Clear Figure (Handling v6 vs v5)
            if hasattr(plt, "clear_figure"):
                plt.clear_figure()
            elif hasattr(plt, "clf"):
                plt.clf()
            
            # Step 2: Sizing
            if hasattr(plt, "plot_size"):
                plt.plot_size(width, height)
            elif hasattr(plt, "plotsize"):
                plt.plotsize(width, height)

            # Step 3: Theme
            if hasattr(plt, "theme"):
                plt.theme("dark")

            times = candle_data["time"]
            x_indexes = list(range(len(times)))
            
            # Step 4: Plotting (Checking for ANY available method)
            if hasattr(plt, "candlestick"):
                prices = {
                    "open": candle_data["open"],
                    "high": candle_data["high"],
                    "low": candle_data["low"],
                    "close": candle_data["close"]
                }
                plt.candlestick(x_indexes, prices)
            elif hasattr(plt, "plot"):
                plt.plot(x_indexes, candle_data["close"])
            elif hasattr(plt, "scatter"):
                plt.scatter(x_indexes, candle_data["close"])
            else:
                # If everything fails, list what IS available so we can debug
                available = [a for a in dir(plt) if not a.startswith("_")]
                return f"Error: No plot methods found. Available attributes: {available[:10]}"

            # Step 5: Metadata
            if hasattr(plt, "title"):
                plt.title(f"{inst_id} [{bar}]")
            
            # Step 6: Rendering
            if hasattr(plt, "build"):
                return str(plt.build())
            
            return "Error: plotext.build() not found. (Plotext v5.0+ required)"

        except Exception as e:
            logging.error(f"Termux Render Crash: {str(e)}")
            return f"Render Crash: {str(e)}"
