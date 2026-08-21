import asyncio
import json
import logging
import websockets
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static, Input, Button
from textual.reactive import reactive
from textual.screen import ModalScreen
from secure_vault import EncryptedVault

# OKX Public WebSocket Endpoint
OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"

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
    """A fully asynchronous, real-time OKX TUI trading terminal with encrypted vault security."""

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

    current_price = reactive("Connecting...")
    high_24h = reactive("---")
    low_24h = reactive("---")
    volume_24h = reactive("---")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="header-bar")

        with Horizontal(classes="row"):
            with Vertical(classes="panel", id="left-sidebar"):
                yield Static("[bold cyan]Order Entry Panel[/bold cyan]")
                yield Static("Price:")
                yield Input(placeholder="0.00", id="price-input")
                yield Static("Amount:")
                yield Input(placeholder="0.001", id="amount-input")
                yield Button("BUY (LONG)", variant="success")
                yield Button("SELL (SHORT)", variant="error")

            with Vertical(classes="panel", id="right-main"):
                yield Static("[bold green]Live Candlestick / Order Book Feed[/bold green]")
                yield Static("WebSocket Stream Active: Streaming live data ticks...", id="feed-status")

        yield Footer()

    async def on_mount(self) -> None:
        """Checks encrypted vault on startup; pushes auth modal if missing, else boots feeds."""
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
        """Kicks off the ticker update interval and asynchronous background WebSocket loop."""
        self.set_interval(0.1, self.update_header_display)
        self.bg_worker = asyncio.create_task(self.connect_okx_stream())

    def update_header_display(self) -> None:
        header_widget = self.query_one("#header-bar", Static)
        header_widget.update(
            f" OKX TUI > BTC-USD [dim]│[/dim] Price: [bold green]{self.current_price}[/bold green] "
            f"[dim]│[/dim] High: {self.high_24h} [dim]│[/dim] Low: {self.low_24h} [dim]│[/dim] Vol: {self.volume_24h}"
        )

    async def connect_okx_stream(self) -> None:
        instrument = "BTC-USD"
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

