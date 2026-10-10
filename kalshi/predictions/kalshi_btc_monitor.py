#!/usr/bin/env python3
"""
kalshi_btc_monitor.py
Live Terminal Monitor for Kalshi 15-Min BTC Contracts.
Automatically fetches active market strike via Kalshi's public REST API.
"""

import asyncio
import datetime
import json
import math
import os
import sys
import requests
import websockets

HAS_TEXTUAL = True
try:
    from textual.app import App, ComposeResult
    from textual.containers import Container
    from textual.widgets import Header, Footer, Static
except ImportError:
    HAS_TEXTUAL = False

class KalshiBTCMonitor(App):
    CSS = """
    Screen {
        background: #111111;
        color: #eeeeee;
    }
    #header-box {
        dock: top;
        height: 3;
        content-align: center middle;
        background: #1f2430;
        color: #5ccfe6;
        text-style: bold;
        border-bottom: solid #3b4252;
    }
    #main-box {
        height: 100%;
        padding: 2 4;
        background: #111111;
        color: #ffffff;
    }
    """

    def __init__(self, strike_price: float = None):
        super().__init__()
        self.strike_price = strike_price
        self.current_spot = strike_price if strike_price else 82900.00
        self.brti_ticks_60s = []
        self.market_ticker = "AUTO-FETCHING..."
        self._spot_task = None

    def fetch_active_strike(self):
        """Queries Kalshi public endpoint for active 15-min BTC target."""
        try:
            url = "https://external-api.kalshi.com/trade-api/v2/markets?series_ticker=KXBTC15M&status=open"
            res = requests.get(url, timeout=5).json()
            markets = res.get("markets", [])
            if markets:
                market = markets[0]
                self.market_ticker = market.get("ticker", "ACTIVE")
                floor_strike = market.get("floor_strike")
                if floor_strike:
                    self.strike_price = float(floor_strike)
                    return True
        except Exception:
            pass
        return False

    def get_seconds_remaining(self) -> int:
        now = datetime.datetime.now()
        minute = now.minute
        next_block = ((minute // 15) + 1) * 15
        if next_block >= 60:
            target = now.replace(hour=(now.hour + 1) % 24, minute=0, second=0, microsecond=0)
        else:
            target = now.replace(minute=next_block, second=0, microsecond=0)
        return max(1, int((target - now).total_seconds()))

    def calculate_probability_and_zone(self):
        if not self.strike_price:
            return 0.50, "INITIALIZING STRIKE..."

        secs_left = self.get_seconds_remaining()
        distance = self.current_spot - self.strike_price

        # Final 60-Second Settlement Window (BRTI 60s Simple Average Rule)
        if secs_left <= 60 and len(self.brti_ticks_60s) > 0:
            current_sum = sum(self.brti_ticks_60s)
            secs_recorded = len(self.brti_ticks_60s)
            needed_avg = ((self.strike_price * 60) - current_sum) / max(1, 60 - secs_recorded)
            
            if self.current_spot >= needed_avg:
                return 0.99, "SETTLEMENT LOCK (YES - Trend Sustained)"
            else:
                return 0.01, "SETTLEMENT LOCK (NO - Unattainable)"

        # Mid-Window Probability Engine
        volatility_per_sec = 2.5
        mo = abs(distance) / (volatility_per_sec * math.sqrt(secs_left))
        
        if distance >= 0:
            prob = 0.5 + (0.45 * (1 - math.exp(-mo * 0.2)))
        else:
            prob = 0.5 - (0.45 * (1 - math.exp(-mo * 0.2)))

        if prob >= 0.85:
            zone = "STRICT BUY ZONE (YES - High Probability)"
        elif prob <= 0.15:
            zone = "STRICT BUY ZONE (NO - High Probability)"
        elif secs_left < 180 and abs(distance) > 120:
            zone = "MID-SCALP MOMENTUM ZONE"
        else:
            zone = "NO TRADE ZONE (High Noise / Coin Flip)"

        return round(prob, 3), zone

    def compose(self) -> ComposeResult:
        yield Static("KALSHI 15-MIN BTC LIVE MONITOR", id="header-box")
        yield Static("Initializing Live Feed...", id="main-box")
        yield Footer()

    async def on_mount(self) -> None:
        if not self.strike_price:
            self.fetch_active_strike()
        self._spot_task = asyncio.create_task(self.coinbase_listener())
        self.set_interval(0.5, self.update_display)

    def update_display(self):
        secs_left = self.get_seconds_remaining()
        prob, zone = self.calculate_probability_and_zone()
        strike_disp = f"${self.strike_price:,.2f}" if self.strike_price else "FETCHING..."
        distance = self.current_spot - (self.strike_price or self.current_spot)

        content = f"""[b]State Engine[/b] ({self.market_ticker})

  [yellow]Target Strike Price:[/yellow]    {strike_disp}
  [yellow]Live Spot Feed (Coinbase):[/yellow] ${self.current_spot:,.2f}
  [yellow]Distance to Strike:[/yellow]       ${distance:+,.2f}
  [yellow]Time Remaining:[/yellow]           {secs_left // 60:02d}:{secs_left % 60:02d}
  [yellow]Model Probability:[/yellow]        {prob * 100:.1f}%
  [yellow]Signal Zone:[/yellow]              [green]{zone}[/green]

[dim]Bypassing human emotion. Press Ctrl+C or q to quit.[/dim]"""

        try:
            main_box = self.query_one("#main-box", Static)
            main_box.update(content)
        except Exception:
            pass

    async def coinbase_listener(self):
        uri = "wss://ws-feed.exchange.coinbase.com"
        subscribe_message = {
            "type": "subscribe",
            "product_ids": ["BTC-USD"],
            "channels": ["ticker"]
        }
        
        while True:
            try:
                async with websockets.connect(uri) as websocket:
                    await websocket.send(json.dumps(subscribe_message))
                    async for message in websocket:
                        data = json.loads(message)
                        if data.get("type") == "ticker" and "price" in data:
                            self.current_spot = float(data["price"])
                            self.brti_ticks_60s.append(self.current_spot)
                            if len(self.brti_ticks_60s) > 60:
                                self.brti_ticks_60s.pop(0)
                            
                            if self.get_seconds_remaining() > 890 or not self.strike_price:
                                self.fetch_active_strike()
            except Exception:
                await asyncio.sleep(3)

def main():
    strike = None
    if len(sys.argv) > 1:
        strike = float(sys.argv[1].replace(",", ""))
    
    if not HAS_TEXTUAL:
        print("Error: 'textual' library is not installed. Please run: pip install textual", file=sys.stderr)
        sys.exit(1)

    app = KalshiBTCMonitor(strike_price=strike)
    app.run()

if __name__ == "__main__":
    main()
