import asyncio
import datetime
import heapq
import logging
import os
import re
import sys
import time
from decimal import Decimal
from logging.handlers import RotatingFileHandler
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
from rich.markup import escape
from order_format import quantize_price, quantize_size, fmt_price, fmt_qty, money
from order_tracker import OrderTracker, TrackedOrder, SimExchange, new_cl_ord_id

# Log to a FILE, not the terminal: Textual owns the screen, and a console log handler paints
# over it.  force=True replaces any handler a module installed at import time (the first
# basicConfig call wins otherwise, which silently ignored this one).
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oxx.log")
logging.basicConfig(
    handlers=[RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")],
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    force=True,
)

# Nerd-Font icons are blank boxes in fonts that lack them (Termux default).  Opt in per machine:
#   export OXX_NERD_FONT=1
_NERD = os.environ.get("OXX_NERD_FONT") == "1"
ICON_KEY = "\uf510 " if _NERD else ""
ICON_CHART = "\uf4c8 " if _NERD else ""

STABLE_QUOTES = {"USDT", "USDC", "USD", "DAI"}
DUST_USD = 1.0  # balances worth less than this are treated as "nothing to trade"

WATCHLIST = [
    "BTC-USDT", "HYPE-USDT", "SOL-USDT", "ETH-USDT", "JUP-USDT",
    "JTO-USDT", "APT-USDT", "PAXG-USDT", "TRX-USDT", "SHIB-USDT",
    "RENDER-USDT", "OP-USDT", "ATOM-USDT", "LTC-USDT",
    "NEAR-USDT", "UNI-USDT", "LINK-USDT", "ADA-USDT", "AVAX-USDT",
    "XRP-USDT", "SUI-USDT", "DOGE-USDT", "BNB-USDT", "USDC-USDT"
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
            yield Static(f"[bold cyan]{ICON_KEY}OXX Secure Credential Setup[/bold cyan]")
            yield Static("Enter your API credentials. Press Enter to submit.")

            yield Label("API Key:")
            yield Input(placeholder="Enter API Key...", id="api_key_input", classes="input-box")

            yield Label("Secret Key:")
            yield Input(placeholder="Enter Secret Key...", password=True, id="secret_key_input", classes="input-box")

            yield Label("Passphrase:")
            yield Input(placeholder="Enter Passphrase...", password=True, id="passphrase_input", classes="input-box")

            yield Button("Save & Launch Terminal", variant="success", id="save_btn")

    _saving = False   # a save is running right now
    _done = False     # a save already succeeded; the dialog is closing

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        await self._submit_credentials()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_btn":
            await self._submit_credentials()

    async def _submit_credentials(self) -> None:
        if self._saving or self._done:   # double tap / Enter + button: during the save, or just after it
            return
        api_key = self.query_one("#api_key_input", Input).value.strip()
        secret_key = self.query_one("#secret_key_input", Input).value.strip()
        passphrase = self.query_one("#passphrase_input", Input).value.strip()

        if not (api_key and secret_key and passphrase):
            self.query_one(Static).update("[bold red]All fields are required! Please fill out all inputs.[/bold red]")
            return

        self._saving = True
        self.query_one(Static).update("[bold yellow]Encrypting and saving - this takes a few seconds...[/bold yellow]")
        try:
            # Encrypting is slow on a phone: keep it off the UI thread so the screen doesn't freeze.
            await asyncio.to_thread(EncryptedVault.save_credentials, api_key, secret_key, passphrase)
        except Exception as e:
            logging.error(f"Saving credentials failed: {type(e).__name__}: {e}")
            self.query_one(Static).update(f"[bold red]Could not save credentials: {escape(str(e))}[/bold red]")
            return
        finally:
            self._saving = False
        self._done = True
        from okx_private import OKXPrivateClient
        OKXPrivateClient.clear_credentials_cache()   # next request re-reads the NEW keys
        self.dismiss(True)

class OXXTerminalApp(App):
    """A fully asynchronous, real-time OXX TUI trading terminal with live market depth grids."""

    TITLE = "OXX Terminal"

    def __init__(self):
        super().__init__()
        self.log_lines = []            # Execution & Order Log lines (newest first)
        self._book_asks = {}           # {price_str: level} full local order book
        self._book_bids = {}
        self.instrument_specs = {}     # {instId: {"tickSz", "lotSz", "minSz"}}
        self._services_started = False
        self._polling = set()          # names of poll tasks currently running
        self._hubs_dirty = False
        self._last_tick = float("-inf")  # monotonic time of the last ticker for the focus instrument (-inf = none yet; stale regardless of device uptime)
        self._feed_confirmed = None    # instrument whose first ticker has arrived
        self.instrument_id = "BTC-USDT"
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
        self.simulation_mode = True # SAFETY PIN: Set to False only when ready for real risk.
        # Orders are tracked until the exchange reports them filled/cancelled; only real fills are booked.
        self.sim_exchange = SimExchange(
            price_fn=self._price_for,
            rates_fn=lambda: (self.accountant.maker_rate, self.accountant.taker_rate),
        )
        self.order_tracker = OrderTracker(
            exchange_fn=self._exchange,
            on_fill=self._on_order_fill,
            on_closed=self._on_order_closed,
            on_note=self.log_action,
        )

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
        width: 54; /* Increased from 48 to fix button border distortion */
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

    #tactical-preflight-box {
        margin-top: 1;
        padding: 0 1;
        border: double #333333;
        background: #080808;
        height: 7; /* header + 4 rows + double border */
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
        yield Static(f" OXX TUI > {self.instrument_id} | Loading Ticker Feed...", id="header-bar")

        # Main viewport with page-level scrolling
        with VerticalScroll(id="page-viewport"):
            # Main workspace grid split into columns
            with Horizontal(classes="row"):

                # Left Column: Standard Vertical container
                with Vertical(id="left-column"):
                    # Sidebar: Portfolio Balance & Order Entry Panel
                    with Vertical(classes="panel", id="left-sidebar"):
                        yield Static("[bold #ffcc00]Instrument Search[/bold #ffcc00]")
                        yield Input(placeholder="BTC-USDT", id="instrument-search-input")

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
                            yield Static(f"[bold #3399ff]{ICON_CHART}Tactical Edge (Pre-Flight)[/bold #3399ff]", id="preflight-header")
                            yield Static("Est. Fee:  $0.00", id="preflight-fee", classes="tactical-row")
                            yield Static("Hurdle:    $0.00", id="preflight-hurdle", classes="tactical-row")
                            yield Static("Net TP:    $0.00", id="preflight-net-tp", classes="tactical-row")
                            yield Static("Net SL:    $0.00", id="preflight-net-sl", classes="tactical-row")

                        yield Static("[dim]Advanced Risk Management (TP/SL)[/dim]")
                        yield Input(placeholder="Take-Profit Price...", id="tp-input")
                        yield Input(placeholder="Stop-Loss Price...", id="sl-input")

                        yield Button("BUY", variant="success", id="manual-buy-btn", classes="buy-btn")
                        yield Button("SELL", variant="error", id="manual-sell-btn", classes="sell-btn")
                        
                        yield Static("[dim]System Settings:[/dim]")
                        yield Button(f"{ICON_KEY}MANAGE API KEYS", id="manage-keys-btn")

                    # Bot Control Panel - FLATTENED ARCHITECTURE
                    with Vertical(classes="panel", id="bot-panel"):
                        yield Static("[bold #ffcc00]Strategy Control Panel[/bold #ffcc00]")
                        yield Static("Engine Status: [bold red]IDLE[/bold red]", id="bot-status")
                        yield Static("Active Bots: 0 | Session PnL: $0.00", id="bot-metrics")

                        yield Static("[dim]Investment (USDT):[/dim]")
                        yield Input(placeholder="100", id="bot-invest-input")

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
                        yield Button("CANCEL MY OPEN ORDERS", variant="error", id="cancel-orders-btn", classes="sell-btn")

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
                            yield Static("Price (USDT)  Amount  Time\n---------------------------------", id="last-trades-header")
                            yield Static("Waiting for trade stream...", id="last-trades-content")

                    # 3. Onyx Ticker Board (Live Watchlist)
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
            self.query_one("#preflight-header", Static).update(f"[bold #3399ff]{ICON_CHART}Tactical Edge ({self.accountant.tier_label})[/bold #3399ff]")

            self.query_one("#preflight-fee", Static).update(f"Est. Fee:  [bold #ff3333]${metrics['fee']:.4f}[/bold #ff3333]")
            self.query_one("#preflight-hurdle", Static).update(f"Hurdle:    [bold #3399ff]${metrics['break_even']:,.2f}[/bold #3399ff]")

            # Show the sign: a TP below the hurdle is a LOSS after fees and must not read as $0.00.
            for widget_id, label, value, entered in (
                ("#preflight-net-tp", "Net TP:   ", metrics['net_tp'], bool(tp_val)),
                ("#preflight-net-sl", "Net SL:   ", metrics['net_sl'], bool(sl_val)),
            ):
                if entered:
                    color = "#00ff66" if value > 0 else "#ff3333"
                    self.query_one(widget_id, Static).update(f"{label} [bold {color}]{money(value)}[/bold {color}]")
                else:
                    self.query_one(widget_id, Static).update(f"{label} $0.00")

        except ValueError:
            return  # half-typed input such as "." or "1e": nothing to calculate yet
        except Exception as e:
            logging.warning(f"Pre-flight calculator failed: {e}", exc_info=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "instrument-search-input":
            new_inst = event.value.strip().upper().replace("/", "-")
            if not new_inst:
                return

            if " " in new_inst:
                new_inst = new_inst.replace(" ", "-")

            if "-" not in new_inst:
                new_inst = f"{new_inst}-USDT"

            event.input.value = ""
            self.action_switch_instrument(new_inst)

    async def on_mount(self) -> None:
        # The vault decrypt takes seconds on a phone: do it off the UI thread, once.  Every later
        # private request reuses the cached result (see OKXPrivateClient.get_credentials).
        from okx_private import OKXPrivateClient
        self.notify("Unlocking credential vault (can take several seconds)...", timeout=8)
        creds = await asyncio.to_thread(OKXPrivateClient.get_credentials)
        if not creds.get("api_key"):
            self.push_screen(AuthModal(), self.handle_auth_result)
        else:
            self.notify("Secure credentials loaded from encrypted vault.", title="Auth Success")
            self._start_terminal_services()  # also loads the first chart

    def handle_auth_result(self, success: bool) -> None:
        if success:
            self.notify("Credentials saved to encrypted vault!", title="Vault Updated")
            self._start_terminal_services()  # idempotent: re-saving keys must not start a second feed

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

        if button_id == "cancel-orders-btn":
            self.action_cancel_orders()
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

        if button_id not in ("manual-buy-btn", "manual-sell-btn"):
            return  # not an order button (e.g. a button inside a modal): never fall through to order code

        def _clean(widget_id: str) -> str:
            return self.query_one(widget_id, Input).value.strip().replace("$", "").replace(",", "")

        price_val = _clean("#price-input")
        amount_val = _clean("#amount-input")
        tp_val = _clean("#tp-input")
        sl_val = _clean("#sl-input")

        if not amount_val:
            self.notify("Please enter an order amount!", severity="error", title="Order Error")
            return

        ord_type = "limit" if price_val else "market"
        side = "buy" if button_id == "manual-buy-btn" else "sell"

        self.run_worker(
            self._execute_order_task(side, ord_type, amount_val, price_val, tp_val, sl_val, tag="Manual"),
            exit_on_error=False,
        )

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
        self._book_asks = {}
        self._book_bids = {}
        self._feed_confirmed = None

        try:
            self.query_one("#last-trades-content", Static).update("Waiting for trade stream...")
        except Exception as e:
            logging.warning(f"Could not clear trades widget on switch: {e}", exc_info=True)

        self.current_price = "Connecting..."

        if self.bg_worker and not self.bg_worker.done():
            self.bg_worker.cancel()

        # Keep the watchlist subscription, otherwise both ticker hubs stop updating after a switch.
        self.client = OKXPublicClient(instrument_id=new_inst, watchlist=WATCHLIST, callback=self.handle_ws_data)
        self.bg_worker = asyncio.create_task(self.client.connect_market_streams())
        self.bg_worker.add_done_callback(self._log_task_result)

        self.refresh_chart()
        if self.accountant.group_rates:  # fee schedule already loaded: re-pick rates for the new pair
            self.run_worker(self._apply_instrument_fees(new_inst), exit_on_error=False)
        # Don't claim success yet: confirm when the first ticker arrives, warn if it never does.
        self.set_timer(10, lambda: self._check_feed(new_inst))

    def _check_feed(self, inst_id: str) -> None:
        if self.instrument_id == inst_id and self._feed_confirmed != inst_id:
            self.notify(f"No data received for {inst_id}. Check the symbol.", severity="warning", title="Feed Silent")
            self.log_action(f"[yellow]No ticker data for {inst_id} after 10s - symbol may be invalid[/yellow]")

    @staticmethod
    def _log_task_result(task: "asyncio.Task") -> None:
        """Surface exceptions from fire-and-forget tasks (otherwise they vanish silently)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logging.error(f"Background task died: {exc!r}", exc_info=exc)

    def _last_price(self):
        """Current price as a float, or None while still connecting."""
        try:
            return float(str(self.current_price).replace(",", ""))
        except ValueError:
            return None

    def action_start_bot(self, strategy_type: str = "GRID") -> None:
        try:
            if self.strategy_manager.active_bots:
                self.notify("A bot is already running. Stop it first.", severity="warning")
                return

            mid_price = self._last_price()
            if mid_price is None:
                self.notify("Waiting for a live price before starting a bot.", severity="warning")
                return
            amount_str = self.query_one("#bot-invest-input", Input).value.strip().replace("$", "").replace(",", "")

            if not amount_str:
                self.notify("Bot investment (USDT) is required to start a bot!", severity="error")
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
                    current_market_price=mid_price,
                    round_trip_fee_rate=self.accountant.taker_rate * 2,  # worst case: both legs taker
                    grid_type=self.grid_type,
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
            self.bot_worker.add_done_callback(self._log_task_result)
            self.notify(f"{strategy_type} Bot Started for {self.instrument_id}!", title="Strategy Active")
            self.log_action(f"[cyan]Strategy Engine: {strategy_type} Bot {bot_id} launched @ ${mid_price:.2f}[/cyan]")
            self.update_bot_ui()

        except Exception as e:
            self.notify(f"Invalid parameters: {e}", severity="error")
            logging.error(f"Bot start failed: {e}", exc_info=True)
            return

    def action_stop_bot(self) -> None:
        bot_ids = set(self.strategy_manager.active_bots)
        count = self.strategy_manager.stop_all()
        if self.bot_worker:
            self.bot_worker.cancel()

        resting = self.order_tracker.open_orders(bot_ids=bot_ids)
        if resting:
            self.notify(f"Stopped {count} bots. Cancelling {len(resting)} resting order(s)...", title="Strategy Halted")
            self.log_action(f"[red]Strategy Engine: bots stopped; cancelling {len(resting)} resting order(s)...[/red]")
            self.run_worker(self._cancel_orders(resting, "bot stop"), group="orders", exit_on_error=False)
        else:
            self.notify(f"Stopped {count} active bots. No resting bot orders to cancel.", title="Strategy Halted")
            self.log_action("[red]Strategy Engine: all bots stopped (no resting orders from this session).[/red]")
        self.update_bot_ui()

    def action_cancel_orders(self) -> None:
        """Cancels every order THIS session placed that is still open (manual and bot)."""
        resting = self.order_tracker.open_orders()
        if not resting:
            self.notify("No open orders from this session.", title="Nothing to cancel")
            return
        extra = " Bots are still running and may place new ones." if self.strategy_manager.active_bots else ""
        self.notify(f"Cancelling {len(resting)} open order(s)...{extra}", title="Cancel Orders")
        self.run_worker(self._cancel_orders(resting, "manual cancel"), group="orders", exit_on_error=False)

    async def _cancel_orders(self, orders, reason: str) -> None:
        summary = await self.order_tracker.cancel(orders)
        parts = []
        if summary["cancelled"]:
            parts.append(f"{summary['cancelled']} cancelled")
        if summary["already_done"]:
            parts.append(f"{summary['already_done']} had already filled/closed")
        if summary["unconfirmed"]:
            parts.append(f"{len(summary['unconfirmed'])} cancel accepted but not yet confirmed")
        text = ", ".join(parts) or "nothing to cancel"
        self.log_action(f"[cyan]Cancel ({reason}): {text}[/cyan]")
        if summary["failed"]:
            detail = "; ".join(f"{o.inst_id} {o.side.upper()} {fmt_qty(o.remaining)}: {r}" for o, r in summary["failed"][:2])
            self.notify(f"{len(summary['failed'])} order(s) could NOT be cancelled: {escape(detail)}. Check the exchange.",
                        severity="error", title="Cancel Failed")
            self.log_action(f"[bold red]{len(summary['failed'])} order(s) NOT cancelled - still open: {escape(detail)}[/bold red]")
        else:
            self.notify(text, title="Cancel Orders")
        self.update_history_display()
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
            target_px = float(price_input_val.replace("$", "").replace(",", "")) if price_input_val else curr_px

            available_quote = self.portfolio_balances.get(quote_asset, 0.0)
            available_base = self.portfolio_balances.get(base_asset, 0.0)
            
            # Dust (a few cents of leftover) must not decide the side: require ~$1 of real value.
            if quote_asset in STABLE_QUOTES:
                quote_ok = available_quote >= DUST_USD
                base_ok = available_base * target_px >= DUST_USD
            else:
                quote_ok = available_quote > 0
                base_ok = available_base > 0

            if quote_ok:
                # BUY Side Logic
                spend_amount = available_quote * percentage
                buy_qty = spend_amount / target_px
                
                # Update TUI
                self.query_one("#amount-input", Input).value = f"{buy_qty:.6f}"
                self.query_one("#total-input", Input).value = f"{spend_amount:.2f}"
                if not price_input_val:
                    price_input_widget.value = f"{target_px:.2f}"
                
                self.notify(f"Prepared to BUY with {int(percentage*100)}% of {quote_asset}", title="Quick Load")
            
            elif base_ok:
                # SELL Side Logic
                sell_qty = available_base * percentage
                total_value = sell_qty * target_px
                
                # Update TUI
                self.query_one("#amount-input", Input).value = f"{sell_qty:.6f}"
                self.query_one("#total-input", Input).value = f"{total_value:.2f}"
                if not price_input_val:
                    price_input_widget.value = f"{target_px:.2f}"
                    
                self.notify(f"Prepared to SELL {int(percentage*100)}% of {base_asset}", title="Quick Load")

            else:
                self.notify(f"Nothing to load: {quote_asset} and {base_asset} balances are below ~${DUST_USD:.0f}.", severity="warning", title="Quick Load")
            
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
            f"Active Bots: {summary['count']} | Session Net: [bold {pnl_color}]{money(live_net)}[/bold {pnl_color}]\n"
            f"[dim]{summary['details']}[/dim]"
        )

    async def _run_bot_execution_loop(self, bot_id: str) -> None:
        bot = self.strategy_manager.active_bots.get(bot_id)
        if not bot:
            return

        stale = False
        while bot_id in self.strategy_manager.active_bots:
            try:
                price = self._last_price()
                if price is None or (time.monotonic() - self._last_tick) > 15:
                    # No price yet, or the feed went quiet: never trade on a stale number.
                    if not stale:
                        stale = True
                        self.log_action("[yellow]Bot paused: no fresh price (feed stale)[/yellow]")
                    await asyncio.sleep(1)
                    continue
                if stale:
                    stale = False
                    self.log_action("[green]Bot resumed: price feed is live again[/green]")
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
                        ), exit_on_error=False)
                
                self.update_bot_ui()
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Error in bot execution loop: {e}", exc_info=True)
                await asyncio.sleep(2)

    def refresh_chart(self) -> None:
        async def load_task():
            try:
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
                    data, self.instrument_id, self.current_timeframe, 130, 20
                )
                trend_str = await asyncio.to_thread(
                    OKXChartEngine.render_trend_view,
                    data, 130, 10, ema9, ema21
                )
                momentum_str = await asyncio.to_thread(
                    OKXChartEngine.render_momentum_view,
                    data, 130, 8, rsi
                )

                from rich.text import Text
                self.query_one("#chart-price", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in price_str.splitlines())))
                self.query_one("#chart-trend", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in trend_str.splitlines())))
                self.query_one("#chart-momentum", Static).update(Text.from_ansi("\n".join(line.rstrip() for line in momentum_str.splitlines())))
            except Exception as e:
                logging.warning(f"Could not update candlestick chart widget: {e}", exc_info=True)

        # group="chart": exclusive=True cancels every other worker in the SAME group.  In the default
        # group that silently killed the fee/history workers at start-up and any in-flight order
        # every 30 seconds.  Keep it in its own group so it only replaces an older chart refresh.
        self.run_worker(load_task, name="chart_update", group="chart", exclusive=True)

    async def _execute_order_task(self, side: str, ord_type: str, size: str, price: str, tp: str, sl: str, tag: str = "Manual", bot_id: str = None) -> None:
        """Runs one order (simulated or live) and never lets an exception escape:
        an unhandled error in a worker would exit the whole app."""
        try:
            await self._execute_order(side, ord_type, size, price, tp, sl, tag, bot_id)
        except Exception as e:
            logging.error(f"Order task failed ({tag} {side} {ord_type} {size} @ {price}): {e}", exc_info=True)
            self.notify(f"Order not sent: {escape(str(e))}", severity="error", title="Order Error")
            self.log_action(f"[red]ERROR ({tag}): {escape(str(e))}[/red]")

    async def _get_instrument_spec(self, inst_id: str):
        """tickSz / lotSz / minSz for an instrument (cached). None if the lookup fails."""
        spec = self.instrument_specs.get(inst_id)
        if spec is None:
            spec = await asyncio.to_thread(OKXPublicClient.fetch_instrument, inst_id)
            if spec:
                self.instrument_specs[inst_id] = spec
        return spec

    async def _execute_order(self, side: str, ord_type: str, size: str, price: str, tp: str, sl: str, tag: str, bot_id: str) -> None:
        from okx_private import OKXPrivateClient

        inst_id = self.instrument_id  # captured now: the user may switch instruments while we await
        price = price or None
        tp = tp or None
        sl = sl or None

        # Put size/price exactly on the exchange's grid (and enforce its minimum) in BOTH modes,
        # so simulation exercises the same checks the live path will face.
        spec = await self._get_instrument_spec(inst_id)
        if spec is None:
            if not self.simulation_mode:
                raise RuntimeError(f"No tick/lot size for {inst_id}; refusing to send a live order.")
            self.log_action("[yellow]No instrument spec available; using raw values (simulation only)[/yellow]")
        else:
            size = quantize_size(size, spec["lotSz"])
            if Decimal(size) < Decimal(spec["minSz"]):
                raise ValueError(f"size {size} is below the exchange minimum {spec['minSz']} for {inst_id}")
            if price:
                price = quantize_price(price, spec["tickSz"])
            if tp:
                tp = quantize_price(tp, spec["tickSz"])
            if sl:
                sl = quantize_price(sl, spec["tickSz"])

        last = self._last_price()
        if not price and last is None:
            raise ValueError("no live price yet")

        order = TrackedOrder(
            cl_ord_id=new_cl_ord_id(), inst_id=inst_id, side=side.lower(), ord_type=ord_type,
            sz=float(size), px=float(price) if (price and ord_type == "limit") else None,
            tag=tag, bot_id=bot_id,
        )
        px_arg = price if ord_type == "limit" else None

        if self.simulation_mode:
            self.notify(f"[SIM] {side.upper()} {ord_type} {size} sent to the simulator (no real order).", title="Sim Mode")
            self.log_action(f"[cyan]SIM MODE: {tag} placed {side.upper()} {size} @ {price or 'MKT'}[/cyan]")
            result = self.sim_exchange.place(inst_id, side, ord_type, size, px_arg, order.cl_ord_id)
        else:
            self.notify(f"Submitting {side.upper()} {ord_type} order...", title="Executing")
            self.log_action(f"[yellow]{tag}: submitting {side.upper()} {ord_type} order (sz: {size}) (TP: {tp or 'None'}, SL: {sl or 'None'})...[/yellow]")
            result = await asyncio.to_thread(
                OKXPrivateClient.place_order,
                inst_id=inst_id,
                side=side,
                order_type=ord_type,
                sz=size,
                px=px_arg,
                tp_trigger_px=tp,
                sl_trigger_px=sl,
                cl_ord_id=order.cl_ord_id,
            )

        code = str(result.get("code"))
        row = (result.get("data") or [{}])[0]
        s_code = str(row.get("sCode", "0"))

        if code == "0" and s_code == "0":
            order.ord_id = row.get("ordId")
            # ACCEPTED is not FILLED.  Register it; fills are booked only when the exchange reports them.
            await self._track_new_order(order, f"[green]PLACED: {tag} {side.upper()} {size} @ {price or 'MKT'} (ID {order.ord_id}) - waiting for fills[/green]")
            self.notify(f"Order placed (not filled yet). ID: {order.ord_id}", title="Order Placed")
        elif code == "500":
            # The request failed locally (timeout / network).  The exchange MAY have the order, so do
            # not call it failed and do not retry blindly: track it by our client id and find out.
            order.uncertain = True
            await self._track_new_order(order, f"[yellow]{tag}: no answer from the exchange ({escape(str(result.get('msg')))}). Checking whether the order exists...[/yellow]")
            self.notify("No answer from the exchange. Checking whether the order was placed - do NOT resend yet.",
                        severity="warning", title="Order Status Unknown")
        else:
            # The useful reason lives in data[0].sMsg; the envelope usually just says "All operations failed".
            msg = row.get("sMsg") or result.get("msg") or "Unknown error"
            shown_code = s_code if s_code != "0" else code
            self.notify(f"Order failed ({shown_code}): {escape(str(msg))}", severity="error", title="API Error")
            self.log_action(f"[red]FAILED ({tag}): {escape(str(msg))}[/red]")

    async def _track_new_order(self, order: TrackedOrder, message: str) -> None:
        self.order_tracker.register(order)
        if order.bot_id:
            self.strategy_manager.order_placed(order.bot_id, order.side, order.sz)
        self.log_action(message)
        self.update_history_display()
        await self._poll_orders()   # market orders usually fill at once: don't wait for the timer

    # ---------------------------------------------------------------- order lifecycle
    def _exchange(self):
        """Where orders live right now: the simulator, or the real exchange client."""
        if self.simulation_mode:
            return self.sim_exchange
        from okx_private import OKXPrivateClient
        return OKXPrivateClient

    def _price_for(self, inst_id: str):
        if inst_id == self.instrument_id:
            return self._last_price()
        return self.telemetry_data.get(inst_id, {}).get("raw_last")

    async def _poll_orders(self) -> None:
        await self._guarded_poll("order-tracking", self.order_tracker.poll)

    def _display_tag(self, order: TrackedOrder) -> str:
        return f"SIM-{order.tag}" if self.simulation_mode else order.tag

    def _on_order_fill(self, order: TrackedOrder, size: float, price: float, fee_quote) -> None:
        """A real piece of fill: the ONLY place the ledger, bot state and history are updated."""
        tag = self._display_tag(order)
        try:
            self.accountant.record_confirmed_fill(order.inst_id, order.side, price, size, tag=tag, fee_quote=fee_quote)
        except Exception as e:
            logging.error(f"Accountant failed to record fill: {e}", exc_info=True)
        if order.bot_id:
            try:
                self.strategy_manager.order_filled(order.bot_id, order.side, price, size)
            except Exception as e:
                logging.error(f"Failed to update bot fill: {e}", exc_info=True)
        self._record_session_fill(order.inst_id, order.side, fmt_qty(size), fmt_price(price), tag)
        partial = f" (partial {fmt_qty(order.booked_sz)}/{fmt_qty(order.sz)})" if order.booked_sz < order.sz - 1e-12 else ""
        self.log_action(f"[green]FILLED: {tag} {order.side.upper()} {fmt_qty(size)} {order.inst_id} @ {fmt_price(price)}{partial}[/green]")
        self.notify(f"{order.side.upper()} {fmt_qty(size)} @ {fmt_price(price)}{partial}", title="Order Filled")
        self.update_history_display()
        self.update_bot_ui()

    def _on_order_closed(self, order: TrackedOrder, state: str, unfilled: float) -> None:
        if order.bot_id:
            self.strategy_manager.order_closed(order.bot_id, order.side, unfilled)
        tag = self._display_tag(order)
        if state == "filled":
            self.log_action(f"[green]ORDER COMPLETE: {tag} {order.side.upper()} {fmt_qty(order.sz)} {order.inst_id}[/green]")
        elif state in ("canceled", "mmp_canceled"):
            self.log_action(f"[yellow]ORDER CANCELLED: {tag} {order.side.upper()} - {fmt_qty(order.booked_sz)} filled, {fmt_qty(unfilled)} unfilled[/yellow]")
        self.update_history_display()
        self.update_bot_ui()

    def _record_session_fill(self, inst_id: str, side: str, size, px, tag: str) -> None:
        self.session_fills.insert(0, {
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "inst": inst_id,
            "side": side.upper(),
            "sz": size,
            "px": px,
            "tag": tag,
        })
        self.session_fills = self.session_fills[:20]

    def update_history_display(self) -> None:
        lines = []
        for o in self.order_tracker.open_orders()[:3]:
            where = f"@ {fmt_price(o.px)}" if o.px else "@ MKT"
            note = " [dim](status unknown)[/dim]" if o.uncertain else ""
            lines.append(f"[yellow]OPEN[/yellow] {self._display_tag(o)} | {o.side.upper()} {fmt_qty(o.remaining)} {where}{note}")
        for f in self.session_fills:
            color = "green" if f["side"] == "BUY" else "red"
            tag_color = "#3399ff" if f["tag"] == "Manual" else "#ffcc00"
            lines.append(
                f"[{tag_color}]{f['tag']}[/{tag_color}] | {f['time']} | "
                f"[{color}]{f['side']}[/{color}] {f['sz']} @ {f['px']}"
            )
        
        history_text = "\n".join(lines) if lines else "No orders or fills yet this session..."
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
                        "side": (f.get("side") or "").upper(),
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
        if self._services_started:
            # Called again after "Manage API keys": credentials are re-read on every request, so
            # just refresh what depends on them. Starting a second feed/timer set would double everything.
            self.run_worker(self.update_accountant_fees(), exit_on_error=False)
            return
        self._services_started = True

        self.set_interval(0.5, self.update_header_display)
        self.set_interval(5.0, self.update_portfolio_balance)
        self.set_interval(5.0, self.update_open_orders_and_positions)
        self.set_interval(2.0, self._poll_orders)   # order lifecycle: fills, cancels, unknown placements
        self.set_interval(30.0, self.refresh_chart)
        self.set_interval(1.0, self._flush_hubs)  # redraw the 24-pair board at most once a second
        self.client = OKXPublicClient(instrument_id=self.instrument_id, watchlist=WATCHLIST, callback=self.handle_ws_data)
        self.bg_worker = asyncio.create_task(self.client.connect_market_streams())
        self.bg_worker.add_done_callback(self._log_task_result)

        self.refresh_chart()
        # exit_on_error=False: a failure in any of these must be logged, not exit the app
        self.run_worker(self.hydrate_fill_history(), exit_on_error=False)   # account trade history
        self.run_worker(self.update_accountant_fees(), exit_on_error=False) # account fee tier

    def _flush_hubs(self) -> None:
        if self._hubs_dirty:
            self._hubs_dirty = False
            self.refresh_hubs()

    async def update_accountant_fees(self) -> None:
        from okx_private import OKXPrivateClient
        try:
            result = await asyncio.to_thread(OKXPrivateClient.get_trade_fee, "SPOT")
            if result.get("code") == "0":
                fee_data = (result.get("data") or [{}])[0]
                self.accountant.load_fee_schedule(fee_data)
                await self._apply_instrument_fees(self.instrument_id)  # picks this pair's fee group
                a = self.accountant
                self.log_action(f"[dim]Fees {a.tier_label}: maker {a.maker_rate*100:.2f}% taker {a.taker_rate*100:.2f}%[/dim]")
            else:
                logging.warning(f"Fee tier lookup failed: {result.get('code')} {result.get('msg')}")
                self.log_action(f"[yellow]Fee tier lookup failed: {escape(str(result.get('msg')))} - using worst-case default rates[/yellow]")
        except Exception as e:
            logging.warning(f"Could not calibrate accountant fees: {e}", exc_info=True)

    async def _apply_instrument_fees(self, inst_id: str) -> None:
        """Select the fee rates for inst_id's fee group (falls back to worst case if unknown)."""
        spec = await self._get_instrument_spec(inst_id)
        if inst_id != self.instrument_id:
            return  # user switched while we were waiting; the newer call wins
        self.accountant.apply_fee_group(spec.get("groupId") if spec else None)
        self.update_preflight_calculator()
        logging.info(f"Fees for {inst_id}: {self.accountant.tier_label} "
                     f"taker {self.accountant.taker_rate*100:.3f}% maker {self.accountant.maker_rate*100:.3f}%")

    async def _guarded_poll(self, name: str, fn) -> None:
        """Run a poll at most once at a time; log (never raise) on failure."""
        if name in self._polling:
            return
        self._polling.add(name)
        try:
            await fn()
        except Exception as e:
            logging.warning(f"{name} poll failed: {e}", exc_info=True)
        finally:
            self._polling.discard(name)

    async def update_portfolio_balance(self) -> None:
        await self._guarded_poll("balance", self._update_portfolio_balance)

    async def update_open_orders_and_positions(self) -> None:
        await self._guarded_poll("orders", self._update_open_orders_and_positions)

    async def _update_portfolio_balance(self) -> None:
        from okx_private import OKXPrivateClient
        result = await asyncio.to_thread(OKXPrivateClient.get_account_balance)

        if result.get("code") == "0":
            details = result.get("data", [{}])[0].get("details", [])
            bal_lines = []
            self.portfolio_balances = {}
            for asset in details:
                ccy = asset.get("ccy")
                avail = float(asset.get("availBal") or 0)
                self.portfolio_balances[ccy] = avail
                if avail > 0:
                    bal_lines.append(f"[bold white]{ccy}:[/bold white] {avail:,.4f}")

            balance_text = "\n".join(bal_lines) if bal_lines else "No active balances"
            try:
                self.query_one("#portfolio-balance", Static).update(balance_text)
            except Exception as e:
                logging.warning(f"Could not update portfolio balance widget: {e}", exc_info=True)
        else:
            logging.warning(f"Balance lookup failed: {result.get('code')} {result.get('msg')}")
            try:
                self.query_one("#portfolio-balance", Static).update(f"[red]Balance unavailable: {escape(str(result.get('msg')))}[/red]")
            except Exception:
                pass

    async def _update_open_orders_and_positions(self) -> None:
        from okx_private import OKXPrivateClient

        output_lines = []
        if self.simulation_mode:
            # Simulation: show ONLY the simulated session. The real account is not queried, so the
            # panel can never mix "SIM resting order" with "no open orders" from the real exchange.
            output_lines.append("[bold yellow]\\[SIM] Resting Orders:[/bold yellow]")
            sim_open = self.order_tracker.open_orders()
            if sim_open:
                for o in sim_open[:3]:
                    where = fmt_price(o.px) if o.px else "MKT"
                    output_lines.append(f"  • {o.inst_id} | {o.side.upper()} {fmt_qty(o.remaining)} @ {where}")
            else:
                output_lines.append("[dim]No open resting orders[/dim]")
            output_lines.append("")
            held = {k: v for k, v in self.accountant.positions.items() if abs(v["size"]) > 1e-12}
            if held:
                output_lines.append("[bold cyan]\\[SIM] Positions:[/bold cyan]")
                for inst, pos in held.items():
                    mark = self.current_price if inst == self.instrument_id else None
                    try:
                        mark = float(str(mark).replace(",", ""))
                    except (TypeError, ValueError):
                        mark = pos["avg_price"]
                    pnl = (mark - pos["avg_price"]) * pos["size"]
                    color = "green" if pnl >= 0 else "red"
                    output_lines.append(f"  • {inst} | {fmt_qty(pos['size'])} @ {fmt_price(pos['avg_price'])}"
                                        f" | PnL: [{color}]{money(pnl)}[/{color}]")
            else:
                output_lines.append("[dim]No simulated positions[/dim]")
            try:
                self.query_one("#positions-content", Static).update("\n".join(output_lines))
            except Exception as e:
                logging.warning(f"Could not update positions/orders widget: {e}", exc_info=True)
            return

        orders_res = await asyncio.to_thread(OKXPrivateClient.get_pending_orders)
        pos_res = await asyncio.to_thread(OKXPrivateClient.get_positions)

        if orders_res.get("code") == "0":
            orders = orders_res.get("data", [])
            if orders:
                output_lines.append("[bold yellow]Resting Orders:[/bold yellow]")
                for o in orders[:3]:
                    inst = o.get("instId")
                    side = (o.get("side") or "?").upper()
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
            active_pos = [p for p in positions if float(p.get("pos") or 0) != 0]
            if active_pos:
                output_lines.append("[bold cyan]Active Positions:[/bold cyan]")
                for p in active_pos:
                    inst = p.get("instId")
                    pos_sz = p.get("pos")
                    pnl = float(p.get("upl") or 0)
                    pnl_color = "green" if pnl >= 0 else "red"
                    output_lines.append(f"  • {inst} | Size: {pos_sz} | PnL: [{pnl_color}]{money(pnl)}[/{pnl_color}]")
            else:
                output_lines.append("[dim]No active trading positions[/dim]")
        else:
            output_lines.append("[dim]Positions feed idle (Cash/Spot mode)[/dim]")

        try:
            self.query_one("#positions-content", Static).update("\n".join(output_lines))
        except Exception as e:
            logging.warning(f"Could not update positions/orders widget: {e}", exc_info=True)

    def log_action(self, message: str) -> None:
        # Kept in our own list: reading the text back out of the widget depends on the Textual
        # version (Static.renderable no longer exists), and failures there were silent.
        logging.info(re.sub(r"\[/?[a-zA-Z#$][^\]]*\]", "", message))  # plain-text copy in oxx.log
        self.log_lines.insert(0, message)
        del self.log_lines[4:]
        try:
            self.query_one("#execution-log-content", Static).update("\n".join(self.log_lines))
        except Exception as e:
            logging.warning(f"Could not update execution log widget: {e}")

    async def handle_ws_data(self, channel: str, data: list) -> None:
        """Parses multi-channel telemetry from api_client.py and updates target TUI widgets."""
        if channel == "tickers":
            for ticker in data:
                inst_id = ticker.get("instId")
                last = ticker.get("last", "0.0")
                
                # Routing for primary focus instrument
                if inst_id == self.instrument_id:
                    self._last_tick = time.monotonic()
                    if self._feed_confirmed != inst_id:
                        self._feed_confirmed = inst_id
                        self.log_action(f"[green]Feed live: {inst_id}[/green]")
                    self.current_price = last
                    self.high_24h = ticker.get("high24h", "0.0")
                    self.low_24h = ticker.get("low24h", "0.0")
                    self.volume_24h = ticker.get("vol24h", "0.0")

                # Routing for Watchlist Telemetry
                if inst_id in WATCHLIST:
                    last_px = float(last or 0)
                    open_24h = float(ticker.get("open24h") or 0)
                    high_24h = float(ticker.get("high24h") or 0)
                    low_24h = float(ticker.get("low24h") or 0)
                    change_pct = 0.0
                    if open_24h > 0:
                        change_pct = ((last_px - open_24h) / open_24h) * 100
                    
                    self.telemetry_data[inst_id] = {
                        "last": fmt_price(last_px),
                        "change": f"{change_pct:+.2f}%",
                        "high": high_24h,
                        "low": low_24h,
                        "raw_last": last_px
                    }
            
            self._hubs_dirty = True  # redrawn by _flush_hubs (max 1x/second)

        elif channel == "books":
            for book in data:
                if book.get("action", "update") == "snapshot":
                    self._book_asks = {}
                    self._book_bids = {}
                # Keep the FULL book locally and only slice for display.  Trimming the stored book to
                # 5 levels meant a removed top level could never be replaced by the one behind it.
                for level in book.get("asks", []):
                    self._apply_book_level(self._book_asks, level)
                for level in book.get("bids", []):
                    self._apply_book_level(self._book_bids, level)

            asks = [self._book_asks[p] for p in heapq.nsmallest(5, self._book_asks, key=float)]
            bids = [self._book_bids[p] for p in heapq.nlargest(5, self._book_bids, key=float)]
            self.cached_asks, self.cached_bids = asks, bids

            asks_formatted = [f"[red]{fmt_price(float(a[0]))}  {fmt_qty(float(a[1]))}[/red]" for a in reversed(asks)]
            bids_formatted = [f"[green]{fmt_price(float(b[0]))}  {fmt_qty(float(b[1]))}[/green]" for b in bids]

            asks_text = "Asks (Sells) [Price / Amt]\n" + ("\n".join(asks_formatted) if asks_formatted else "Waiting...")
            bids_text = "Bids (Buys) [Price / Amt]\n" + ("\n".join(bids_formatted) if bids_formatted else "Waiting...")

            try:
                self.query_one("#order-book-asks", Static).update(asks_text)
                self.query_one("#order-book-bids", Static).update(bids_text)
                if asks and bids:
                    spread = float(asks[0][0]) - float(bids[0][0])
                    self.query_one("#order-book-mid", Static).update(f"[bold white]Spread: {fmt_price(spread)}[/bold white]")
            except Exception as e:
                logging.warning(f"Order book update skipped during shutdown: {e}", exc_info=True)

        elif channel == "trades":
            for trade in data:
                price = float(trade.get("px") or 0)
                size = float(trade.get("sz") or 0)
                side = trade.get("side", "buy")
                try:
                    stamp = datetime.datetime.fromtimestamp(int(trade.get("ts")) / 1000).strftime("%H:%M:%S")
                except (TypeError, ValueError):
                    stamp = "--:--:--"
                self.cached_trades.insert(0, {"price": price, "size": size, "side": side, "time": stamp})

            self.cached_trades = self.cached_trades[:10]

            trade_lines = []
            for t in self.cached_trades:
                color = "green" if t["side"] == "buy" else "red"
                trade_lines.append(f"[{color}]{fmt_price(t['price'])} | {fmt_qty(t['size'])} | {t['time']}[/{color}]")

            # The column header already lives in the static "last-trades-header" above this widget.
            trades_text = "\n".join(trade_lines) if trade_lines else "No Trades"
            try:
                self.query_one("#last-trades-content", Static).update(trades_text)
            except Exception as e:
                logging.warning(f"Trade feed update skipped during shutdown: {e}", exc_info=True)

    @staticmethod
    def _apply_book_level(book: dict, level: list) -> None:
        """Insert/replace one order-book level, or delete it when its size is 0."""
        price, size = level[0], level[1]
        if float(size) == 0.0:
            book.pop(price, None)
        else:
            book[price] = level

    def update_header_display(self) -> None:
        header_widget = self.query_one("#header-bar", Static)
        header_widget.update(
            f" {'[black on yellow] SIM [/]' if self.simulation_mode else '[white on red] LIVE [/]'} "
            f"OXX TUI > {self.instrument_id} [dim]│[/dim] Price: [bold green]{self.current_price}[/bold green] "
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
        hub_a_pairs = WATCHLIST[:12]
        hub_b_pairs = WATCHLIST[12:]
        self.refresh_hub_content(hub_a_pairs, "#hub-a-content")
        self.refresh_hub_content(hub_b_pairs, "#hub-b-content")

if __name__ == "__main__":
    app = OXXTerminalApp()
    app.run()
