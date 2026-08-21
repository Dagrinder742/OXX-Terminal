import asyncio
import json
import logging
import websockets

# Primary public WebSocket endpoint for OKX market feeds
OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("OKX_Client")

class OKXPublicClient:
    def __init__(self, instrument_id: str = "BTC-USDT"):
        self.instrument_id = instrument_id
        self.uri = OKX_WS_PUBLIC

    async def connect_ticker_stream(self):
        """Connects to the OKX public WebSocket and listens to ticker updates."""
        while True:
            try:
                logger.info(f"Connecting to OKX WebSocket at {self.uri}...")
                async with websockets.connect(self.uri) as websocket:
                    
                    # Subscription payload for the ticker channel
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [{"channel": "tickers", "instId": self.instrument_id}]
                    }
                    
                    await websocket.send(json.dumps(subscribe_msg))
                    logger.info(f"Subscribed to ticker feed for {self.instrument_id}")

                    async for message in websocket:
                        data = json.loads(message)
                        
                        # Filter and process data payloads
                        if "data" in data:
                            for ticker in data["data"]:
                                last_price = ticker.get("last")
                                high_24h = ticker.get("high24h")
                                low_24h = ticker.get("high24h")
                                volume_24h = ticker.get("vol24h")
                                
                                logger.info(
                                    f"[{self.instrument_id}] Price: {last_price} | "
                                    f"High: {high_24h} | Low: {low_24h} | Vol: {volume_24h}"
                                )

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket loop: {e}. Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

if __name__ == "__main__":
    client = OKXPublicClient("BTC-USDT")
    try:
        asyncio.run(client.connect_ticker_stream())
    except KeyboardInterrupt:
        logger.info("Client stopped by user.")