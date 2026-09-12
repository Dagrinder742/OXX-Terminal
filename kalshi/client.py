# kalshi/client.py
import asyncio
import json
import logging
from pathlib import Path
import websockets
from auth import load_private_key_from_file, get_auth_headers

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("KalshiWSClient")

# Configuration Constants
API_KEY_ID = "837934ae-214d-4a46-86ff-dbfb21619e49"
KEY_FILE_PATH = Path(__file__).resolve().parent / "main.txt"
WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
WS_PATH = "/trade-api/ws/v2"

async def kalshi_stream_listener():
    """Connects to Kalshi live WebSocket feed and listens for market data."""
    if not KEY_FILE_PATH.exists():
        logger.error(f"Private key file not found at {KEY_FILE_PATH}")
        return

    logger.info("Loading private key for WebSocket handshake...")
    private_key = load_private_key_from_file(str(KEY_FILE_PATH))

    # Generate authentication headers using the WebSocket endpoint path
    headers = get_auth_headers(
        api_key_id=API_KEY_ID,
        private_key=private_key,
        method="GET",
        path=WS_PATH
    )

    logger.info(f"Connecting to Kalshi WebSocket at {WS_URL}...")

    try:
        # Pass authentication headers during the handshake
        async with websockets.connect(WS_URL, additional_headers=headers) as websocket:
            logger.info("Connected successfully to Kalshi WebSocket feed!")

            # Example: Subscribe to a public ticker or orderbook channel
            sub_payload = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["ticker"],
                    "market_tickers": [
                        "KXBTC15M-26SEP112215-15",
                        "KXSOL15M-26SEP112215-15",
                        "KXHYPE15M-26SEP112215-15"
                    ]
                }
            }

            await websocket.send(json.dumps(sub_payload))
            logger.info("Subscription request sent. Listening for messages...")

            # Listen loop
            async for message in websocket:
                data = json.loads(message)
                logger.info(f"Received WebSocket Message: {data}")

    except websockets.exceptions.ConnectionClosed as e:
        logger.warning(f"WebSocket connection closed: {e}")
    except Exception as e:
        logger.error(f"An error occurred in the WebSocket client: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(kalshi_stream_listener())
    except KeyboardInterrupt:
        logger.info("WebSocket client stopped by user.")
