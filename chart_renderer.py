import requests
import plotext as plt
import logging
import datetime
import threading

# Global lock to prevent plotext state collisions during concurrent renders
chart_lock = threading.Lock()

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
    def _prepare_canvas(width: int, height: int):
        """Internal helper to clean and size the plotext matrix."""
        try:
            plt.clear_figure()
        except AttributeError:
            plt.clf()
        
        try:
            plt.clear_data()
            plt.clear_color()
        except Exception:
            pass
            
        plt.plotsize(width, height)
        plt.theme("dark")
        plt.canvas_color("black")
        plt.axes_color("black")
        plt.ticks_color("gold")

    @staticmethod
    def render_price_view(candle_data: dict, inst_id: str, bar: str, width: int, height: int) -> str:
        """Renders pure Price Action candlesticks."""
        with chart_lock:
            try:
                OKXChartEngine._prepare_canvas(width, height)
                plt.title(f"{inst_id} [{bar}] | Pure Price Action")
                
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
                    step = max(1, len(x_indexes) // 6)
                    plt.xticks(x_indexes[::step], [times[i] for i in range(0, len(times), step)])
                
                return plt.build()
            except Exception as e:
                return f"Price Render Error: {str(e)}"

    @staticmethod
    def render_trend_view(candle_data: dict, width: int, height: int, ema9: list, ema21: list) -> str:
        """Renders the EMA Trend Oscillator (Blue vs Red)."""
        with chart_lock:
            try:
                OKXChartEngine._prepare_canvas(width, height)
                plt.title("Trend: Blue (EMA-9) vs Red (EMA-21)")
                
                x_indexes = list(range(len(candle_data["time"])))
                if ema9:
                    plt.plot(x_indexes, ema9, color="blue")
                if ema21:
                    plt.plot(x_indexes, ema21, color="red")
                
                plt.xticks([], []) # Minimalist
                return plt.build()
            except Exception as e:
                return f"Trend Render Error: {str(e)}"

    @staticmethod
    def render_momentum_view(candle_data: dict, width: int, height: int, rsi: list) -> str:
        """Renders the RSI Momentum Oscillator."""
        with chart_lock:
            try:
                OKXChartEngine._prepare_canvas(width, height)
                plt.title("Momentum: RSI (14)")
                
                x_indexes = list(range(len(candle_data["time"])))
                if rsi:
                    plt.plot(x_indexes, rsi, color="gold")
                    plt.hline(70, color="red")
                    plt.hline(30, color="blue")
                    plt.ylim(0, 100)
                
                plt.xticks([], []) # Minimalist
                return plt.build()
            except Exception as e:
                return f"Momentum Render Error: {str(e)}"
