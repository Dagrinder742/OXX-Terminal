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

    .log-container {
        height: 12;
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

            # Left Sidebar: Portfolio Balance & Order Entry Panel
            with Vertical(classes="panel", id="left-sidebar"):
                yield Static("[bold cyan]Portfolio Balance[/bold cyan]")
                yield Static("Loading Balances...", id="portfolio-balance")

                yield Static("[bold cyan]Order Entry Panel[/bold cyan]")
                yield Static("Price:")
                yield Input(placeholder="77,891.50", id="price-input")
                yield Static("Amount:")
                yield Input(placeholder="0.001", id="amount-input")
                yield Button("BUY (LONG)", variant="success")
                yield Button("SELL (SHORT)", variant="error")

            # Right Main Workspace: Market Depth, Trades, and Execution Log
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

                # Bottom Sub-Panel: Order Status / Activity Log
                with Vertical(classes="sub-panel log-container", id="log-panel"):
                    yield Static("[bold magenta]Execution & Order Log[/bold magenta]")
                    yield Static("System initialized. Waiting for actions...", id="execution-log-content")

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        # If triggered from AuthModal save button, ignore here as it's handled in AuthModal
        if button_id == "save_btn":
            return

        price_val = self.query_one("#price-input", Input).value.strip()
        amount_val = self.query_one("#amount-input", Input).value.strip()

        if not amount_val:
            self.notify("Please enter an order amount!", severity="error", title="Order Error")
            return

        # Default to limit order if price is provided, else market
        ord_type = "limit" if price_val else "market"

        if event.button.label.text.startswith("BUY"):
            side = "buy"
        else:
            side = "sell"

        # Run order execution asynchronously so it doesn't freeze the TUI loop
        self.run_worker(self._execute_order_task(side, ord_type, amount_val, price_val))

    async def _execute_order_task(self, side: str, ord_type: str, size: str, price: str) -> None:
        from okx_private import OKXPrivateClient

        self.notify(f"Submitting {side.upper()} {ord_type} order...", title="Executing")
        self.log_action(f"[yellow]Submitting {side.upper()} {ord_type} order (sz: {size})...[/yellow]")

        # Run the blocking requests call in an executor thread
        result = await asyncio.to_thread(
            OKXPrivateClient.place_order,
            inst_id="BTC-USD",
            side=side,
            order_type=ord_type,
            sz=size,
            px=price if ord_type == "limit" else None
        )

        code = result.get("code")
        if code == "0":
            data = result.get("data", [{}])[0]
            ord_id = data.get("ordId", "Unknown")
            self.notify(f"Order placed successfully! ID: {ord_id}", severity="information", title="Success")
            self.log_action(f"[green]SUCCESS: Order ID {ord_id} placed.[/green]")
            logging.info(f"Order success: {result}")
        else:
            msg = result.get("msg", "Unknown error")
            self.notify(f"Order failed [{code}]: {msg}", severity="error", title="API Error")
            self.log_action(f"[red]FAILED [{code}]: {msg}[/red]")
            logging.error(f"Order failed: {result}")

    def _start_terminal_services(self) -> None:
        self.set_interval(0.1, self.update_header_display)
        self.set_interval(5.0, self.update_portfolio_balance)  # Poll balances every 5s
        self.client = OKXPublicClient(instrument_id="BTC-USD", callback=self.handle_ws_data)
        self.bg_worker = asyncio.create_task(self.client.connect_market_streams())

    async def update_portfolio_balance(self) -> None:
        from okx_private import OKXPrivateClient
        result = await asyncio.to_thread(OKXPrivateClient.get_account_balance)

        if result.get("code") == "0":
            details = result.get("data", [{}])[0].get("details", [])
            bal_lines = []
            for asset in details:
                ccy = asset.get("ccy")
                avail = float(asset.get("availBal", 0))
                if avail > 0:
                    bal_lines.append(f"[bold white]{ccy}:[/bold white] {avail:,.4f}")

            balance_text = "\n".join(bal_lines) if bal_lines else "No active balances"
            try:
                self.query_one("#portfolio-balance", Static).update(balance_text)
            except Exception as e:
                # Widget might not be mounted yet during startup/shutdown
                logging.debug(f"Could not update portfolio balance widget: {e}")
        else:
            msg = result.get("msg", "Auth check failed")
            try:
                self.query_one("#portfolio-balance", Static).update(f"[dim red]{msg[:30]}...[/dim red]")
            except Exception as e:
                logging.debug(f"Could not update portfolio error widget: {e}")

    def log_action(self, message: str) -> None:
        """Appends status messages to the Execution Log window."""
        try:
            log_widget = self.query_one("#execution-log-content", Static)
            current_text = log_widget.renderable
            new_text = f"{message}\n{current_text}"
            lines = new_text.strip().split("\n")[:5]
            log_widget.update("\n".join(lines))
        except Exception:
            logging.info(message)


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
