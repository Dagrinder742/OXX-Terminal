import asyncio
import logging
import sys
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Static, Label
from textual.reactive import reactive
from api_client import OKXPublicClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class TelemetryHubTest(App):
    """Diagnostic TUI to test Native Exchange Telemetry Hub (SPOT & SWAP)"""

    CSS = """
    Screen {
        background: #000000;
        color: #ffffff;
        border: solid #ffcc00;
    }
    .panel {
        border: solid #ffcc00;
        height: auto;
        min-height: 15;
        padding: 1;
        margin: 1;
        background: #000000;
    }
    #right-main {
        width: 1fr;
    }
    .sub-panel {
        border: solid #ffcc00;
        height: auto;
        min-height: 20;
        padding: 1;
        margin: 1;
        background: #000000;
        width: 1fr;
    }
    .row {
        height: auto;
    }
    .telemetry-row {
        height: 1;
        margin-bottom: 0;
    }
    """

    def __init__(self):
        super().__init__()
        self.telemetry_data = {} # {instId: {last: str, change: str}}
        self.spot_list = []
        self.swap_list = []
        self.client = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Static("[bold green]Market Depth & Execution Feed (Placeholder)[/bold green]")
            with Horizontal(classes="row"):
                yield Static("Order Book Placeholder", classes="sub-panel")
                yield Static("Last Trades Placeholder", classes="sub-panel")

            yield Static("[bold yellow]Network Telemetry Hub[/bold yellow]")
            with Horizontal(classes="row"):
                with Vertical(classes="sub-panel", id="spot-hub"):
                    yield Static("[bold cyan]SPOT MARKET TELEMETRY[/bold cyan]")
                    yield Static("Asset      Price      24H %", classes="telemetry-row")
                    yield Static("---------------------------", classes="telemetry-row")
                    yield Static("Discovering assets...", id="spot-content")

                with Vertical(classes="sub-panel", id="swap-hub"):
                    yield Static("[bold magenta]SWAP MARKET TELEMETRY[/bold magenta]")
                    yield Static("Asset      Price      24H %", classes="telemetry-row")
                    yield Static("---------------------------", classes="telemetry-row")
                    yield Static("Discovering assets...", id="swap-content")
        yield Footer()

    async def on_mount(self) -> None:
        self.run_worker(self.initialize_telemetry())

    async def initialize_telemetry(self):
        temp_client = OKXPublicClient()
        
        # 1. Discovery Phase
        self.notify("Discovering OKX Markets...", title="Discovery")
        
        # Fetch SPOT
        all_spot = await asyncio.to_thread(temp_client.fetch_instruments, "SPOT")
        # Filter for USD prioritized, but keep USDT
        usd_spot = [i["instId"] for i in all_spot if i["instId"].endswith("-USD")]
        usdt_spot = [i["instId"] for i in all_spot if i["instId"].endswith("-USDT")]
        
        # Take top 5 USD + top 3 USDT for variety in test
        self.spot_list = (usd_spot[:5] + usdt_spot[:3])
        
        # Fetch SWAP
        all_swap = await asyncio.to_thread(temp_client.fetch_instruments, "SWAP")
        usd_swap = [i["instId"] for i in all_swap if i["instId"].endswith("-USD-SWAP")]
        usdt_swap = [i["instId"] for i in all_swap if i["instId"].endswith("-USDT-SWAP")]
        self.swap_list = (usd_swap[:5] + usdt_swap[:3])

        watchlist = self.spot_list + self.swap_list
        self.notify(f"Found {len(watchlist)} assets. Starting stream...", title="Success")

        # 2. Start WebSocket
        self.client = OKXPublicClient(instrument_id="BTC-USD", watchlist=watchlist, callback=self.handle_ws_data)
        asyncio.create_task(self.client.connect_market_streams())

    async def handle_ws_data(self, channel: str, data: list) -> None:
        if channel == "tickers":
            for ticker in data:
                inst_id = ticker.get("instId")
                last = float(ticker.get("last", 0))
                open_24h = float(ticker.get("open24h", 0))
                
                change_pct = 0.0
                if open_24h > 0:
                    change_pct = ((last - open_24h) / open_24h) * 100
                
                self.telemetry_data[inst_id] = {
                    "last": f"{last:,.2f}",
                    "change": f"{change_pct:+.2f}%"
                }
            
            self.refresh_hubs()

    def refresh_hub_content(self, inst_list, widget_id):
        lines = []
        for inst in inst_list:
            data = self.telemetry_data.get(inst, {"last": "---", "change": "---"})
            color = "green" if "+" in data["change"] else "red"
            if data["change"] == "---": color = "white"
            
            # Format: BTC-USD    78,000.00    +2.5%
            lines.append(f"{inst:<12} {data['last']:>10}    [{color}]{data['change']:>7}[/{color}]")
        
        try:
            self.query_one(widget_id, Static).update("\n".join(lines))
        except:
            pass

    def refresh_hubs(self):
        self.refresh_hub_content(self.spot_list, "#spot-content")
        self.refresh_hub_content(self.swap_list, "#swap-content")

if __name__ == "__main__":
    app = TelemetryHubTest()
    app.run()
