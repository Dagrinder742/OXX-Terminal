import asyncio
import logging
import sys
import time
import math
import datetime
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
from accountant import PnLAccountant

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
        self.grid_validator = OKXGridValidator()
        self.grid_type = "arithmetic"
        self.bot_worker = None
        self.session_fills = []
        self.session_pnl = 0.0
        self.portfolio_balances = {} # {asset: available_balance}
        self.telemetry_data = {} # {instId: {last: str, change: str}}
        self.accountant = PnLAccountant() # Our mathematical co-pilot
        self.simulation_mode = True # SAFETY PIN: Set to False only when ready for real risk
        self.resize_timer = None # Debounce timer for smooth liquid scaling

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
        width: 1fr;
        min-width: 48;
        max-width: 60;
        height: auto;
    }

    #left-sidebar {
        height: auto;
        border: solid #ffcc00;
    }

    /* Bot Control Buttons */
    Button.bot-start-btn {
        background: #000000;
        color: #00ff66; /* Or your preferred green */
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
        min-height: 34; /* Increased to accommodate Range inputs */
        border: solid #ffcc00;
        padding: 1;
        margin: 1;
        background: #000000;
    }

    #right-main {
        width: 4fr;
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

    #manage-keys-btn, #grid-type-btn {
        width: 100%;
    }

    Button.buy-btn {
        background: #000000;
        color: #3399ff;
        border: solid #3399ff;
        width: 100%;
    }
    Button.buy-btn:hover {
        background: #3399ff;
        color: #000000;
    }

    Button.sell-btn {
        background: #000000;
        color: #ff3333;
        border: solid #ff3333;
        width: 100%;
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
        width: 100%;
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
        width: 100%;
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

    #tactical-preflight-box {
        margin-top: 1;
        padding: 0 1;
        border: double #333333;
        background: #080808;
        height: 6; /* Increased height to fit SL row */
    }

    .tactical-row {
        height: 1;
        margin-bottom: 0;
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

                # Left Column: Standard Vertical container
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

                        with Horizontal(classes="pct-bar"):
                            yield Button("25%", id="pct-25", classes="pct-btn")
                            yield Button("50%", id="pct-50", classes="pct-btn")
                            yield Button("75%", id="pct-75", classes="pct-btn")
                            yield Button("100%", id="pct-100", classes="pct-btn")

                        yield Static("Total (USD Estimate):")
                        yield Input(placeholder="$0.00", id="total-input", disabled=True)

                        with Vertical(id="tactical-preflight-box"):
                            yield Static("[bold #3399ff] Tactical Edge (Pre-Flight)[/bold #3399ff]", id="preflight-header")
                            yield Static("Est. Fee:  $0.00", id="preflight-fee", classes="tactical-row")
                            yield Static("Hurdle:    $0.00", id="preflight-hurdle", classes="tactical-row")
                            yield Static("Net TP:    $0.00", id="preflight-net-tp", classes="tactical-row")
                            yield Static("Net SL:    $0.00", id="preflight-net-sl", classes="tactical-row")

                        yield Static("[dim]Advanced Risk Management (TP/SL)[/dim]")
                        yield Input(placeholder="Take-Profit Price...", id="tp-input")
                        yield Input(placeholder="Stop-Loss Price...", id="sl-input")

                        yield Button("BUY (LONG)", variant="success", classes="buy-btn")
                        yield Button("SELL (SHORT)", variant="error", classes="sell-btn")
                        
                        yield Static("[dim]System Settings:[/dim]")
                        yield Button(" MANAGE API KEYS", id="manage-keys-btn")

                    # Bot Control Panel - FLATTENED ARCHITECTURE
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

                        # Vertical Stacked Buttons
                        yield Button("START GRID BOT", variant="success", id="start-grid-btn", classes="buy-btn")
                        yield Button("START DCA BOT", variant="success", id="start-dca-btn", classes="buy-btn")
                        yield Button("STOP ALL BOTS", variant="error", id="stop-bot-btn", classes="sell-btn")

                    # Open Orders & Positions Sub-Panel
                    with Vertical(classes="sub-panel positions-container", id="positions-panel"):
                        yield Static("[bold #ffcc00]Active Strategy Orders & Positions[/bold #ffcc00]")
                        yield Static("Scanning for open orders and positions...", id="positions-content")

                # Right Main Workspace: Candlestick Chart, Market Depth, Trades, and Activity
                with Vertical(classes="panel", id="right-main"):

                    # 1. Candlestick Chart Sub-Panel
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

                    # 2. Market Depth & Last Trades
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

                    # 3. Onyx Ticker Board (Live Watchlist)
                    yield Static("[bold #ffcc00]Onyx Ticker Board (Live Market Hub)[/bold #ffcc00]")
                    with Horizontal(classes="sub-grid", id="hub-master-container"):
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

                        with Vertical(classes="sub-panel", id="hub-c"):
                            yield Static("[bold cyan]MARKET HUB C[/bold cyan]")
                            yield Static("Asset        Price       24H %    RNG %", classes="telemetry-row")
                            yield Static("------------------------------------------", classes="telemetry-row")
                            yield Static("Loading Hub C...", id="hub-c-content")

                    # 4. Session Activity Hub
                    yield Static("[bold #3399ff]Session Activity & Execution Hub[/bold #3399ff]")
                    with Horizontal(classes="sub-grid"):
                        # Session Order History & Fills
                        with Vertical(classes="sub-panel", id="history-panel"):
                            yield Static("[bold #3399ff]Order History & Fills[/bold #3399ff]")
                            yield Static("Waiting for session fills...", id="history-content")

                        # Bottom Sub-Panel: Order Status / Activity Log
                        with Vertical(classes="sub-panel log-container", id="log-panel"):
                            yield Static("[bold magenta]Execution & Order Log[/bold magenta]")
                            yield Static("System initialized. Waiting for actions...", id="execution-log-content")

        yield Footer()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Reactively updates the Tactical Pre-Flight box as the user types."""
        if event.input.id in ["price-input", "amount-input", "tp-input", "sl-input"]:
            self.update_preflight_calculator()

    def on_resize(self, event) -> None:
        """Handles liquid layout state toggles with debouncing for performance."""
        # Cancel any pending refresh task
        if self.resize_timer:
            self.resize_timer.cancel()
        
        # Schedule a new refresh once resizing has 'settled' (300ms)
        self.resize_timer = self.set_timer(0.3, self.execute_liquid_refresh)

    def execute_liquid_refresh(self) -> None:
        """The heavy lift logic: only runs after resizing stops."""
        width = self.size.width
        try:
            hub_container = self.query_one("#hub-master-container")
            hub_c = self.query_one("#hub-c")

            # Adaptive Layout Logic
            if width > 190:
                # Wide Desktop: 3 Columns
                hub_container.styles.layout = "horizontal"
                hub_c.styles.display = "block"
            elif width > 110:
                # Standard Desktop: 2 Columns
                hub_container.styles.layout = "horizontal"
                hub_c.styles.display = "none"
            else:
                # Mobile/Termux: Vertical Stack
                hub_container.styles.layout = "vertical"
                hub_c.styles.display = "none"
            
            self.refresh_hubs()

            # 2. Trigger Chart Redraw at the new actual width
            self.refresh_chart()
        except Exception as e:
            logging.debug(f"Liquid refresh error: {e}")

    def update_preflight_calculator(self) -> None:
        try:
            price_val = self.query_one("#price-input", Input).value.strip()
            amount_val = self.query_one("#amount-input", Input).value.strip()
            tp_val = self.query_one("#tp-input", Input).value.strip()
            sl_val = self.query_one("#sl-input", Input).value.strip()

            # Handle current price defaulting
            if not price_val:
                curr_px_str = str(self.current_price).replace(",", "")
                price = float(curr_px_str) if curr_px_str != "Connecting..." else 0.0
            else:
                price = float(price_val.replace("$", "").replace(",", ""))

            amount = float(amount_val) if amount_val else 0.0
            tp = float(tp_val) if tp_val else None
            sl = float(sl_val) if sl_val else None

            metrics = self.accountant.calculate_preflight_metrics(price, amount, tp, sl)

            # Update Header with Tier Label
            self.query_one("#preflight-header", Static).update(f"[bold #3399ff] Tactical Edge ({self.accountant.tier_label})[/bold #3399ff]")

            self.query_one("#preflight-fee", Static).update(f"Est. Fee:  [bold #ff3333]${metrics['fee']:.4f}[/bold #ff3333]")
            self.query_one("#preflight-hurdle", Static).update(f"Hurdle:    [bold #3399ff]${metrics['break_even']:,.2f}[/bold #3399ff]")
            
            if metrics['net_tp'] > 0:
                self.query_one("#preflight-net-tp", Static).update(f"Net TP:    [bold #00ff66]${metrics['net_tp']:,.2f}[/bold #00ff66]")
            else:
                self.query_one("#preflight-net-tp", Static).update(f"Net TP:    $0.00")

            if metrics['net_sl'] < 0:
                self.query_one("#preflight-net-sl", Static).update(f"Net SL:    [bold #ff3333]${metrics['net_sl']:,.2f}[/bold #ff3333]")
            else:
                self.query_one("#preflight-net-sl", Static).update(f"Net SL:    $0.00")

        except:
            # Silently fail for partial input strings (like ".")
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "instrument-search-input":
            new_inst = event.value.strip().upper().replace("/", "-")
            if not new_inst:
                return

            if " " in new_inst:
                new_inst = new_inst.replace(" ", "-")

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
            tf_map = {"tf-1m": "1m", "tf-5m": "5m", "tf-15m": "15m", "tf-1h": "1H", "tf-1d": "1D"}
            self.current_timeframe = tf_map.get(button_id, "15m")
            self.notify(f"Switching timeframe to {self.current_timeframe}", title="Chart Update")
            self.refresh_chart()
            return

        if button_id == "save_btn":
            return

        if button_id == "start-grid-btn":
            self.action_start_bot(strategy_type="GRID")
            return

        if button_id == "start-dca-btn":
            self.action_start_bot(strategy_type="DCA")
            return

        if button_id == "stop-bot-btn":
            self.action_stop_bot()
            return

        if button_id == "grid-type-btn":
            self.grid_type = "geometric" if self.grid_type == "arithmetic" else "arithmetic"
            event.button.label = f"Grid Type: {self.grid_type.upper()}"
            return

        if button_id == "manage-keys-btn":
            self.action_manage_keys()
            return

        if button_id and button_id.startswith("pct-"):
            pct = float(button_id.split("-")[1]) / 100.0
            self.action_quick_load_amount(pct)
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

        self.run_worker(self._execute_order_task(side, ord_type, amount_val, price_val, tp_val, sl_val, tag="Manual"))

    def action_switch_instrument(self, new_inst: str) -> None:
        if self.instrument_id == new_inst:
            return

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

        if self.bg_worker and not self.bg_worker.done():
            self.bg_worker.cancel()

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

                # OKX Production-Grade Validation
                success, msg = self.grid_validator.validate_setup(
                    lower_price=lower,
                    upper_price=upper,
                    grid_count=grids,
                    total_investment=investment,
                    current_market_price=mid_price
                )

                if not success:
                    self.notify(msg, severity="error", title="Validation Error")
                    self.log_action(f"[red]{msg}[/red]")
                    return

                bot_id = self.strategy_manager.start_grid_bot(
                    inst_id=self.instrument_id,
                    lower=lower,
                    upper=upper,
                    grids=grids,
                    investment=investment,
                    grid_type=self.grid_type
                )
            else:
                drop_pct_str = self.query_one("#dca-drop-input", Input).value.strip()
                drop_pct = float(drop_pct_str) if drop_pct_str else 2.0

                bot_id = self.strategy_manager.start_dca_bot(
                    inst_id=self.instrument_id,
                    base_amount=investment,
                    drop_pct=drop_pct
                )

            self.bot_worker = asyncio.create_task(self._run_bot_execution_loop(bot_id))
            self.notify(f"{strategy_type} Bot Started for {self.instrument_id}!", title="Strategy Active")
            self.log_action(f"[cyan]Strategy Engine: {strategy_type} Bot {bot_id} launched @ ${mid_price:.2f}[/cyan]")
            self.update_bot_ui()

        except Exception as e:
            self.notify(f"Invalid parameters: {e}", severity="error")
            logging.error(f"Bot start failed: {e}", exc_info=True)
            return

    def action_stop_bot(self) -> None:
        count = self.strategy_manager.stop_all()
        if self.bot_worker:
            self.bot_worker.cancel()

        self.notify(f"Stopped {count} active bots.", title="Strategy Halted")
        self.log_action("[red]Strategy Engine: All bots stopped.[/red]")
        self.update_bot_ui()

    def action_manage_keys(self) -> None:
        """Allows re-authenticating and updating API credentials on the fly."""
        self.push_screen(AuthModal(), self.handle_auth_result)

    def action_quick_load_amount(self, percentage: float) -> None:
        """Calculates and fills the price, amount, and total based on available balance."""
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
                # BUY Side Logic
                spend_amount = available_quote * percentage
                buy_qty = spend_amount / target_px
                
                # Update TUI
                self.query_one("#amount-input", Input).value = f"{buy_qty:.6f}"
                self.query_one("#total-input", Input).value = f"{spend_amount:.2f}"
                if not price_input_val:
                    price_input_widget.value = f"{target_px:.2f}"
                
                self.notify(f"Prepared to BUY with {int(percentage*100)}% of {quote_asset}", title="Quick Load")
            
            elif available_base > 0:
                # SELL Side Logic
                sell_qty = available_base * percentage
                total_value = sell_qty * target_px
                
                # Update TUI
                self.query_one("#amount-input", Input).value = f"{sell_qty:.6f}"
                self.query_one("#total-input", Input).value = f"{total_value:.2f}"
                if not price_input_val:
                    price_input_widget.value = f"{target_px:.2f}"
                    
                self.notify(f"Prepared to SELL {int(percentage*100)}% of {base_asset}", title="Quick Load")
            
        except Exception as e:
            self.notify(f"Quick Load failed: {e}", severity="error")
            logging.error(f"Quick Load failed: {e}", exc_info=True)

    def update_bot_ui(self) -> None:
        summary = self.strategy_manager.get_status_summary()
        status_color = "green" if summary["status"] == "ACTIVE" else "red"
        
        try:
            curr_px_str = str(self.current_price).replace(",", "")
            curr_px = float(curr_px_str) if curr_px_str != "Connecting..." else 0.0
            
            # Aggregate total session score (Manual + Bots) from the Accountant
            # We pass the current price for unrealized calculation
            session_report = self.accountant.get_session_summary({self.instrument_id: curr_px})
            live_net = session_report["net"]
            
        except Exception as e:
            logging.warning(f"UI PnL update error: {e}")
            live_net = 0.0
            
        self.query_one("#bot-status", Static).update(f"Engine Status: [bold {status_color}]{summary['status']}[/bold {status_color}]")
        
        pnl_color = "#ffcc00" if live_net >= 0 else "#ff3333" # Gold if profit, Red if loss
        self.query_one("#bot-metrics", Static).update(
            f"Active Bots: {summary['count']} | Session Net: [bold {pnl_color}]${live_net:,.2f}[/bold {pnl_color}]\n"
            f"[dim]{summary['details']}[/dim]"
        )

    async def _run_bot_execution_loop(self, bot_id: str) -> None:
        bot = self.strategy_manager.active_bots.get(bot_id)
        if not bot:
            return

        while bot_id in self.strategy_manager.active_bots:
            try:
                price_str = str(self.current_price).replace(",", "")
                price = float(price_str)
                signal = bot.process_tick(price)

                if signal:
                    if len(signal) == 4:
                        sig_type, sig_px, sig_sz, sig_tag = signal
                    else:
                        sig_type, sig_px, sig_sz = signal
                        sig_tag = "Bot"

                    if sig_type == "LOG":
                        self.log_action(f"[dim]{sig_tag} {bot_id}: {sig_px}[/dim]")
                    elif sig_type in ["BUY", "SELL"]:
                        self.log_action(f"[bold yellow]{sig_tag} {sig_type} Signal: {sig_sz:.4f} @ {sig_px}[/bold yellow]")
                        self.run_worker(self._execute_order_task(
                            side=sig_type.lower(),
                            ord_type="limit",
                            size=str(sig_sz),
                            price=str(sig_px),
                            tp=None,
                            sl=None,
                            tag=sig_tag,
                            bot_id=bot_id
                        ))
                
                self.update_bot_ui()
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error in bot execution loop: {e}", exc_info=True)
                await asyncio.sleep(2)

    def refresh_chart(self) -> None:
        async def load_task():
            try:
                # Detect the actual width of the chart panel to prevent "Void" space
                chart_widget = self.query_one("#chart-price", Static)
                actual_width = chart_widget.content_size.width or 130
                
                data = await asyncio.to_thread(
                    OKXChartEngine.fetch_candles,
                    inst_id=self.instrument_id,
                    bar=self.current_timeframe,
                    limit=80
                )
                close_prices = data["close"]
                ema9 = StrategyManager.calculate_ema(close_prices, 9)
                ema21 = StrategyManager.calculate_ema(close_prices, 21)
                rsi = StrategyManager.calculate_rsi(close_prices, 14)

                price_str = await asyncio.to_thread(
                    OKXChartEngine.render_price_view,
                    data, self.instrument_id, self.current_timeframe, actual_width, 20
                )
                trend_str = await asyncio.to_thread(
                    OKXChartEngine.render_trend_view,
                    data, actual_width, 10, ema9, ema21
                )
                momentum_str = await asyncio.to_thread(
                    OKXChartEngine.render_momentum_view,
                    data, actual_width, 8, rsi
                )

                from rich.text import Text
                self.query_one("#chart-price", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in price_str.splitlines())))
                self.query_one("#chart-trend", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in trend_str.splitlines())))
                self.query_one("#chart-momentum", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in momentum_str.splitlines())))
            except Exception as e:
                logging.warning(f"Could not update candlestick chart widget: {e}", exc_info=True)

        self.run_worker(load_task, name="chart_update", exclusive=True)

    async def _execute_order_task(self, side: str, ord_type: str, size: str, price: str, tp: str, sl: str, tag: str = "Manual", bot_id: str = None) -> None:
        from okx_private import OKXPrivateClient

        if self.simulation_mode:
            self.notify(f"[SIM] {side.upper()} {ord_type} intercepted.", title="Sim Mode")
            self.log_action(f"[cyan]SIM MODE: {tag} would have placed {side.upper()} {size} @ {price or 'MKT'}[/cyan]")
            # Mock a successful fill for the Accountant to test the dashboard math
            exec_px = price if price else str(self.current_price).replace(",", "")
            self.accountant.record_confirmed_fill(self.instrument_id, side, float(exec_px), float(size), tag=f"SIM-{tag}")
            self.update_bot_ui()
            return

        self.notify(f"Submitting {side.upper()} {ord_type} order...", title="Executing")
        self.log_action(f"[yellow]{tag}: Submitting {side.upper()} {ord_type} order (sz: {size}) [TP: {tp or 'None'}, SL: {sl or 'None'}]...[/yellow]")

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
            exec_px = price if price else str(self.current_price).replace(",", "")
            
            import datetime
            fill = {
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "inst": self.instrument_id,
                "side": side.upper(),
                "sz": size,
                "px": exec_px,
                "tag": tag
            }
            self.session_fills.insert(0, fill)
            self.session_fills = self.session_fills[:20]
            
            if bot_id:
                try:
                    self.strategy_manager.update_bot_fill(bot_id, side, float(exec_px), float(size))
                except Exception as e:
                    logging.error(f"Failed to update bot fill: {e}", exc_info=True)

            # Update the Global Accountant Ledger
            try:
                self.accountant.record_confirmed_fill(self.instrument_id, side, float(exec_px), float(size), tag=tag)
            except Exception as e:
                logging.error(f"Accountant failed to record fill: {e}", exc_info=True)

            self.notify(f"Order placed successfully! ID: {ord_id}", severity="information", title="Success")
            self.log_action(f"[green]SUCCESS: {tag} Order ID {ord_id} placed.[/green]")
            self.update_history_display()
            self.update_bot_ui()
        else:
            msg = result.get("msg", "Unknown error")
            self.notify(f"Order failed [{code}]: {msg}", severity="error", title="API Error")
            self.log_action(f"[red]FAILED [{tag}]: {msg}[/red]")

    def update_history_display(self) -> None:
        lines = []
        for f in self.session_fills:
            color = "green" if f["side"] == "BUY" else "red"
            tag_color = "#3399ff" if f["tag"] == "Manual" else "#ffcc00"
            lines.append(
                f"[{tag_color}]{f['tag']}[/{tag_color}] | {f['time']} | "
                f"[{color}]{f['side']}[/{color}] {f['sz']} @ {f['px']}"
            )
        
        history_text = "\n".join(lines) if lines else "Waiting for session fills..."
        try:
            self.query_one("#history-content", Static).update(history_text)
        except Exception as e:
            logging.warning(f"History display update skipped: {e}", exc_info=True)

    async def hydrate_fill_history(self) -> None:
        """Fetches recent account fills from the REST API to populate the history panel on boot."""
        from okx_private import OKXPrivateClient
        self.log_action("[dim]Hydrating account trade history...[/dim]")
        
        try:
            result = await asyncio.to_thread(OKXPrivateClient.get_fill_history, limit=40)
            code = result.get("code")
            self.log_action(f"[dim]Fill API Response Code: {code}[/dim]")
            
            if code == "0":
                fills = result.get("data", [])
                self.log_action(f"[dim]Found {len(fills)} historical fills.[/dim]")
                
                for f in reversed(fills): # Older first
                    import datetime
                    ts = int(f.get("fillTime", 0))
                    time_str = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
                    
                    fill = {
                        "time": time_str,
                        "inst": f.get("instId"),
                        "side": f.get("side").upper(),
                        "sz": f.get("fillSz"),
                        "px": f.get("fillPx"),
                        "tag": "ACCOUNT"
                    }
                    
                    # Manual check to avoid duplicates instead of using 'any'
                    exists = False
                    for x in self.session_fills:
                        if x["time"] == time_str and x["px"] == fill["px"] and x["inst"] == fill["inst"]:
                            exists = True
                            break
                            
                    if not exists:
                        self.session_fills.insert(0, fill)
                
                self.session_fills = self.session_fills[:40] # Keep more history
                self.update_history_display()
                if fills:
                    self.log_action(f"[green]SUCCESS: Loaded {len(fills)} account fills.[/green]")
                else:
                    self.log_action("[yellow]No recent fills found (last 3 days).[/yellow]")
            else:
                msg = result.get("msg", "Unknown error")
                self.log_action(f"[red]Hydration Error: {msg}[/red]")
        except Exception as e:
            self.log_action(f"[red]Hydration critical failure: {str(e)}[/red]")
            logging.error(f"Hydration critical failure: {e}", exc_info=True)

    def _start_terminal_services(self) -> None:
        self.set_interval(0.1, self.update_header_display)
        self.set_interval(5.0, self.update_portfolio_balance)
        self.set_interval(5.0, self.update_open_orders_and_positions)
        self.set_interval(30.0, self.refresh_chart)
        self.client = OKXPublicClient(instrument_id=self.instrument_id, watchlist=WATCHLIST, callback=self.handle_ws_data)
        self.bg_worker = asyncio.create_task(self.client.connect_market_streams())
        
        # Trigger history hydration
        self.run_worker(self.hydrate_fill_history())
        # Load account fee tiers for the accountant
        self.run_worker(self.update_accountant_fees())

    async def update_accountant_fees(self) -> None:
        from okx_private import OKXPrivateClient
        try:
            result = await asyncio.to_thread(OKXPrivateClient.get_trade_fee, "SPOT")
            if result.get("code") == "0":
                fee_data = result.get("data", [{}])[0]
                taker_rate = float(fee_data.get("taker", "0.0035"))
                maker_rate = float(fee_data.get("maker", "0.0020"))
                # Note: OKX returns 'level' for the tier name
                tier_lvl = fee_data.get("level", "VIP 0")
                
                self.accountant.update_tier_data(taker=taker_rate, maker=maker_rate, level=tier_lvl)
                self.update_preflight_calculator() # Refresh UI
                logging.info(f"Accountant calibrated to {tier_lvl} | Taker: {taker_rate*100:.3f}%")
        except Exception as e:
            logging.warning(f"Could not calibrate accountant fees: {e}", exc_info=True)

    async def update_portfolio_balance(self) -> None:
        from okx_private import OKXPrivateClient
        result = await asyncio.to_thread(OKXPrivateClient.get_account_balance)

        if result.get("code") == "0":
            details = result.get("data", [{}])[0].get("details", [])
            bal_lines = []
            self.portfolio_balances = {}
            for asset in details:
                ccy = asset.get("ccy")
                avail = float(asset.get("availBal", 0))
                self.portfolio_balances[ccy] = avail
                if avail > 0:
                    bal_lines.append(f"[bold white]{ccy}:[/bold white] {avail:,.4f}")

            balance_text = "\n".join(bal_lines) if bal_lines else "No active balances"
            try:
                self.query_one("#portfolio-balance", Static).update(balance_text)
            except Exception as e:
                logging.warning(f"Could not update portfolio balance widget: {e}", exc_info=True)

    async def update_open_orders_and_positions(self) -> None:
        from okx_private import OKXPrivateClient

        orders_res = await asyncio.to_thread(OKXPrivateClient.get_pending_orders)
        pos_res = await asyncio.to_thread(OKXPrivateClient.get_positions)

        output_lines = []

        if orders_res.get("code") == "0":
            orders = orders_res.get("data", [])
            if orders:
                output_lines.append("[bold yellow]Resting Orders:[/bold yellow]")
                for o in orders[:3]:
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
            logging.warning(f"Could not update positions/orders widget: {e}", exc_info=True)

    def log_action(self, message: str) -> None:
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
                inst_id = ticker.get("instId")
                last = ticker.get("last", "0.0")
                
                # Routing for primary focus instrument
                if inst_id == self.instrument_id:
                    self.current_price = last
                    self.high_24h = ticker.get("high24h", "0.0")
                    self.low_24h = ticker.get("low24h", "0.0")
                    self.volume_24h = ticker.get("vol24h", "0.0")

                # Routing for Watchlist Telemetry
                if inst_id in WATCHLIST:
                    last_px = float(last)
                    open_24h = float(ticker.get("open24h", 0))
                    high_24h = float(ticker.get("high24h", 0))
                    low_24h = float(ticker.get("low24h", 0))
                    change_pct = 0.0
                    if open_24h > 0:
                        change_pct = ((last_px - open_24h) / open_24h) * 100
                    
                    self.telemetry_data[inst_id] = {
                        "last": f"{last_px:,.2f}",
                        "change": f"{change_pct:+.2f}%",
                        "high": high_24h,
                        "low": low_24h,
                        "raw_last": last_px
                    }
            
            self.refresh_hubs()

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
                    logging.warning(f"Order book update skipped during shutdown: {e}", exc_info=True)

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
                logging.warning(f"Trade feed update skipped during shutdown: {e}", exc_info=True)

    def update_header_display(self) -> None:
        header_widget = self.query_one("#header-bar", Static)
        header_widget.update(
            f" OXX TUI > {self.instrument_id} [dim]│[/dim] Price: [bold green]{self.current_price}[/bold green] "
            f"[dim]│[/dim] High: {self.high_24h} [dim]│[/dim] Low: {self.low_24h} [dim]│[/dim] Vol: {self.volume_24h}"
        )

    def refresh_hub_content(self, inst_list, widget_id):
        lines = []
        for inst in inst_list:
            data = self.telemetry_data.get(inst, {"last": "---", "change": "---", "high": 0, "low": 0, "raw_last": 0})
            
            # Price Change Color
            change_color = "#3399ff" if "+" in data["change"] else "#ff3333"
            if data["change"] == "---": change_color = "white"
            
            # RPI Calculation
            high = data.get("high", 0)
            low = data.get("low", 0)
            last = data.get("raw_last", 0)
            
            rng_pos_str = "---"
            rng_color = "white"
            
            if high > low:
                rpi = ((last - low) / (high - low)) * 100
                rng_pos_str = f"{rpi:.1f}%"
                
                # Steelers Stars Theme: Blue (Dip), White (Neutral), Red (Chase)
                if rpi <= 30:
                    rng_color = "#3399ff" # Star Blue
                elif rpi >= 70:
                    rng_color = "#ff3333" # Star Red
                else:
                    rng_color = "#ffffff" # White
            
            # Asset (12) Price (10) 24H% (9) RNG% (8)
            lines.append(f"{inst:<12} {data['last']:>10}  [{change_color}]{data['change']:>7}[/{change_color}]  [{rng_color}]{rng_pos_str:>6}[/{rng_color}]")
        
        try:
            self.query_one(widget_id, Static).update("\n".join(lines))
        except Exception as e:
            logging.warning(f"Unable To Retrieve RPI Calculation: {e}", exc_info=True)

    def refresh_hubs(self):
        width = self.size.width
        if width > 190:
            # 3 Columns of 8 pairs each
            hub_a_pairs = WATCHLIST[:8]
            hub_b_pairs = WATCHLIST[8:16]
            hub_c_pairs = WATCHLIST[16:]
            self.refresh_hub_content(hub_a_pairs, "#hub-a-content")
            self.refresh_hub_content(hub_b_pairs, "#hub-b-content")
            self.refresh_hub_content(hub_c_pairs, "#hub-c-content")
        else:
            # 2 Columns of 12 pairs each
            hub_a_pairs = WATCHLIST[:12]
            hub_b_pairs = WATCHLIST[12:]
            self.refresh_hub_content(hub_a_pairs, "#hub-a-content")
            self.refresh_hub_content(hub_b_pairs, "#hub-b-content")
            # Clear Hub C if visible but unused
            try: self.query_one("#hub-c-content").update("Unused real estate")
            except: pass

if __name__ == "__main__":
    app = OKXTerminalApp()
    app.run()
