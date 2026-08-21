import asyncio
import json
import logging
import websockets
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static, Input, Button
from textual.reactive import reactive

# OKX Public WebSocket Endpoint
OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class OKXTerminalApp(App):
    """A fully asynchronous, real-time OKX TUI trading terminal."""

    CSS = """
    Screen {
        background: #111111;
        color: #ffffff;
    }

    #header-bar {
        height: 3;
        border: solid #00ffcc;
        padding: 0 1;
        background: #1a1a1a;
        text-style: bold;
    }

    .panel {
        border: solid #333333;
        height: 1fr;
        padding: 1;
        margin: 1;
        background: #181818;
    }

    #left-sidebar {
        width: 35%;
    }

    #right-main {
        width: 65%;
    }

    .row {
        height: 1fr;
    }

    Button {
        width: 100%;
        margin-top: 1;
    }
    """

    # Reactive properties automatically trigger UI updates when their values change
    current_price = reactive("Connecting...")
    high_24h = reactive("---")
    low_24h = reactive("---")
    volume_24h = reactive("---")

    def compose(self) -> ComposeResult:
        yield Header()

        # Dynamic top ticker strip bound to reactive properties
        yield Static(id="header-bar")

        # Main workspace grid
        with Horizontal(classes="row"):
            # Left Sidebar: Order Execution
            with Vertical(classes="panel", id="left-sidebar"):
                yield Static("[bold cyan]Order Entry Panel[/bold cyan]")
                yield Static("Price:")
                yield Input(placeholder="0.00", id="price-input")
                yield Static("Amount:")
                yield Input(placeholder="0.001", id="amount-input")
                yield Button("BUY (LONG)", variant="success")
                yield Button("SELL (SHORT)", variant="error")

            # Right Main Workspace: Order book / feeds
            with Vertical(classes="panel", id="right-main"):
                yield Static("[bold green]Live Candlestick / Order Book Feed[/bold green]")
                yield Static("WebSocket Stream Active: Streaming live data ticks...", id="feed-status")

        yield Footer()

    async def on_mount(self) -> None:
        """Triggered when the app starts; spawns the background WebSocket loop."""
        self.set_interval(0.1, self.update_header_display)
        self.bg_worker = asyncio.create_task(self.connect_okx_stream())

    def update_header_display(self) -> None:
        """Refreshes the header bar with the latest live market telemetry."""
        header_widget = self.query_one("#header-bar", Static)
        header_widget.update(
            f" OKX TUI > BTC-USD [dim]│[/dim] Price: [bold green]{self.current_price}[/bold green] "
            f"[dim]│[/dim] High: {self.high_24h} [dim]│[/dim] Low: {self.low_24h} [dim]│[/dim] Vol: {self.volume_24h}"
        )

    async def connect_okx_stream(self) -> None:
        """Asynchronous background loop handling real-time OKX data subscription."""
        instrument = "BTC-USD"  # Swapped from USDT to USD pair
        while True:
            try:
                async with websockets.connect(OKX_WS_PUBLIC) as websocket:
                    subscribe_msg = {
                        "op": "subscribe",
                        "args": [{"channel": "tickers", "instId": instrument}]
                    }
                    await websocket.send(json.dumps(subscribe_msg))

                    async for message in websocket:
                        data = json.loads(message)
                        if "data" in data:
                            for ticker in data["data"]:
                                # Update reactive state variables
                                self.current_price = ticker.get("last", "0.0")
                                self.high_24h = ticker.get("high24h", "0.0")
                                self.low_24h = ticker.get("low24h", "0.0")
                                self.volume_24h = ticker.get("vol24h", "0.0")

            except websockets.exceptions.ConnectionClosed:
                self.current_price = "Reconnecting..."
                await asyncio.sleep(5)
            except Exception:
                self.current_price = "Connection Error"
                await asyncio.sleep(5)

if __name__ == "__main__":
    app = OKXTerminalApp()
    app.run()
