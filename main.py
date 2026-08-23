import asyncio
import logging
import sys
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Static, Input, Button, Label
from textual.reactive import reactive
from textual.screen import ModalScreen
from secure_vault import EncryptedVault
from api_client import OKXPublicClient
from chart_renderer import OKXChartEngine
from strategy_engine import StrategyManager

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
        background: #000000;
        border: solid #ffcc00;
    }
    .input-box {
        margin-bottom: 1;
        border: solid;
    }
    Button {
        width: 100%;
        margin-top: 1;
        border: solid;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[bold cyan] OKX Secure Credential Setup[/bold cyan]")
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
        self.instrument_id = "BTC-USD"
        self.cached_asks = []
        self.cached_bids = []
        self.cached_trades = []
        self.bg_worker = None
        self.client = None
        self.current_timeframe = "15m"
        self.strategy_manager = StrategyManager()
        self.bot_worker = None

    CSS = """
    Screen {
        background: #000000;
        color: #ffffff;
        overflow-y: auto;
        border: solid #ffcc00;
        scrollbar-size: 0 0;
    }

    #page-viewport {
        width: 100%;
        height: auto;
        overflow-y: auto;
    }

    #header-bar {
        height: 3;
        border: solid #ffcc00;
        padding: 0 1;
        background: #000000;
    }

    .panel {
        border: solid #ffcc00;
        height: auto;
        min-height: 20;
        padding: 1;
        margin: 1;
        background: #000000;
        border: solid;
    }

    #left-column {
        width: 30%;
        height: auto;
    }

    #left-sidebar {
        border: solid;
        margin-bottom: 1;
    }

    #bot-panel {
        border: solid #ffcc00;
        height: auto;
        min-height: 15;
        padding: 1;
        margin: 1;
        background: #000000;
    }

    #right-main {
        width: 70%;
        border: solid;
    }

    .sub-grid {
        height: auto;
        min-height: 20;
    }

    .sub-panel {
        border: solid #ffcc00;
        height: auto;
        min-height: 15;
        padding: 1;
        margin: 0 1;
        background: #000000;
    }

    .row {
        height: auto;
    }

    Button {
        width: 100%;
        margin-top: 1;
        background: #111111;
        color: #ffcc00;
        border: solid #ffcc00;
    }

    Button:hover {
        background: #ffcc00;
        color: #000000;
        border: solid;
    }

    /* Star Blue for BUY */
    Button.buy-btn {
        background: #000000;
        color: #3399ff;
        border: solid #3399ff;
    }
    Button.buy-btn:hover {
        background: #3399ff;
        color: #000000;
    }

    /* Star Red for SELL/STOP */
    Button.sell-btn {
        background: #000000;
        color: #ff3333;
        border: solid #ff3333;
    }
    Button.sell-btn:hover {
        background: #ff3333;
        color: #000000;
    }

    Input {
        background: #000000;
        border: solid #333333;
        color: #ffffff;
        border: solid;
    }

    Input:focus {
        border: solid #ffcc00;
    }

    .log-container {
        height: 5;
        margin-top: 1;
        border: solid;
    }

    .positions-container {
        height: 5;
        margin-top: 1;
        border: solid;
    }

    #chart-container {
        height: 30;
        padding: 1;
        background: #000000;
        border: solid #ffcc00;
        margin-top: 1;
    }

    #ascii-chart-view {
        height: 18;
        width: 125;
        text-wrap: nowrap;
        text-overflow: clip;
        overflow: hidden;
        border: solid #ffcc00;
        margin-top: 1;
    }

    .timeframe-bar {
        height: 3;
        layout: horizontal;
        margin-bottom: 1;
    }

    .tf-btn {
        width: 1fr;
        height: 3;
        margin: 0 1;
        background: #000000;
        color: #ffcc00;
        border: solid #ffcc00;
    }

    .tf-btn:hover {
        background: #ffcc00;
        color: #000000;
        border: solid;
    }

    /* Fix for notification "eye sores" */
    Toast {
        border: solid #ffcc00;
        background: #000000;
        color: #ffffff;
    }

    /* Fix for scrollbar "eye sores" */
    ScrollBar {
        background: #000000;
        color: #ffcc00;
    }
    
    #page-viewport {
        width: 100%;
        height: auto;
        overflow-y: auto;
    }
    """

    current_price = reactive("Connecting...")
    high_24h = reactive("---")
    low_24h = reactive("---")
    volume_24h = reactive("---")

    def compose(self) -> ComposeResult:
        yield Header()

        # Top ticker strip
        yield Static(f" OXX TUI > {getattr(self, 'current_pair', 'BTC-USD')} | Loading Ticker Feed...", id="header-bar")

        # Main viewport with page-level scrolling
        with VerticalScroll(id="page-viewport"):
            # Main workspace grid split into columns
            with Horizontal(classes="row"):

                # Left Column: Manual Order Entry & Bot Control
                with Vertical(id="left-column"):
                    # Sidebar: Portfolio Balance & Order Entry Panel
                    with Vertical(classes="panel", id="left-sidebar"):
                        yield Static("[bold #ffcc00]Instrument Search[/bold #ffcc00]")
                        yield Input(placeholder="BTC-USD", id="instrument-search-input")

                        yield Static("[bold #ffcc00]Portfolio Balance[/bold #ffcc00]")
                        yield Static("Loading Balances...", id="portfolio-balance")

                        yield Static("[bold #ffcc00]Order Entry Panel[/bold #ffcc00]")
                        yield Static("Price:")
                        yield Input(placeholder="$0.00", id="price-input")
                        yield Static("Amount:")
                        yield Input(placeholder="0.001", id="amount-input")

                        # New Advanced TP/SL Inputs
                        yield Static("[dim]Advanced Risk Management (TP/SL)[/dim]")
                        yield Input(placeholder="Take-Profit Price...", id="tp-input")
                        yield Input(placeholder="Stop-Loss Price...", id="sl-input")

                        yield Button("BUY (LONG)", variant="success", classes="buy-btn")
                        yield Button("SELL (SHORT)", variant="error", classes="sell-btn")

                    # Bot Control Panel
                    with Vertical(classes="panel", id="bot-panel"):
                        yield Static("[bold #ffcc00]Grid Bot Control Panel[/bold #ffcc00]")
                        yield Static("Engine Status: [bold red]IDLE[/bold red]", id="bot-status")
                        yield Static("Active Bots: 0 | Strategy PnL: $0.00", id="bot-metrics")
                        yield Button("START GRID BOT", variant="success", id="start-bot-btn", classes="buy-btn")
                        yield Button("STOP ALL BOTS", variant="error", id="stop-bot-btn", classes="sell-btn")

                # Right Main Workspace: Candlestick Chart, Market Depth, Trades, and Activity
                with Vertical(classes="panel", id="right-main"):
                    
                    # 1. Candlestick Chart Sub-Panel (NOW AT TOP)
                    with Vertical(classes="sub-panel", id="chart-container"):
                        yield Static("[bold cyan]Candlestick Price Action[/bold cyan]")
                        with Horizontal(classes="timeframe-bar"):
                            yield Button("1m", id="tf-1m", classes="tf-btn")
                            yield Button("5m", id="tf-5m", classes="tf-btn")
                            yield Button("15m", id="tf-15m", classes="tf-btn")
                            yield Button("1H", id="tf-1h", classes="tf-btn")
                            yield Button("1D", id="tf-1d", classes="tf-btn")
                        yield Static("Loading Chart Data...", id="ascii-chart-view")

                    # 2. Market Depth & Last Trades
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

                    # 3. Open Orders & Positions Sub-Panel
                    with Vertical(classes="sub-panel positions-container", id="positions-panel"):
                        yield Static("[bold blue]Open Orders & Positions Tracking[/bold blue]")
                        yield Static("Scanning for open orders and positions...", id="positions-content")

                    # 4. Bottom Sub-Panel: Order Status / Activity Log
                    with Vertical(classes="sub-panel log-container", id="log-panel"):
                        yield Static("[bold magenta]Execution & Order Log[/bold magenta]")
                        yield Static("System initialized. Waiting for actions...", id="execution-log-content")

        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handles submission from the instrument search input."""
        if event.input.id == "instrument-search-input":
            new_inst = event.value.strip().upper().replace("/", "-")
            if not new_inst:
                return

            # Normalize spaces to hyphens (e.g., "SOL USD" -> "SOL-USD")
            if " " in new_inst:
                new_inst = new_inst.replace(" ", "-")

            # Default to -USD if no quote asset or hyphen is provided
            if "-" not in new_inst:
                new_inst = f"{new_inst}-USD"

            event.input.value = ""
            self.action_switch_instrument(new_inst)

    async def on_mount(self) -> None:
        creds = EncryptedVault.load_credentials()
        if not creds.get("api_key"):
            self.push_screen(AuthModal(), self.handle_auth_result)
        else:
            self.notify("Secure credentials loaded from encrypted vault.", title="Auth Success")
            self._start_terminal_services()
            self.refresh_chart()

    def handle_auth_result(self, success: bool) -> None:
        if success:
            self.notify("Credentials saved to encrypted vault!", title="Vault Updated")
            self._start_terminal_services()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id and button_id.startswith("tf-"):
            # Handle timeframe clicks via mouse
            tf_map = {"tf-1m": "1m", "tf-5m": "5m", "tf-15m": "15m", "tf-1h": "1H", "tf-1d": "1D"}
            self.current_timeframe = tf_map.get(button_id, "15m")
            self.notify(f"Switching timeframe to {self.current_timeframe}", title="Chart Update")
            self.refresh_chart()
            return

        if button_id == "save_btn":
            return

        if button_id == "start-bot-btn":
            self.action_start_bot()
            return

        if button_id == "stop-bot-btn":
            self.action_stop_bot()
            return

        price_val = self.query_one("#price-input", Input).value.strip()
        amount_val = self.query_one("#amount-input", Input).value.strip()
        tp_val = self.query_one("#tp-input", Input).value.strip()
        sl_val = self.query_one("#sl-input", Input).value.strip()

        if not amount_val:
            self.notify("Please enter an order amount!", severity="error", title="Order Error")
            return

        ord_type = "limit" if price_val else "market"
        side = "buy" if event.button.label.text.startswith("BUY") else "sell"

        self.run_worker(self._execute_order_task(side, ord_type, amount_val, price_val, tp_val, sl_val))

    def action_switch_instrument(self, new_inst: str) -> None:
        """Switches the active trading pair dynamically without restarting the app."""
        if self.instrument_id == new_inst:
            return

        # Stop bot if instrument changes (safety)
        if self.strategy_manager.active_bots:
            self.action_stop_bot()
            self.notify("Trading Bot stopped due to instrument switch.", severity="warning")

        old_inst = self.instrument_id
        self.instrument_id = new_inst
        self.query_one("#header-bar", Static).update(f" OXX TUI > {self.instrument_id} | Loading Ticker Feed...")
        self.notify(f"Switching instrument from {old_inst} to {new_inst}...", title="Market Switch")
        self.log_action(f"[yellow]Switching feed to {new_inst}...[/yellow]")

        self.cached_asks = []
        self.cached_bids = []
        self.cached_trades = []

        try:
            self.query_one("#last-trades-content", Static).update("Waiting for trade stream...")
        except Exception as e:
            logging.warning(f"Could not clear trades widget on switch: {e}")

        self.current_price = "Connecting..."

        if self.bg_worker and not self.bg_worker.done():
            self.bg_worker.cancel()

        self.client = OKXPublicClient(instrument_id=new_inst, callback=self.handle_ws_data)
        self.bg_worker = asyncio.create_task(self.client.connect_market_streams())

        self.refresh_chart()
        self.notify(f"Successfully tuned to {new_inst}", title="Feed Active")

    def action_start_bot(self) -> None:
        """Initializes and starts the Grid Bot strategy."""
        if self.strategy_manager.active_bots:
            self.notify("A bot is already running!", severity="warning")
            return

        # Determine bounds and grid settings from inputs or current price
        try:
            mid_price = float(self.current_price)
            tp_price = self.query_one("#tp-input", Input).value.strip()
            sl_price = self.query_one("#sl-input", Input).value.strip()
            amount_str = self.query_one("#amount-input", Input).value.strip()

            if not amount_str:
                self.notify("Order amount required to start bot!", severity="error")
                return

            investment = float(amount_str)
            lower = float(sl_price) if sl_price else mid_price * 0.98
            upper = float(tp_price) if tp_price else mid_price * 1.02
        except Exception:
            self.notify("Enter valid Price/Amount/SL/TP to start bot!", severity="error")
            return
        
        bot_id = self.strategy_manager.start_grid_bot(
            inst_id=self.instrument_id,
            lower=lower,
            upper=upper,
            grids=5,
            investment=investment
        )

        self.bot_worker = asyncio.create_task(self._run_bot_execution_loop(bot_id))
        self.notify(f"Grid Bot Started for {self.instrument_id}!", title="Strategy Active")
        self.log_action(f"[cyan]Strategy Engine: Bot {bot_id} launched at ${mid_price:.2f}[/cyan]")
        self.update_bot_ui()

    def action_stop_bot(self) -> None:
        """Stops all active strategy bots."""
        count = self.strategy_manager.stop_all()
        if self.bot_worker:
            self.bot_worker.cancel()
        
        self.notify(f"Stopped {count} active bots.", title="Strategy Halted")
        self.log_action("[red]Strategy Engine: All bots stopped.[/red]")
        self.update_bot_ui()

    def update_bot_ui(self) -> None:
        """Updates the Grid Bot panel labels."""
        summary = self.strategy_manager.get_status_summary()
        status_color = "green" if summary["status"] == "ACTIVE" else "red"
        
        self.query_one("#bot-status", Static).update(f"Engine Status: [bold {status_color}]{summary['status']}[/bold {status_color}]")
        self.query_one("#bot-metrics", Static).update(f"Active Bots: {summary['count']} | Strategy PnL: ${summary['pnl']:.2f}")

    async def _run_bot_execution_loop(self, bot_id: str) -> None:
        """Background loop to process market ticks through the strategy engine."""
        bot = self.strategy_manager.active_bots.get(bot_id)
        if not bot:
            return

        while bot_id in self.strategy_manager.active_bots:
            try:
                price = float(self.current_price)
                signal = bot.process_tick(price)

                if signal:
                    sig_type, sig_px, sig_sz = signal
                    if sig_type == "LOG":
                        self.log_action(f"[dim]Bot {bot_id}: {sig_px}[/dim]")
                    elif sig_type in ["BUY", "SELL"]:
                        self.log_action(f"[bold yellow]Bot {sig_type} Signal: {sig_sz:.4f} @ {sig_px}[/bold yellow]")
                        # Execute live order via Private Client
                        self.run_worker(self._execute_order_task(
                            side=sig_type.lower(),
                            ord_type="limit",
                            size=str(sig_sz),
                            price=str(sig_px),
                            tp=None,
                            sl=None
                        ))
                
                await asyncio.sleep(1) # Check every second
            except Exception as e:
                logging.error(f"Error in bot execution loop: {e}")
                await asyncio.sleep(2)

    def refresh_chart(self) -> None:
        """Fetches and renders the ASCII chart for the current pair and timeframe asynchronously."""
        async def load_task():
            try:
                # Run the blocking network call and ASCII rendering in a separate thread pool
                data = await asyncio.to_thread(
                    OKXChartEngine.fetch_candles,
                    inst_id=self.instrument_id,
                    bar=self.current_timeframe,
                    limit=80
                )
                chart_str = await asyncio.to_thread(
                    OKXChartEngine.render_ascii_chart,
                    data,
                    self.instrument_id,
                    self.current_timeframe,
                    width=120,
                    height=16
                )
                from rich.text import Text
                # Clean ANSI output and use Rich to parse it correctly
                cleaned_chart = "\n".join(line.rstrip() for line in chart_str.splitlines())
                self.query_one("#ascii-chart-view", Static).update(Text.from_ansi(cleaned_chart))
            except Exception as e:
                logging.warning(f"Could not update candlestick chart widget: {e}")

        self.run_worker(load_task)

    async def _execute_order_task(self, side: str, ord_type: str, size: str, price: str, tp: str, sl: str) -> None:
        from okx_private import OKXPrivateClient

        self.notify(f"Submitting {side.upper()} {ord_type} order...", title="Executing")
        self.log_action(f"[yellow]Submitting {side.upper()} {ord_type} order (sz: {size}) [TP: {tp or 'None'}, SL: {sl or 'None'}]...[/yellow]")

        result = await asyncio.to_thread(
            OKXPrivateClient.place_order,
            inst_id=self.instrument_id,
            side=side,
            order_type=ord_type,
            sz=size,
            px=price if ord_type == "limit" else None,
            tp_trigger_px=tp if tp else None,
            sl_trigger_px=sl if sl else None
        )

        code = result.get("code")
        if code == "0":
            data = result.get("data", [{}])[0]
            ord_id = data.get("ordId", "Unknown")
            self.notify(f"Order placed successfully! ID: {ord_id}", severity="information", title="Success")
            self.log_action(f"[green]SUCCESS: Order ID {ord_id} placed.[/green]")
        else:
            msg = result.get("msg", "Unknown error")
            self.notify(f"Order failed [{code}]: {msg}", severity="error", title="API Error")
            self.log_action(f"[red]FAILED [{code}]: {msg}[/red]")

    def _start_terminal_services(self) -> None:
        self.set_interval(0.1, self.update_header_display)
        self.set_interval(5.0, self.update_portfolio_balance)
        self.set_interval(5.0, self.update_open_orders_and_positions)  # Poll open orders & positions every 5s
        self.set_interval(30.0, self.refresh_chart)  # Auto-refresh chart every 30 seconds
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
                logging.debug(f"Could not update portfolio balance widget: {e}")

    async def update_open_orders_and_positions(self) -> None:
        from okx_private import OKXPrivateClient

        # Fetch pending orders and positions concurrently or sequentially via thread
        orders_res = await asyncio.to_thread(OKXPrivateClient.get_pending_orders)
        pos_res = await asyncio.to_thread(OKXPrivateClient.get_positions)

        output_lines = []

        # Parse Pending Orders
        if orders_res.get("code") == "0":
            orders = orders_res.get("data", [])
            if orders:
                output_lines.append("[bold yellow]Resting Orders:[/bold yellow]")
                for o in orders[:3]:  # Show top 3
                    inst = o.get("instId")
                    side = o.get("side").upper()
                    px = o.get("px")
                    sz = o.get("sz")
                    output_lines.append(f"  • {inst} | {side} {sz} @ {px}")
            else:
                output_lines.append("[dim]No open resting orders[/dim]")
        else:
            output_lines.append("[red]Error fetching orders[/red]")

        output_lines.append("")

        # Parse Positions
        if pos_res.get("code") == "0":
            positions = pos_res.get("data", [])
            active_pos = [p for p in positions if float(p.get("pos", 0)) != 0]
            if active_pos:
                output_lines.append("[bold cyan]Active Positions:[/bold cyan]")
                for p in active_pos:
                    inst = p.get("instId")
                    pos_sz = p.get("pos")
                    pnl = float(p.get("upl", 0))
                    pnl_color = "green" if pnl >= 0 else "red"
                    output_lines.append(f"  • {inst} | Size: {pos_sz} | PnL: [{pnl_color}]${pnl:,.2f}[/{pnl_color}]")
            else:
                output_lines.append("[dim]No active trading positions[/dim]")
        else:
            output_lines.append("[dim]Positions feed idle (Cash/Spot mode)[/dim]")

        try:
            self.query_one("#positions-content", Static).update("\n".join(output_lines))
        except Exception as e:
            logging.debug(f"Could not update positions/orders widget: {e}")

    def log_action(self, message: str) -> None:
        """Appends status messages to the Execution Log window."""
        try:
            log_widget = self.query_one("#execution-log-content", Static)
            current_text = log_widget.renderable
            new_text = f"{message}\n{current_text}"
            lines = new_text.strip().split("\n")[:4]
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
                    for ask in raw_asks:
                        price, size, _, _ = ask[:4]
                        if float(size) == 0.0:
                            self.cached_asks = [a for a in self.cached_asks if a[0] != price]
                        else:
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

                self.cached_asks = sorted(self.cached_asks, key=lambda x: float(x[0]))[:5]
                self.cached_bids = sorted(self.cached_bids, key=lambda x: float(x[0]), reverse=True)[:5]

                asks = self.cached_asks
                bids = self.cached_bids

                asks_formatted = [f"[red]{float(a[0]):,.1f}  {float(a[1]):.4f}[/red]" for a in reversed(asks)]
                bids_formatted = [f"[green]{float(b[0]):,.1f}  {float(b[1]):.4f}[/green]" for b in bids]

                asks_text = "Asks (Sells) [Price / Amt]\n" + ("\n".join(asks_formatted) if asks_formatted else "Waiting...")
                bids_text = "Bids (Buys) [Price / Amt]\n" + ("\n".join(bids_formatted) if bids_formatted else "Waiting...")

                try:
                    self.query_one("#order-book-asks", Static).update(asks_text)
                    self.query_one("#order-book-bids", Static).update(bids_text)
                    if asks and bids:
                        spread = float(asks[0][0]) - float(bids[0][0])
                        self.query_one("#order-book-mid", Static).update(f"[bold white]Spread: {spread:.2f}[/bold white]")
                except Exception as e:
                    logging.debug(f"Order book update skipped during shutdown: {e}")

        elif channel == "trades":
            for trade in data:
                price = float(trade.get("px", 0))
                size = float(trade.get("sz", 0))
                side = trade.get("side", "buy")
                self.cached_trades.insert(0, {"price": price, "size": size, "side": side})

            self.cached_trades = self.cached_trades[:10]

            trade_lines = []
            for t in self.cached_trades:
                color = "green" if t["side"] == "buy" else "red"
                trade_lines.append(f"[{color}]{t['price']:,.1f} | {t['size']:.4f}[/{color}]")

            trades_text = "Price (USD)  Amount\n" + ("\n".join(trade_lines) if trade_lines else "No Trades")
            try:
                self.query_one("#last-trades-content", Static).update(trades_text)
            except Exception as e:
                logging.debug(f"Trade feed update skipped during shutdown: {e}")

    def update_header_display(self) -> None:
        header_widget = self.query_one("#header-bar", Static)
        header_widget.update(
            f" OXX TUI > {self.instrument_id} [dim]│[/dim] Price: [bold green]{self.current_price}[/bold green] "
            f"[dim]│[/dim] High: {self.high_24h} [dim]│[/dim] Low: {self.low_24h} [dim]│[/dim] Vol: {self.volume_24h}"
        )

if __name__ == "__main__":
    app = OKXTerminalApp()
    app.run()
