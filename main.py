import asyncio
import logging
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static, Input, Button, Label
from textual.reactive import reactive
from textual.screen import ModalScreen
from secure_vault import EncryptedVault
from api_client import OKXPublicClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class AuthModal(ModalScreen):
    """A modal screen that prompts the user for secure API credentials on first launch."""

    CSS = """
    AuthModal {
        align: center middle;
    }
    #dialog {
        padding: 1 3;
        width: 60;
        height: 24;
        background: #1e1e1e;
        border: solid #00ffcc;
    }
    .input-box {
        margin-bottom: 1;
    }
    Button {
        width: 100%;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[bold cyan]🔐 OKX Secure Credential Setup[/bold cyan]")
            yield Static("Enter your API credentials. Press Enter to submit.")

            yield Label("API Key:")
            yield Input(placeholder="Enter API Key...", id="api_key_input", classes="input-box")

            yield Label("Secret Key:")
            yield Input(placeholder="Enter Secret Key...", password=True, id="secret_key_input", classes="input-box")

            yield Label("Passphrase:")
            yield Input(placeholder="Enter Passphrase...", password=True, id="passphrase_input", classes="input-box")

            yield Button("Save & Launch Terminal", variant="success", id="save_btn")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit_credentials()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_btn":
            self._submit_credentials()

    def _submit_credentials(self) -> None:
        api_key = self.query_one("#api_key_input", Input).value.strip()
        secret_key = self.query_one("#secret_key_input", Input).value.strip()
        passphrase = self.query_one("#passphrase_input", Input).value.strip()

        if api_key and secret_key and passphrase:
            EncryptedVault.save_credentials(api_key, secret_key, passphrase)
            self.dismiss(True)
        else:
            self.query_one(Static).update("[bold red]All fields are required! Please fill out all inputs.[/bold red]")

class OKXTerminalApp(App):
    """A fully asynchronous, real-time OKX TUI trading terminal with live market depth grids."""

    def __init__(self):
        super().__init__()
        self.cached_asks = []
        self.cached_bids = []
        self.cached_trades = []


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
    }

    .panel {
        border: solid #333333;
        height: 1fr;
        padding: 1;
        margin: 1;
        background: #181818;
    }

    #left-sidebar {
        width: 30%;
    }

    #right-main {
        width: 70%;
    }

    .sub-grid {
        height: 1fr;
    }

    .sub-panel {
        border: solid #222222;
        height: 1fr;
        padding: 1;
        margin: 0 1;
        background: #141414;
    }

    .row {
        height: 1fr;
    }

    Button {
        width: 100%;
        margin-top: 1;
    }
    """

    current_price = reactive("Connecting...")
    high_24h = reactive("---")
    low_24h = reactive("---")
    volume_24h = reactive("---")

    def compose(self) -> ComposeResult:
        yield Header()

        # Top ticker strip
        yield Static(" OKX TUI > BTC-USD | Loading Ticker Feed...", id="header-bar")

        # Main workspace grid split into columns
        with Horizontal(classes="row"):

            # Left Sidebar: Order Execution / Inputs
            with Vertical(classes="panel", id="left-sidebar"):
                yield Static("[bold cyan]Order Entry Panel[/bold cyan]")
                yield Static("Price:")
                yield Input(placeholder="77,891.50", id="price-input")
                yield Static("Amount:")
                yield Input(placeholder="0.001", id="amount-input")
                yield Button("BUY (LONG)", variant="success")
                yield Button("SELL (SHORT)", variant="error")

            # Right Main Workspace: Split into Order Book and Last Trades panels
            with Vertical(classes="panel", id="right-main"):
                yield Static("[bold green]Market Depth & Execution Feed[/bold green]")

                with Horizontal(classes="sub-grid"):
                    # Order Book Panel (Bids & Asks)
                    with Vertical(classes="sub-panel", id="order-book-panel"):
                        yield Static("[bold cyan]Order Book[/bold cyan]")
                        yield Static("Asks (Sells)\n---------------------\nWaiting for depth...", id="order-book-asks")
                        yield Static("[bold green]Spread / Mid-Price[/bold green]", id="order-book-mid")
                        yield Static("Bids (Buys)\n---------------------\nWaiting for depth...", id="order-book-bids")

                    # Last Trades Panel
                    with Vertical(classes="sub-panel", id="last-trades-panel"):
                        yield Static("[bold yellow]Last Trades[/bold yellow]")
                        yield Static("Price (USD)  Amount  Time\n---------------------------------", id="last-trades-header")
                        yield Static("Waiting for trade stream...", id="last-trades-content")

        yield Footer()

    async def on_mount(self) -> None:
        creds = EncryptedVault.load_credentials()
        if not creds.get("api_key"):
            self.push_screen(AuthModal(), self.handle_auth_result)
        else:
            self.notify("Secure credentials loaded from encrypted vault.", title="Auth Success")
            self._start_terminal_services()

    def handle_auth_result(self, success: bool) -> None:
        if success:
            self.notify("Credentials saved to encrypted vault!", title="Vault Updated")
            self._start_terminal_services()

    def _start_terminal_services(self) -> None:
        self.set_interval(0.1, self.update_header_display)
        self.client = OKXPublicClient(instrument_id="BTC-USD", callback=self.handle_ws_data)
        self.bg_worker = asyncio.create_task(self.client.connect_market_streams())

    async def handle_ws_data(self, channel: str, data: list) -> None:
        """Parses multi-channel telemetry from api_client.py and updates target TUI widgets."""
        if channel == "tickers":
            for ticker in data:
                self.current_price = ticker.get("last", "0.0")
                self.high_24h = ticker.get("high24h", "0.0")
                self.low_24h = ticker.get("low24h", "0.0")
                self.volume_24h = ticker.get("vol24h", "0.0")

        elif channel == "books":
            for book in data:
                action = book.get("action", "update")
                raw_asks = book.get("asks", [])
                raw_bids = book.get("bids", [])

                if action == "snapshot":
                    self.cached_asks = raw_asks[:5]
                    self.cached_bids = raw_bids[:5]
                else:
                    # Merge delta updates into existing cached levels by price
                    for ask in raw_asks:
                        price, size, _, _ = ask[:4]
                        if float(size) == 0.0:
                            self.cached_asks = [a for a in self.cached_asks if a[0] != price]
                        else:
                            # Update or append
                            updated = False
                            for i, a in enumerate(self.cached_asks):
                                if a[0] == price:
                                    self.cached_asks[i] = ask
                                    updated = True
                            if not updated:
                                self.cached_asks.append(ask)

                    for bid in raw_bids:
                        price, size, _, _ = bid[:4]
                        if float(size) == 0.0:
                            self.cached_bids = [b for b in self.cached_bids if b[0] != price]
                        else:
                            updated = False
                            for i, b in enumerate(self.cached_bids):
                                if b[0] == price:
                                    self.cached_bids[i] = bid
                                    updated = True
                            if not updated:
                                self.cached_bids.append(bid)

                # Keep top 5 sorted cleanly
                self.cached_asks = sorted(self.cached_asks, key=lambda x: float(x[0]))[:5]
                self.cached_bids = sorted(self.cached_bids, key=lambda x: float(x[0]), reverse=True)[:5]

                asks = self.cached_asks
                bids = self.cached_bids

                asks_formatted = []
                for ask in reversed(asks):
                    price = float(ask[0])
                    amt = float(ask[1])
                    asks_formatted.append(f"[red]{price:,.1f}  {amt:.4f}[/red]")

                bids_formatted = []
                for bid in bids:
                    price = float(bid[0])
                    amt = float(bid[1])
                    bids_formatted.append(f"[green]{price:,.1f}  {amt:.4f}[/green]")

                asks_text = "Asks (Sells) [Price / Amt]\n" + ("\n".join(asks_formatted) if asks_formatted else "Waiting...")
                bids_text = "Bids (Buys) [Price / Amt]\n" + ("\n".join(bids_formatted) if bids_formatted else "Waiting...")

                try:
                    self.query_one("#order-book-asks", Static).update(asks_text)
                    self.query_one("#order-book-bids", Static).update(bids_text)
                    if asks and bids:
                        spread = float(asks[0][0]) - float(bids[0][0])
                        self.query_one("#order-book-mid", Static).update(f"[bold white]Spread: {spread:.2f}[/bold white]")
                except Exception as e:
                    logging.error(f"Error updating order book widgets: {e}")

        elif channel == "trades":
            for trade in data:
                price = float(trade.get("px", 0))
                size = float(trade.get("sz", 0))
                side = trade.get("side", "buy")
                # Format time string if available, or just keep it clean
                timestamp = trade.get("ts", "")

                # Append to the front of our rolling list
                self.cached_trades.insert(0, {"price": price, "size": size, "side": side})

            # Keep only the last 10 trades
            self.cached_trades = self.cached_trades[:10]

            trade_lines = []
            for t in self.cached_trades:
                color = "green" if t["side"] == "buy" else "red"
                trade_lines.append(f"[{color}]{t['price']:,.1f} | {t['size']:.4f}[/{color}]")

            trades_text = "Price (USD)  Amount\n" + ("\n".join(trade_lines) if trade_lines else "No Trades")
            try:
                self.query_one("#last-trades-content", Static).update(trades_text)
            except Exception as e:
                logging.error(f"Error updating trades widgets: {e}")

    def update_header_display(self) -> None:
        header_widget = self.query_one("#header-bar", Static)
        header_widget.update(
            f" OKX TUI > BTC-USD [dim]│[/dim] Price: [bold green]{self.current_price}[/bold green] "
            f"[dim]│[/dim] High: {self.high_24h} [dim]│[/dim] Low: {self.low_24h} [dim]│[/dim] Vol: {self.volume_24h}"
        )

if __name__ == "__main__":
    app = OKXTerminalApp()
    app.run()
