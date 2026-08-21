import keyring
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Static, Input, Button, Label
from textual.screen import ModalScreen

SERVICE_NAME = "OKX_Terminal_Suite"

class AuthModal(ModalScreen):
    """A modal screen that prompts the user for secure API credentials on first launch."""

    CSS = """
    AuthModal {
        align: center middle;
    }
    #dialog {
        padding: 2 4;
        width: 60;
        height: 22;
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
            yield Static("Enter your API credentials. They will be stored securely in your OS vault.")

            yield Label("API Key:")
            yield Input(placeholder="Enter API Key...", id="api_key_input", classes="input-box")

            yield Label("Secret Key:")
            yield Input(placeholder="Enter Secret Key...", password=True, id="secret_key_input", classes="input-box")

            yield Label("Passphrase:")
            yield Input(placeholder="Enter Passphrase...", password=True, id="passphrase_input", classes="input-box")

            yield Button("Save & Launch Terminal", variant="success", id="save_btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_btn":
            api_key = self.query_one("#api_key_input", Input).value.strip()
            secret_key = self.query_one("#secret_key_input", Input).value.strip()
            passphrase = self.query_one("#passphrase_input", Input).value.strip()

            if api_key and secret_key and passphrase:
                # Save securely into OS native credential manager
                keyring.set_password(SERVICE_NAME, "api_key", api_key)
                keyring.set_password(SERVICE_NAME, "secret_key", secret_key)
                keyring.set_password(SERVICE_NAME, "passphrase", passphrase)
                self.dismiss(True)
            else:
                self.query_one(Static).update("[bold red]All fields are required![/bold red]")

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
        """Check if credentials exist in the system vault on startup."""
        api_key = keyring.get_password(SERVICE_NAME, "api_key")
        if not api_key:
            # Push the auth modal if credentials are missing
            self.push_screen(AuthModal(), self.handle_auth_result)
        else:
            self.notify("Secure credentials loaded from OS Vault.", title="Auth Success")

    def handle_auth_result(self, success: bool) -> None:
        if success:
            self.notify("Credentials saved securely!", title="Vault Updated")

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

