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
from strategy_engine import StrategyManager, OKXGridValidator

# Set logging to INFO to see our new singleton traces
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

WATCHLIST = [
    "BTC-USD", "HYPE-USD", "SOL-USD", "ETH-USD", "JUP-USD",
    "JTO-USD", "APT-USD", "PAXG-USD", "TRX-USD", "SHIB-USD",
    "RENDER-USD", "OP-USD", "ATOM-USD", "LTC-USD",
    "NEAR-USD", "UNI-USD", "LINK-USD", "ADA-USD", "AVAX-USD",
    "XRP-USD", "SUI-USD", "DOGE-USD", "BNB-USD", "USDT-USD"
]

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
    """[TERMUX SINGLETON TEST VERSION] Specialized to prevent freezes on mobile."""

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
        self.grid_validator = OKXGridValidator()
        self.grid_type = "arithmetic"
        self.bot_worker = None
        self.session_fills = []
        self.session_pnl = 0.0
        self.portfolio_balances = {} 
        self.telemetry_data = {} 

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
        height: 1fr;
        overflow-y: auto;
        scrollbar-size: 0 0;
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
        min-height: 10;
        padding: 1;
        margin: 1;
        background: #000000;
    }

    #left-column {
        width: 54; 
    }

    #left-sidebar {
        height: auto;
        border: solid #ffcc00;
    }

    Button.bot-start-btn {
        background: #000000;
        color: #00ff66; 
        border: solid #00ff66;
        width: 100%;
        margin-top: 1;
    }
    Button.bot-start-btn:hover {
        background: #00ff66;
        color: #000000;
    }

    Button.bot-stop-btn {
        background: #000000;
        color: #ff3333;
        border: solid #ff3333;
        width: 100%;
        margin-top: 1;
    }
    Button.bot-stop-btn:hover {
        background: #ff3333;
        color: #000000;
    }

    #bot-panel {
        height: auto;
        min-height: 34; 
        border: solid #ffcc00;
        padding: 1;
        margin: 1;
        background: #000000;
    }

    #right-main {
        width: 1fr;
        height: auto;
        border: solid #ffcc00;
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

    .bot-row {
        height: auto;
        margin-bottom: 1;
    }

    .bot-row Button {
        width: 1fr;
        margin: 0 1;
    }

    .telemetry-row {
        height: 1;
        margin-bottom: 0;
        text-wrap: nowrap;
    }

    Button {
        background: #111111;
        color: #ffcc00;
        border: solid #ffcc00;
    }

    Button:hover {
        background: #ffcc00;
        color: #000000;
        border: solid;
    }

    Button.buy-btn {
        background: #000000;
        color: #3399ff;
        border: solid #3399ff;
    }
    Button.buy-btn:hover {
        background: #3399ff;
        color: #000000;
    }

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
        height: auto;
        min-height: 12;
        margin: 1;
    }

    #history-panel {
        height: 12;
        padding: 1;
        background: #000000;
        border: solid #ffcc00;
        margin-top: 1;
    }

    #chart-container {
        height: auto;
        padding: 1;
        background: #000000;
        border: solid #ffcc00;
        margin-top: 1;
        layout: vertical;
    }

    .chart-view {
        width: 135;
        text-wrap: nowrap;
        text-overflow: clip;
        overflow: hidden;
        border: solid #ffcc00;
        margin-bottom: 1;
    }

    #chart-price {
        height: 22;
    }

    #chart-trend {
        height: 12;
    }

    #chart-momentum {
        height: 10;
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

    Toast {
        border: solid #ffcc00;
        background: #000000;
        color: #ffffff;
    }

    ScrollBar {
        background: #000000;
        color: #ffcc00;
    }

    .pct-bar {
        height: 3;
        margin-top: 1;
        layout: horizontal;
    }

    .pct-btn {
        width: 1fr;
        height: 3;
        margin: 0 1;
        background: #000000;
        color: #ffcc00;
        border: solid #333333;
        min-width: 5;
    }

    .pct-btn:hover {
        background: #ffcc00;
        color: #000000;
        border: solid;
    }
    """

    current_price = reactive("Connecting...")
    high_24h = reactive("---")
    low_24h = reactive("---")
    volume_24h = reactive("---")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f" OXX TUI > {getattr(self, 'current_pair', 'BTC-USD')} | Loading Ticker Feed...", id="header-bar")

        with VerticalScroll(id="page-viewport"):
            with Horizontal(classes="row"):
                with Vertical(id="left-column"):
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
                        with Horizontal(classes="pct-bar"):
                            yield Button("25%", id="pct-25", classes="pct-btn")
                            yield Button("50%", id="pct-50", classes="pct-btn")
                            yield Button("75%", id="pct-75", classes="pct-btn")
                            yield Button("100%", id="pct-100", classes="pct-btn")
                        yield Static("Total (USD Estimate):")
                        yield Input(placeholder="$0.00", id="total-input", disabled=True)
                        yield Static("[dim]Advanced Risk Management (TP/SL)[/dim]")
                        yield Input(placeholder="Take-Profit Price...", id="tp-input")
                        yield Input(placeholder="Stop-Loss Price...", id="sl-input")
                        yield Button("BUY (LONG)", variant="success", classes="buy-btn")
                        yield Button("SELL (SHORT)", variant="error", classes="sell-btn")
                        yield Static("[dim]System Settings:[/dim]")
                        yield Button(" MANAGE API KEYS", id="manage-keys-btn")

                    with Vertical(classes="panel", id="bot-panel"):
                        yield Static("[bold #ffcc00]Strategy Control Panel[/bold #ffcc00]")
                        yield Static("Engine Status: [bold red]IDLE[/bold red]", id="bot-status")
                        yield Static("Active Bots: 0 | Session PnL: $0.00", id="bot-metrics")
                        yield Static("[dim]Bot Range (Lower - Upper):[/dim]")
                        yield Input(placeholder="Lower Price...", id="bot-lower-input")
                        yield Input(placeholder="Upper Price...", id="bot-upper-input")
                        yield Static("[dim]Strategy Parameters:[/dim]")
                        yield Button("Grid Type: ARITHMETIC", id="grid-type-btn")
                        yield Static("[dim]Grid Count:[/dim]")
                        yield Input(placeholder="5", id="grid-count-input")
                        yield Static("[dim]DCA Drop %:[/dim]")
                        yield Input(placeholder="2.0", id="dca-drop-input")
                        yield Button("START GRID BOT", variant="success", id="start-grid-btn", classes="buy-btn")
                        yield Button("START DCA BOT", variant="success", id="start-dca-btn", classes="buy-btn")
                        yield Button("STOP ALL BOTS", variant="error", id="stop-bot-btn", classes="sell-btn")

                    with Vertical(classes="sub-panel positions-container", id="positions-panel"):
                        yield Static("[bold #ffcc00]Active Strategy Orders & Positions[/bold #ffcc00]")
                        yield Static("Scanning for open orders and positions...", id="positions-content")

                with Vertical(classes="panel", id="right-main"):
                    with Vertical(classes="sub-panel", id="chart-container"):
                        yield Static("[bold cyan]Candlestick Price Action[/bold cyan]")
                        with Horizontal(classes="timeframe-bar"):
                            yield Button("1m", id="tf-1m", classes="tf-btn")
                            yield Button("5m", id="tf-5m", classes="tf-btn")
                            yield Button("15m", id="tf-15m", classes="tf-btn")
                            yield Button("1H", id="tf-1h", classes="tf-btn")
                            yield Button("1D", id="tf-1d", classes="tf-btn")
                        yield Static("Loading Price...", id="chart-price", classes="chart-view")
                        yield Static("Loading Trend...", id="chart-trend", classes="chart-view")
                        yield Static("Loading Momentum...", id="chart-momentum", classes="chart-view")

                    yield Static("[bold green]Market Depth & Execution Feed[/bold green]")
                    with Horizontal(classes="sub-grid"):
                        with Vertical(classes="sub-panel", id="order-book-panel"):
                            yield Static("[bold cyan]Order Book[/bold cyan]")
                            yield Static("Asks (Sells)\n---------------------\nWaiting for depth...", id="order-book-asks")
                            yield Static("[bold green]Spread / Mid-Price[/bold green]", id="order-book-mid")
                            yield Static("Bids (Buys)\n---------------------\nWaiting for depth...", id="order-book-bids")
                        with Vertical(classes="sub-panel", id="last-trades-panel"):
                            yield Static("[bold yellow]Last Trades[/bold yellow]")
                            yield Static("Price (USD)  Amount  Time\n---------------------------------", id="last-trades-header")
                            yield Static("Waiting for trade stream...", id="last-trades-content")

                    yield Static("[bold #ffcc00]Onyx Ticker Board (Live Market Hub)[/bold #ffcc00]")
                    with Horizontal(classes="sub-grid"):
                        with Vertical(classes="sub-panel", id="hub-a"):
                            yield Static("[bold cyan]MARKET HUB A[/bold cyan]")
                            yield Static("Asset        Price       24H %    RNG %", classes="telemetry-row")
                            yield Static("------------------------------------------", classes="telemetry-row")
                            yield Static("Loading Hub A...", id="hub-a-content")
                        with Vertical(classes="sub-panel", id="hub-b"):
                            yield Static("[bold cyan]MARKET HUB B[/bold cyan]")
                            yield Static("Asset        Price       24H %    RNG %", classes="telemetry-row")
                            yield Static("------------------------------------------", classes="telemetry-row")
                            yield Static("Loading Hub B...", id="hub-b-content")

                    yield Static("[bold #3399ff]Session Activity & Execution Hub[/bold #3399ff]")
                    with Horizontal(classes="sub-grid"):
                        with Vertical(classes="sub-panel", id="history-panel"):
                            yield Static("[bold #3399ff]Order History & Fills[/bold #3399ff]")
                            yield Static("Waiting for session fills...", id="history-content")
                        with Vertical(classes="sub-panel log-container", id="log-panel"):
                            yield Static("[bold magenta]Execution & Order Log[/bold magenta]")
                            yield Static("System initialized. Waiting for actions...", id="execution-log-content")

        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "instrument-search-input":
            new_inst = event.value.strip().upper().replace("/", "-")
            if not new_inst: return
            if " " in new_inst: new_inst = new_inst.replace(" ", "-")
            if "-" not in new_inst: new_inst = f"{new_inst}-USD"
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
            tf_map = {"tf-1m": "1m", "tf-5m": "5m", "tf-15m": "15m", "tf-1h": "1H", "tf-1d": "1D"}
            self.current_timeframe = tf_map.get(button_id, "15m")
            self.notify(f"Switching timeframe to {self.current_timeframe}", title="Chart Update")
            self.refresh_chart()
            return

        if button_id == "save_btn": return
        if button_id == "start-grid-btn": self.action_start_bot(strategy_type="GRID"); return
        if button_id == "start-dca-btn": self.action_start_bot(strategy_type="DCA"); return
        if button_id == "stop-bot-btn": self.action_stop_bot(); return
        if button_id == "grid-type-btn":
            self.grid_type = "geometric" if self.grid_type == "arithmetic" else "arithmetic"
            event.button.label = f"Grid Type: {self.grid_type.upper()}"
            return
        if button_id == "manage-keys-btn": self.action_manage_keys(); return
        if button_id and button_id.startswith("pct-"):
            pct = float(button_id.split("-")[1]) / 100.0
            self.action_quick_load_amount(pct); return

        price_val = self.query_one("#price-input", Input).value.strip()
        amount_val = self.query_one("#amount-input", Input).value.strip()
        tp_val = self.query_one("#tp-input", Input).value.strip()
        sl_val = self.query_one("#sl-input", Input).value.strip()

        if not amount_val:
            self.notify("Please enter an order amount!", severity="error", title="Order Error")
            return

        ord_type = "limit" if price_val else "market"
        side = "buy" if event.button.label.text.startswith("BUY") else "sell"
        self.run_worker(self._execute_order_task(side, ord_type, amount_val, price_val, tp_val, sl_val, tag="Manual"))

    def action_switch_instrument(self, new_inst: str) -> None:
        if self.instrument_id == new_inst: return
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
            logging.warning(f"Could not clear trades widget on switch: {e}", exc_info=True)

        self.current_price = "Connecting..."
        if self.bg_worker and not self.bg_worker.done(): self.bg_worker.cancel()

        self.client = OKXPublicClient(instrument_id=new_inst, callback=self.handle_ws_data)
        self.bg_worker = asyncio.create_task(self.client.connect_market_streams())

        self.refresh_chart()
        self.notify(f"Successfully tuned to {new_inst}", title="Feed Active")

    def action_start_bot(self, strategy_type: str = "GRID") -> None:
        try:
            curr_px_str = str(self.current_price).replace(",", "")
            mid_price = float(curr_px_str)
            amount_str = self.query_one("#amount-input", Input).value.strip()
            if not amount_str:
                self.notify("Order amount/investment required to start bot!", severity="error")
                return
            investment = float(amount_str)

            if strategy_type == "GRID":
                grid_count_str = self.query_one("#grid-count-input", Input).value.strip()
                grids = int(grid_count_str) if grid_count_str else 5
                lower_str = self.query_one("#bot-lower-input", Input).value.strip()
                upper_str = self.query_one("#bot-upper-input", Input).value.strip()
                lower = float(lower_str) if lower_str else mid_price * 0.98
                upper = float(upper_str) if upper_str else mid_price * 1.02
                success, msg = self.grid_validator.validate_setup(lower, upper, grids, investment, mid_price)
                if not success:
                    self.notify(msg, severity="error", title="Validation Error")
                    self.log_action(f"[red]{msg}[/red]")
                    return
                bot_id = self.strategy_manager.start_grid_bot(self.instrument_id, lower, upper, grids, investment, self.grid_type)
            else:
                drop_pct_str = self.query_one("#dca-drop-input", Input).value.strip()
                drop_pct = float(drop_pct_str) if drop_pct_str else 2.0
                bot_id = self.strategy_manager.start_dca_bot(self.instrument_id, investment, drop_pct)

            self.bot_worker = asyncio.create_task(self._run_bot_execution_loop(bot_id))
            self.notify(f"{strategy_type} Bot Started for {self.instrument_id}!", title="Strategy Active")
            self.log_action(f"[cyan]Strategy Engine: {strategy_type} Bot {bot_id} launched @ ${mid_price:.2f}[/cyan]")
            self.update_bot_ui()
        except Exception as e:
            self.notify(f"Invalid parameters: {e}", severity="error")
            logging.error(f"Bot start failed: {e}", exc_info=True)

    def action_stop_bot(self) -> None:
        count = self.strategy_manager.stop_all()
        if self.bot_worker: self.bot_worker.cancel()
        self.notify(f"Stopped {count} active bots.", title="Strategy Halted")
        self.log_action("[red]Strategy Engine: All bots stopped.[/red]")
        self.update_bot_ui()

    def action_manage_keys(self) -> None:
        self.push_screen(AuthModal(), self.handle_auth_result)

    def action_quick_load_amount(self, percentage: float) -> None:
        try:
            base_asset, quote_asset = self.instrument_id.split("-")
            curr_px_str = str(self.current_price).replace(",", "")
            curr_px = float(curr_px_str) if curr_px_str != "Connecting..." else 1.0
            price_input_widget = self.query_one("#price-input", Input)
            price_input_val = price_input_widget.value.strip()
            target_px = float(price_input_val) if price_input_val else curr_px
            available_quote = self.portfolio_balances.get(quote_asset, 0.0)
            available_base = self.portfolio_balances.get(base_asset, 0.0)
            if available_quote > 0:
                spend_amount = available_quote * percentage
                buy_qty = spend_amount / target_px
                self.query_one("#amount-input", Input).value = f"{buy_qty:.6f}"
                self.query_one("#total-input", Input).value = f"{spend_amount:.2f}"
                if not price_input_val: price_input_widget.value = f"{target_px:.2f}"
                self.notify(f"Prepared to BUY with {int(percentage*100)}% of {quote_asset}", title="Quick Load")
            elif available_base > 0:
                sell_qty = available_base * percentage
                total_value = sell_qty * target_px
                self.query_one("#amount-input", Input).value = f"{sell_qty:.6f}"
                self.query_one("#total-input", Input).value = f"{total_value:.2f}"
                if not price_input_val: price_input_widget.value = f"{target_px:.2f}"
                self.notify(f"Prepared to SELL {int(percentage*100)}% of {base_asset}", title="Quick Load")
        except Exception as e:
            self.notify(f"Quick Load failed: {e}", severity="error")
            logging.error(f"Quick Load failed: {e}", exc_info=True)

    def update_bot_ui(self) -> None:
        summary = self.strategy_manager.get_status_summary()
        status_color = "green" if summary["status"] == "ACTIVE" else "red"
        try:
            curr_px_str = str(self.current_price).replace(",", "")
            curr_px = float(curr_px_str)
            live_pnl = self.strategy_manager.get_total_session_pnl({self.instrument_id: curr_px})
        except: live_pnl = 0.0
        self.query_one("#bot-status", Static).update(f"Engine Status: [bold {status_color}]{summary['status']}[/bold {status_color}]")
        self.query_one("#bot-metrics", Static).update(f"Active Bots: {summary['count']} | Session PnL: ${live_pnl:,.2f}\n[dim]{summary['details']}[/dim]")

    async def _run_bot_execution_loop(self, bot_id: str) -> None:
        bot = self.strategy_manager.active_bots.get(bot_id)
        if not bot: return
        while bot_id in self.strategy_manager.active_bots:
            try:
                price_str = str(self.current_price).replace(",", "")
                price = float(price_str)
                signal = bot.process_tick(price)
                if signal:
                    sig_type, sig_px, sig_sz, sig_tag = signal if len(signal) == 4 else (signal[0], signal[1], signal[2], "Bot")
                    if sig_type == "LOG": self.log_action(f"[dim]{sig_tag} {bot_id}: {sig_px}[/dim]")
                    elif sig_type in ["BUY", "SELL"]:
                        self.log_action(f"[bold yellow]{sig_tag} {sig_type} Signal: {sig_sz:.4f} @ {sig_px}[/bold yellow]")
                        self.run_worker(self._execute_order_task(sig_type.lower(), "limit", str(sig_sz), str(sig_px), None, None, sig_tag, bot_id))
                self.update_bot_ui()
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error in bot execution loop: {e}", exc_info=True)
                await asyncio.sleep(2)

    def refresh_chart(self) -> None:
        """Updated with Singleton Worker pattern to prevent Termux freezes."""
        async def load_task():
            try:
                logging.info(f"[TERMUX-DEBUG] Chart Render START for {self.instrument_id} ({self.current_timeframe})")
                data = await asyncio.to_thread(OKXChartEngine.fetch_candles, self.instrument_id, self.current_timeframe, 80)
                logging.info(f"[TERMUX-DEBUG] Data fetched. Rendering views...")
                
                close_prices = data["close"]
                ema9 = StrategyManager.calculate_ema(close_prices, 9)
                ema21 = StrategyManager.calculate_ema(close_prices, 21)
                rsi = StrategyManager.calculate_rsi(close_prices, 14)

                price_str = await asyncio.to_thread(OKXChartEngine.render_price_view, data, self.instrument_id, self.current_timeframe, 130, 20)
                trend_str = await asyncio.to_thread(OKXChartEngine.render_trend_view, data, 130, 10, ema9, ema21)
                momentum_str = await asyncio.to_thread(OKXChartEngine.render_momentum_view, data, 130, 8, rsi)

                from rich.text import Text
                self.query_one("#chart-price", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in price_str.splitlines())))
                self.query_one("#chart-trend", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in trend_str.splitlines())))
                self.query_one("#chart-momentum", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in momentum_str.splitlines())))
                logging.info(f"[TERMUX-DEBUG] Chart Render COMPLETE.")
            except Exception as e:
                logging.warning(f"Could not update candlestick chart widget: {e}", exc_info=True)

        # exclusive=True is the key! It cancels any existing worker with the name "chart_update"
        self.run_worker(load_task, name="chart_update", exclusive=True)

    async def _execute_order_task(self, side: str, ord_type: str, size: str, price: str, tp: str, sl: str, tag: str = "Manual", bot_id: str = None) -> None:
        from okx_private import OKXPrivateClient
        self.notify(f"Submitting {side.upper()} {ord_type} order...", title="Executing")
        result = await asyncio.to_thread(OKXPrivateClient.place_order, self.instrument_id, side, ord_type, size, price, tp, sl)
        code = result.get("code")
        if code == "0":
            data = result.get("data", [{}])[0]
            ord_id = data.get("ordId", "Unknown")
            exec_px = price if price else str(self.current_price).replace(",", "")
            import datetime
            fill = {"time": datetime.datetime.now().strftime("%H:%M:%S"), "inst": self.instrument_id, "side": side.upper(), "sz": size, "px": exec_px, "tag": tag}
            self.session_fills.insert(0, fill)
            self.session_fills = self.session_fills[:20]
            if bot_id: self.strategy_manager.update_bot_fill(bot_id, side, float(exec_px), float(size))
            self.notify(f"Order placed successfully! ID: {ord_id}", severity="information", title="Success")
            self.update_history_display(); self.update_bot_ui()
        else:
            msg = result.get("msg", "Unknown error")
            self.notify(f"Order failed [{code}]: {msg}", severity="error", title="API Error")

    def update_history_display(self) -> None:
        lines = []
        for f in self.session_fills:
            color = "green" if f["side"] == "BUY" else "red"
            tag_color = "#3399ff" if f["tag"] == "Manual" else "#ffcc00"
            lines.append(f"[{tag_color}]{f['tag']}[/{tag_color}] | {f['time']} | [{color}]{f['side']}[/{color}] {f['sz']} @ {f['px']}")
        history_text = "\n".join(lines) if lines else "Waiting for session fills..."
        try: self.query_one("#history-content", Static).update(history_text)
        except Exception as e: logging.warning(f"History display update skipped: {e}", exc_info=True)

    async def hydrate_fill_history(self) -> None:
        from okx_private import OKXPrivateClient
        try:
            result = await asyncio.to_thread(OKXPrivateClient.get_fill_history, limit=40)
            if result.get("code") == "0":
                fills = result.get("data", [])
                for f in reversed(fills):
                    import datetime
                    ts = int(f.get("fillTime", 0))
                    time_str = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
                    fill = {"time": time_str, "inst": f.get("instId"), "side": f.get("side").upper(), "sz": f.get("fillSz"), "px": f.get("fillPx"), "tag": "ACCOUNT"}
                    exists = any(x["time"] == time_str and x["px"] == fill["px"] for x in self.session_fills)
                    if not exists: self.session_fills.insert(0, fill)
                self.session_fills = self.session_fills[:40]
                self.update_history_display()
        except Exception as e: logging.error(f"Hydration critical failure: {e}", exc_info=True)

    def _start_terminal_services(self) -> None:
        self.set_interval(0.1, self.update_header_display)
        self.set_interval(5.0, self.update_portfolio_balance)
        self.set_interval(5.0, self.update_open_orders_and_positions)
        self.set_interval(30.0, self.refresh_chart)
        self.client = OKXPublicClient(instrument_id=self.instrument_id, watchlist=WATCHLIST, callback=self.handle_ws_data)
        self.bg_worker = asyncio.create_task(self.client.connect_market_streams())
        self.run_worker(self.hydrate_fill_history())

    async def update_portfolio_balance(self) -> None:
        from okx_private import OKXPrivateClient
        result = await asyncio.to_thread(OKXPrivateClient.get_account_balance)
        if result.get("code") == "0":
            details = result.get("data", [{}])[0].get("details", [])
            bal_lines = []
            self.portfolio_balances = {}
            for asset in details:
                ccy = asset.get("ccy"); avail = float(asset.get("availBal", 0))
                self.portfolio_balances[ccy] = avail
                if avail > 0: bal_lines.append(f"[bold white]{ccy}:[/bold white] {avail:,.4f}")
            balance_text = "\n".join(bal_lines) if bal_lines else "No active balances"
            try: self.query_one("#portfolio-balance", Static).update(balance_text)
            except Exception as e: logging.warning(f"Could not update portfolio balance widget: {e}", exc_info=True)

    async def update_open_orders_and_positions(self) -> None:
        from okx_private import OKXPrivateClient
        orders_res = await asyncio.to_thread(OKXPrivateClient.get_pending_orders)
        pos_res = await asyncio.to_thread(OKXPrivateClient.get_positions)
        output_lines = []
        if orders_res.get("code") == "0":
            orders = orders_res.get("data", [])
            if orders:
                output_lines.append("[bold yellow]Resting Orders:[/bold yellow]")
                for o in orders[:3]: output_lines.append(f"  • {o.get('instId')} | {o.get('side').upper()} {o.get('sz')} @ {o.get('px')}")
            else: output_lines.append("[dim]No open resting orders[/dim]")
        if pos_res.get("code") == "0":
            positions = pos_res.get("data", [])
            active_pos = [p for p in positions if float(p.get("pos", 0)) != 0]
            if active_pos:
                output_lines.append("\n[bold cyan]Active Positions:[/bold cyan]")
                for p in active_pos:
                    pnl = float(p.get("upl", 0)); pnl_color = "green" if pnl >= 0 else "red"
                    output_lines.append(f"  • {p.get('instId')} | Size: {p.get('pos')} | PnL: [{pnl_color}]${pnl:,.2f}[/{pnl_color}]")
            else: output_lines.append("\n[dim]No active trading positions[/dim]")
        try: self.query_one("#positions-content", Static).update("\n".join(output_lines))
        except Exception as e: logging.warning(f"Could not update positions/orders widget: {e}", exc_info=True)

    def log_action(self, message: str) -> None:
        try:
            log_widget = self.query_one("#execution-log-content", Static)
            new_text = f"{message}\n{log_widget.renderable}"
            log_widget.update("\n".join(new_text.strip().split("\n")[:4]))
        except: logging.info(message)

    async def handle_ws_data(self, channel: str, data: list) -> None:
        if channel == "tickers":
            for ticker in data:
                inst_id = ticker.get("instId"); last = ticker.get("last", "0.0")
                if inst_id == self.instrument_id:
                    self.current_price = last
                    self.high_24h = ticker.get("high24h", "0.0")
                    self.low_24h = ticker.get("low24h", "0.0")
                    self.volume_24h = ticker.get("vol24h", "0.0")
                if inst_id in WATCHLIST:
                    last_px = float(last); open_24h = float(ticker.get("open24h", 0))
                    change_pct = ((last_px - open_24h) / open_24h) * 100 if open_24h > 0 else 0.0
                    self.telemetry_data[inst_id] = {"last": f"{last_px:,.2f}", "change": f"{change_pct:+.2f}%", "high": float(ticker.get("high24h", 0)), "low": float(ticker.get("low24h", 0)), "raw_last": last_px}
            self.refresh_hubs()
        elif channel == "books":
            for book in data:
                action = book.get("action", "update")
                if action == "snapshot":
                    self.cached_asks = book.get("asks", [])[:5]
                    self.cached_bids = book.get("bids", [])[:5]
                else:
                    for ask in book.get("asks", []):
                        if float(ask[1]) == 0.0: self.cached_asks = [a for a in self.cached_asks if a[0] != ask[0]]
                        else:
                            found = False
                            for i, a in enumerate(self.cached_asks):
                                if a[0] == ask[0]: self.cached_asks[i] = ask; found = True; break
                            if not found: self.cached_asks.append(ask)
                    for bid in book.get("bids", []):
                        if float(bid[1]) == 0.0: self.cached_bids = [b for b in self.cached_bids if b[0] != bid[0]]
                        else:
                            found = False
                            for i, b in enumerate(self.cached_bids):
                                if b[0] == bid[0]: self.cached_bids[i] = bid; found = True; break
                            if not found: self.cached_bids.append(bid)
                self.cached_asks = sorted(self.cached_asks, key=lambda x: float(x[0]))[:5]
                self.cached_bids = sorted(self.cached_bids, key=lambda x: float(x[0]), reverse=True)[:5]
                asks_fmt = [f"[red]{float(a[0]):,.1f}  {float(a[1]):.4f}[/red]" for a in reversed(self.cached_asks)]
                bids_fmt = [f"[green]{float(b[0]):,.1f}  {float(b[1]):.4f}[/green]" for b in self.cached_bids]
                try:
                    self.query_one("#order-book-asks", Static).update("Asks (Sells) [Price / Amt]\n" + "\n".join(asks_fmt))
                    self.query_one("#order-book-bids", Static).update("Bids (Buys) [Price / Amt]\n" + "\n".join(bids_fmt))
                    if self.cached_asks and self.cached_bids:
                        self.query_one("#order-book-mid", Static).update(f"[bold white]Spread: {float(self.cached_asks[0][0]) - float(self.cached_bids[0][0]):.2f}[/bold white]")
                except Exception as e: logging.warning(f"Order book update skipped: {e}", exc_info=True)
        elif channel == "trades":
            for trade in data: self.cached_trades.insert(0, {"price": float(trade.get("px", 0)), "size": float(trade.get("sz", 0)), "side": trade.get("side", "buy")})
            self.cached_trades = self.cached_trades[:10]
            trade_lines = [f"[{'green' if t['side'] == 'buy' else 'red'}]{t['price']:,.1f} | {t['size']:.4f}[/]" for t in self.cached_trades]
            try: self.query_one("#last-trades-content", Static).update("Price (USD)  Amount\n" + "\n".join(trade_lines))
            except Exception as e: logging.warning(f"Trade feed update skipped: {e}", exc_info=True)

    def update_header_display(self) -> None:
        try: self.query_one("#header-bar", Static).update(f" OXX TUI > {self.instrument_id} [dim]│[/dim] Price: [bold green]{self.current_price}[/bold green] [dim]│[/dim] High: {self.high_24h} [dim]│[/dim] Low: {self.low_24h} [dim]│[/dim] Vol: {self.volume_24h}")
        except: pass

    def refresh_hub_content(self, inst_list, widget_id):
        lines = []
        for inst in inst_list:
            data = self.telemetry_data.get(inst, {"last": "---", "change": "---", "high": 0, "low": 0, "raw_last": 0})
            change_color = "#3399ff" if "+" in data["change"] else "#ff3333"
            if data["change"] == "---": change_color = "white"
            high = data.get("high", 0); low = data.get("low", 0); last = data.get("raw_last", 0)
            rng_pos_str = "---"; rng_color = "white"
            if high > low:
                rpi = ((last - low) / (high - low)) * 100
                rng_pos_str = f"{rpi:.1f}%"
                if rpi <= 30: rng_color = "#3399ff" 
                elif rpi >= 70: rng_color = "#ff3333"
                else: rng_color = "#ffffff"
            lines.append(f"{inst:<12} {data['last']:>10}  [{change_color}]{data['change']:>7}[/{change_color}]  [{rng_color}]{rng_pos_str:>6}[/{rng_color}]")
        try: self.query_one(widget_id, Static).update("\n".join(lines))
        except Exception as e: logging.warning(f"Unable To Retrieve RPI Calculation: {e}", exc_info=True)

    def refresh_hubs(self):
        self.refresh_hub_content(WATCHLIST[:12], "#hub-a-content")
        self.refresh_hub_content(WATCHLIST[12:], "#hub-b-content")

if __name__ == "__main__":
    app = OKXTerminalApp()
    app.run()
