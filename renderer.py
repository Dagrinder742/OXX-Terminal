from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Static, Input, Button

class OKXTerminalUI(App):
    """A full-screen TUI terminal layout for OKX trading telemetry."""

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

    def compose(self) -> ComposeResult:
        yield Header()
        
        # Top ticker strip
        yield Static(" OKX TUI > BTC-USDT | Loading Ticker Feed...", id="header-bar")

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