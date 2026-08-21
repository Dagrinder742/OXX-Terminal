from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static, Input, Button, Label
from textual.screen import ModalScreen
from secure_vault import EncryptedVault

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
            # Save using our cross-platform encrypted vault
            EncryptedVault.save_credentials(api_key, secret_key, passphrase)
            self.dismiss(True)
        else:
            self.query_one(Static).update("[bold red]All fields are required! Please fill out all inputs.[/bold red]")

class OKXTerminalUI(App):
    """A full-screen TUI terminal layout for OKX trading telemetry with secure auth."""

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

    def on_mount(self) -> None:
        """Check if credentials exist in the encrypted vault on startup."""
        creds = EncryptedVault.load_credentials()
        if not creds.get("api_key"):
            self.push_screen(AuthModal(), self.handle_auth_result)
        else:
            self.notify("Secure credentials loaded from encrypted vault.", title="Auth Success")

    def handle_auth_result(self, success: bool) -> None:
        if success:
            self.notify("Credentials saved to encrypted vault!", title="Vault Updated")

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

            # Right Main Workspace: Charts & Order Book grids
            with Vertical(classes="panel", id="right-main"):
                yield Static("[bold green]Live Candlestick / Order Book Feed[/bold green]")
                yield Static("Awaiting live stream data stream synchronization...")

        yield Footer()

if __name__ == "__main__":
    app = OKXTerminalUI()
    app.run()

