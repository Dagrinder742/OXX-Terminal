import asyncio
import json
import logging
import sys
import websockets
from typing import Dict, List, Tuple

# Configure clean, structured telemetry logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("OrderBookGateway")

class LocalOrderBook:
    """
    Maintains an in-memory order book for a given product (e.g., BTC-USD).
    Keeps bids (descending) and asks (ascending) sorted securely via async locks.
    """
    def __init__(self, product_id: str):
        self.product_id = product_id
        self.bids: Dict[float, float] = {}  # price -> size
        self.asks: Dict[float, float] = {}  # price -> size
        self.sequence: int = -1
        self._lock = asyncio.Lock()

    async def apply_snapshot(self, bids: List[List[str]], asks: List[List[str]], sequence: int):
        async with self._lock:
            self.bids.clear()
            self.asks.clear()
            for price, size in bids:
                self.bids[float(price)] = float(size)
            for price, size in asks:
                self.asks[float(price)] = float(size)
            self.sequence = sequence
            logger.info(f"[{self.product_id}] Snapshot synchronized. Seq: {sequence} | Bids: {len(self.bids)} | Asks: {len(self.asks)}")

    async def apply_delta(self, bids: List[List[str]], asks: List[List[str]], sequence: int):
        async with self._lock:
            # Sequence validation guard: reject duplicates or stale frames
            if sequence != -1 and self.sequence != -1 and sequence <= self.sequence:
                return

            self.sequence = sequence

            for price_str, size_str in bids:
                price, size = float(price_str), float(size_str)
                if size == 0.0:
                    self.bids.pop(price, None)
                else:
                    self.bids[price] = size

            for price_str, size_str in asks:
                price, size = float(price_str), float(size_str)
                if size == 0.0:
                    self.asks.pop(price, None)
                else:
                    self.asks[price] = size

    async def get_top_levels(self, limit: int = 5) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        async with self._lock:
            sorted_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:limit]
            sorted_asks = sorted(self.asks.items(), key=lambda x: x[0])[:limit]
            return sorted_bids, sorted_asks


class CoinbaseWebsocketGateway:
    """
    Manages the persistent WebSocket connection, automatic reconnection with exponential backoff,
    and message routing to the LocalOrderBook.
    """
    def __init__(s, product_id: str, order_book: LocalOrderBook):
        s.product_id = product_id
        s.order_book = order_book
        s.uri = "wss://advanced-trade-ws.coinbase.com"
        s.is_running = False

    async def connect(self):
        self.is_running = True
        backoff = 1.0
        max_backoff = 60.0

        while self.is_running:
            try:
                logger.info(f"Connecting to Coinbase WebSocket endpoint...")
                async with websockets.connect(self.uri) as ws:
                    logger.info("WebSocket connected successfully. Transmitting subscription payload...")
                    backoff = 1.0  # Reset backoff on success

                    sub_payload = {
                        "type": "subscribe",
                        "product_ids": [self.product_id],
                        "channel": "level2"
                    }
                    await ws.send(json.dumps(sub_payload))

                    async for raw_message in ws:
                        await self._handle_message(raw_message)

            except (websockets.ConnectionClosedError, websockets.ConnectionClosedOK) as e:
                logger.warning(f"Connection dropped: {e}. Reconnecting in {backoff}s...")
            except Exception as e:
                logger.error(f"Unexpected transport error: {e}. Reconnecting in {backoff}s...")

            if self.is_running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _handle_message(self, raw_message: str):
        try:
            data = json.loads(raw_message)
            events = data.get("events", [])

            for event in events:
                event_type = event.get("type")
                updates = event.get("updates", [])

                bids, asks = [], []
                for update in updates:
                    side = update.get("side")
                    price = update.get("price")
                    size = update.get("new_quantity")
                    if side == "bid":
                        bids.append([price, size])
                    elif side in ("offer", "ask"):
                        asks.append([price, size])

                seq = int(data.get("sequence", -1))
                if event_type == "snapshot":
                    await self.order_book.apply_snapshot(bids, asks, sequence=seq)
                elif event_type == "update":
                    await self.order_book.apply_delta(bids, asks, sequence=seq)

        except json.JSONDecodeError:
            logger.error("Failed to parse incoming frame schema.")
        except Exception as e:
            logger.error(f"Error handling message frame: {e}")

    def stop(self):
        self.is_running = False


async def telemetry_reporter(order_book: LocalOrderBook, interval: float = 3.0):
    """
    Non-blocking background loop that inspects order book health and depth telemetry.
    """
    while True:
        await asyncio.sleep(interval)
        bids, asks = await order_book.get_top_levels(limit=3)

        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        spread = best_ask - best_bid if (best_ask and best_bid) else 0.0

        logger.info(f"=== TELEMETRY [Seq: {order_book.sequence}] ===")
        logger.info(f"Best Bid: {best_bid:,.2f} | Best Ask: {best_ask:,.2f} | Spread: {spread:.2f}")
        logger.info(f"Top 3 Bids: {bids}")
        logger.info(f"Top 3 Asks: {asks}")


async def main():
    product = "BTC-USD"
    book = LocalOrderBook(product_id=product)
    gateway = CoinbaseWebsocketGateway(product_id=product, order_book=book)

    await asyncio.gather(
        gateway.connect(),
        telemetry_reporter(book, interval=3.0)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Graceful shutdown sequence initialized by operator.")

