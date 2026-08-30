import asyncio
import logging
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Static, Label
from textual.reactive import reactive
import plotext as plt

# Simplified mock for exploration
WATCHLIST = [f"TOKEN-{i}-USD" for i in range(24)]

class ReactiveScalingApp(App):
    """
    [EXPLORATION SCRIPT - V2]
    Hardened for Termux/Windows compatibility using on_resize logic 
    instead of fragile media queries.
    """

    CSS = """
    Screen {
        background: #000000;
        color: #ffffff;
        border: solid #ffcc00;
    }

    #page-viewport {
        width: 100%;
        height: 1fr;
    }

    /* THE LIQUID SIDEBAR */
    #left-column {
        width: 1fr;
        min-width: 48;
        max-width: 60;
        height: auto;
        border: solid #ffcc00;
        margin: 1;
        padding: 1;
    }

    /* THE MAIN DASHBOARD */
    #right-main {
        width: 3fr;
        height: auto;
        border: solid #333333;
        margin: 1;
    }

    .sub-panel {
        border: solid #ffcc00;
        padding: 1;
        margin: 1;
    }

    /* THE INFINITE STRETCH CHART */
    #chart-box {
        width: 100%;
        height: 20;
        background: #080808;
        text-align: center;
    }

    /* ADAPTIVE HUB CLASSES */
    #hub-container {
        height: auto;
    }

    .hub-column {
        border: solid #333333;
        margin: 0 1;
        height: auto;
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="page-viewport"):
            with Horizontal():
                with Vertical(id="left-column"):
                    yield Static("[bold #ffcc00]LIQUID SIDEBAR[/bold #ffcc00]")
                    yield Label("Width: Dynamic (1fr)")
                    yield Static("\nThis column stays grounded while the right dashboard stretches.")

                with Vertical(id="right-main"):
                    with Vertical(classes="sub-panel"):
                        yield Static("[bold cyan]INFINITE STRETCH CHART[/bold cyan]")
                        yield Static("Calculating matrix...", id="chart-box")
                        yield Static("Current Width: 0", id="width-label")

                    yield Static("  [bold #ffcc00]ADAPTIVE MARKET HUB[/bold #ffcc00]")
                    with Horizontal(id="hub-container"):
                        with Vertical(classes="hub-column", id="hub-a"):
                            yield Static("[bold cyan]HUB A (Majors)[/bold cyan]")
                            yield Static("Loading...", id="hub-a-content")
                        with Vertical(classes="hub-column", id="hub-b"):
                            yield Static("[bold cyan]HUB B (Alts)[/bold cyan]")
                            yield Static("Loading...", id="hub-b-content")
                        with Vertical(classes="hub-column", id="hub-c"):
                            yield Static("[bold cyan]HUB C (DeFi)[/bold cyan]")
                            yield Static("Loading...", id="hub-c-content")

        yield Footer()

    async def on_mount(self) -> None:
        self.set_interval(1.0, self.refresh_liquid_views)

    def on_resize(self, event) -> None:
        """Textual event that fires every time the terminal window is stretched."""
        # Use on_resize to handle layout logic instead of CSS media queries
        width = event.size.width
        hub_container = self.query_one("#hub-container")
        
        if width > 180:
            # 3 Column Mode
            hub_container.styles.layout = "horizontal"
            self.query_one("#hub-c").styles.display = "block"
        elif width > 100:
            # 2 Column Mode
            hub_container.styles.layout = "horizontal"
            self.query_one("#hub-c").styles.display = "none"
        else:
            # Mobile/Small Mode (Vertical Stack)
            hub_container.styles.layout = "vertical"
            self.query_one("#hub-c").styles.display = "none"

    def refresh_liquid_views(self):
        """Reactively updates the chart resolution based on panel width."""
        try:
            chart_widget = self.query_one("#chart-box", Static)
            width = chart_widget.content_size.width
            height = chart_widget.content_size.height
            
            self.query_one("#width-label", Static).update(f"Current Dashboard Width: [bold green]{width}[/bold green] chars")

            if width > 0:
                plt.clf()
                plt.plotsize(width, height)
                plt.theme("dark")
                plt.title(f"Liquid Plotext @ {width}px Width")
                
                # Higher resolution data if the screen is wider
                data_points = max(20, width // 2)
                y = [i**0.5 for i in range(data_points)]
                plt.plot(y, color="gold")
                
                chart_widget.update(plt.build())

            self.update_hub_data()
        except:
            pass

    def update_hub_data(self):
        width = self.size.width
        if width > 180:
            self.query_one("#hub-a-content").update("\n".join(WATCHLIST[:8]))
            self.query_one("#hub-b-content").update("\n".join(WATCHLIST[8:16]))
            self.query_one("#hub-c-content").update("\n".join(WATCHLIST[16:]))
        else:
            self.query_one("#hub-a-content").update("\n".join(WATCHLIST[:12]))
            self.query_one("#hub-b-content").update("\n".join(WATCHLIST[12:]))

if __name__ == "__main__":
    app = ReactiveScalingApp()
    app.run()
