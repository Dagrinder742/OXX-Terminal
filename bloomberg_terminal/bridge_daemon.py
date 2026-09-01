import asyncio
import json
import logging
import requests
import websockets
from typing import Callable, Optional, List, Dict, Any

# Primary public WebSocket endpoint for OKX market feeds
OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OKX_Client")

class OKXPublicClient:
    def __init__(self, instrument_id: str = "BTC-USD", callback: Optional[Callable[[str, list], Any]] = None, watchlist: List[str] = None):
        self.instrument_id = instrument_id
        self.watchlist = watchlist or []
        self.uri = OKX_WS_PUBLIC
        self.callback = callback  # Callback function to push data packets back to the TUI app

    def fetch_recent_trades(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetches a one-time REST snapshot of recent trades for instant UI hydration."""
        try:
            url = f"https://www.okx.com/api/v5/market/trades?instId={self.instrument_id}&limit={limit}"
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                data = response.json().get("data", [])
                trades = []
                for trade in data:
                    trades.append({
                        "price": float(trade.get("px", 0)),
                        "size": float(trade.get("sz", 0)),
                        "side": trade.get("side", "buy")
                    })
                return trades
        except Exception as e:
            logger.warning(f"Failed to fetch initial trade REST snapshot: {e}", exc_info=True)
        return []

    async def connect_market_streams(self):
        """Connects to the OKX public WebSocket and subscribes to tickers, order book, and trades."""
        while True:
            try:
                logger.info(f"Connecting to OKX WebSocket at {self.uri}...")
                async with websockets.connect(self.uri) as websocket:

                    # Build subscription arguments for tickers (Main + Watchlist)
                    ticker_args = [{"channel": "tickers", "instId": self.instrument_id}]
                    for inst in self.watchlist:
                        if inst != self.instrument_id:
                            ticker_args.append({"channel": "tickers", "instId": inst})

                    # Multi-channel subscription payload
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": ticker_args + [
                            {"channel": "books", "instId": self.instrument_id},
                            {"channel": "trades", "instId": self.instrument_id}
                        ]
                    }

                    await websocket.send(json.dumps(subscribe_msg))
                    logger.info(f"Subscribed to tickers (count: {len(ticker_args)}), books, and trades.")

                    async for message in websocket:
                        data = json.loads(message)

                        # Check if message is a data push from a specific channel
                        arg = data.get("arg", {})
                        channel = arg.get("channel")

                        if "data" in data and channel and self.callback:
                            # Forward the channel name and data payload to our callback
                            if asyncio.iscoroutinefunction(self.callback):
                                await self.callback(channel, data["data"])
                            else:
                                self.callback(channel, data["data"])

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket loop: {e}. Reconnecting in 5 seconds...", exc_info=True)
                await asyncio.sleep(5)

if __name__ == "__main__":
    # Define our file-cache bridge callback for live updates
    async def bridge_cache_callback(channel: str, data: list):
        payload = {"channel": channel, "data": data}
        print(f"-> Pushing channel [{channel}] update to cache file.")
        try:
            # Dump live feed data into local JSON cache file for the C++ TUI binary
            with open("bloomberg_cache.json", "w") as f:
                json.dump(payload, f)
        except Exception as e:
            logger.error(f"Failed to write cache file: {e}")

    # Initialize client targeting BTC-USD with our file-cache writer callback
    client = OKXPublicClient("BTC-USD", callback=bridge_cache_callback)

    try:
        asyncio.run(client.connect_market_streams())
    except KeyboardInterrupt:
        logger.info("Bridge daemon stopped by user.")
