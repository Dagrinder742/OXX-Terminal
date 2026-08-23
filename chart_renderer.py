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
        """Renders an ASCII candlestick chart string safely."""
        if not candle_data.get("success"):
            return "Unable to load candlestick telemetry."

        try:
            plt.clf()
            plt.plotsize(width, height)
            plt.theme("dark")

            times = candle_data["time"]
            x_indexes = list(range(len(times)))
            
            prices = {
                "Open": candle_data["open"],
                "High": candle_data["high"],
                "Low": candle_data["low"],
                "Close": candle_data["close"]
            }

            plt.candlestick(x_indexes, prices)
            
            if x_indexes:
                step = max(1, len(x_indexes) // 5)
                plt.xticks(x_indexes[::step], times[::step])

            plt.title(f"{inst_id} [{bar}]")
            return plt.build()
        except Exception as e:
            logging.exception("Error building plotext ASCII chart")
            return f"Error rendering chart: {str(e)}"
