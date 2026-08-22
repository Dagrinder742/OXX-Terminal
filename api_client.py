import asyncio
import json
import logging
import websockets
from typing import Callable, Optional

# Primary public WebSocket endpoint for OKX market feeds
OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OKX_Client")

class OKXPublicClient:
    def __init__(self, instrument_id: str = "BTC-USD", callback: Optional[Callable[[str, dict], None]] = None):
        self.instrument_id = instrument_id
        self.uri = OKX_WS_PUBLIC
        self.callback = callback  # Callback function to push data packets back to the TUI app

    async def connect_market_streams(self):
        """Connects to the OKX public WebSocket and subscribes to tickers, order book, and trades."""
        while True:
            try:
                logger.info(f"Connecting to OKX WebSocket at {self.uri}...")
                async with websockets.connect(self.uri) as websocket:

                    # Multi-channel subscription payload for professional layout feeds
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [
                            {"channel": "tickers", "instId": self.instrument_id},
                            {"channel": "books", "instId": self.instrument_id},
                            {"channel": "trades", "instId": self.instrument_id}
                        ]
                    }

                    await websocket.send(json.dumps(subscribe_msg))
                    logger.info(f"Subscribed to tickers, books, and trades for {self.instrument_id}")

                    async for message in websocket:
                        data = json.loads(message)

                        # Check if message is a data push from a specific channel
                        arg = data.get("arg", {})
                        channel = arg.get("channel")

                        if "data" in data and channel and self.callback:
                            # Forward the channel name and data payload to our UI orchestrator
                            await self.callback(channel, data["data"])

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket loop: {e}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

if __name__ == "__main__":
    async def test_callback(channel, data):
        print(f"Channel: {channel} | Data count: {len(data)}")

    client = OKXPublicClient("BTC-USD", callback=test_callback)
    try:
        asyncio.run(client.connect_market_streams())
    except KeyboardInterrupt:
        logger.info("Client stopped by user.")

