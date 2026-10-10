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

HAS_RICH = True
try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    console = Console()
except ImportError:
    HAS_RICH = False

class KalshiBTCMonitor:
    def __init__(self, strike_price: float = None):
        self.strike_price = strike_price
        self.current_spot = strike_price if strike_price else 82900.00
        self.brti_ticks_60s = []
        self.market_ticker = "AUTO-FETCHING..."

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

    def render(self):
        secs_left = self.get_seconds_remaining()
        prob, zone = self.calculate_probability_and_zone()
        strike_disp = f"${self.strike_price:,.2f}" if self.strike_price else "FETCHING..."

        if HAS_RICH:
            layout = Layout()
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="main", size=11),
                Layout(name="footer", size=3)
            )
            layout["header"].update(Panel(Text("KALSHI 15-MIN BTC LIVE MONITOR", style="bold cyan", justify="center"), style="blue"))

            table = Table(show_header=False, expand=True)
            table.add_column("Metric", style="bold yellow")
            table.add_column("Value", style="bold white")

            table.add_row("Target Strike Price", strike_disp)
            table.add_row("Live Spot Feed (Coinbase)", f"${self.current_spot:,.2f}")
            table.add_row("Distance to Strike", f"${self.current_spot - (self.strike_price or self.current_spot):+,.2f}")
            table.add_row("Time Remaining", f"{secs_left // 60:02d}:{secs_left % 60:02d}")
            table.add_row("Model Probability", f"{prob * 100:.1f}%")
            table.add_row("Signal Zone", f"[bold green]{zone}[/bold green]")

            layout["main"].update(Panel(table, title=f"State Engine ({self.market_ticker})", border_style="green"))
            layout["footer"].update(Panel(Text("Bypassing human emotion. Press Ctrl+C to quit.", style="dim"), border_style="yellow"))
            
            console.clear()
            console.print(layout)

async def coinbase_listener(monitor):
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
                        monitor.current_spot = float(data["price"])
                        monitor.brti_ticks_60s.append(monitor.current_spot)
                        if len(monitor.brti_ticks_60s) > 60:
                            monitor.brti_ticks_60s.pop(0)
                        
                        if monitor.get_seconds_remaining() > 890 or not monitor.strike_price:
                            monitor.fetch_active_strike()
                            
                        monitor.render()
        except Exception:
            await asyncio.sleep(3)

async def main():
    monitor = KalshiBTCMonitor()
    if len(sys.argv) > 1:
        monitor.strike_price = float(sys.argv[1].replace(",", ""))
    else:
        monitor.fetch_active_strike()
        
    await coinbase_listener(monitor)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nMonitor closed.")

