# ================================================================================================
# OXX-Terminal-US ENDPOINTS
# us.okx.com
# wss://ws.okx.com:8443/ws/v5/public
# ================================================================================================
# PACKAGE VERSIONS
# ================================================================================================
# Plotext 5.3.2
# Python 3.14.6
# Rich 15.0.0
# Textual 8.2.8
# Keyrings.cryptfile 1.3.9
# Websockets 15.0.1
# Asyncio 4.0.0
# ================================================================================================
## OXX Terminal Project Roadmap
# ------------------------------------------------------------------------------------------------
## THE ONYX TERMINAL
# ------------------------------------------------------------------------------------------------

## 1. Project Overview & Blueprint
The goal is to replicate a multi-pane web dashboard layout within a terminal environment using **Textual** and **Rich**. This project focuses on high-performance data pipelines and secure, OS-level credential management.

### UI Layout Mapping
| Section | Function | Implementation |
| :--- | :--- | :--- |
| **Header** | Ticker metadata & 24h stats | `Header` / `Static` |
| **Left Sidebar** | Portfolio & Order Entry | `Vertical` / `Input` / `Button` |
| **Center/Right** | Order Book & Trades Feed | `Horizontal` / `Vertical` panels |
| **Bottom** | Execution & Activity Logs | `Static` log window |

---

## 2. Architectural Stack
* **UI Framework**: `Textual` (for event-driven TUI) and `Rich` (for formatting).
* **Data Layer**: `asyncio` + `websockets` for low-latency public/private feeds.
* **Security**: `keyrings.cryptfile` backend for OS-level encrypted credential storage (AES-128 GCM).
* **Endpoints**: Routing strictly to `us.okx.com` for US-based access.

---

## 3. Modular File Structure
* `main.py`: Entry point; orchestrates app state, dynamic instrument search parsing, and widget layout.
* `api_client.py`: Manages WebSocket connections, public market streams, and instant REST trade snapshots.
* `okx_private.py`: Handles authenticated REST requests (signing, ordering, balance).
* `secure_vault.py`: Interacts with `keyring` for encrypted credential persistence.
* `auth.py`: Handles authentication helper sequences and signature mapping.
* `renderer.py`: Houses TUI layout formatting and visual widget rendering logic.
* `secure_store.py`: Low-level wrapper for OS credential storage integrations.
* `chart_renderer.py`: Fetches historical OHLCV data and renders terminal-grade ASCII candlestick charts using `plotext==5.3.2`.
* `strategy_engine.py`: Local logic for grid bots/DCA execution.

---

## 4. Development Log (Completed)
* [x] **Modular Structure**: Initialized core project files (`main.py`, `api_client.py`, `okx_private.py`, `secure_vault.py`, `auth.py`, `renderer.py`, `secure_store.py`, `strategy_engine.py`).
* [x] **Secure Auth**: Implemented `keyrings.cryptfile` and the `AuthModal` TUI for first-run setup.
* [x] **API Connectivity**: Wired `us.okx.com` endpoints for account balance and order execution.
* [x] **TUI Dashboard**: Built reactive layout with Portfolio, Order Book, Last Trades, and Execution Log.
* [x] **OXX Terminal Rebranding**: Updated dynamic header UI strings and layout branding across `main.py` and `renderer.py.
* [x] **Smart Input Normalization**: Added flexible search parsing supporting space-to-hyphen translation and defaulting bare tickers strictly to USD quotes.
* [x] **Instant Last Trades Hydration**: Implemented a hybrid REST snapshot fetch (`/api/v5/market/trades`) on pair switch for immediate browser-grade trade feed loading before live WebSockets take over.
* [x] **Grid Bot Control Integration**: Integrated a dedicated sidebar panel for automated strategy oversight with live PnL and status hooks. Consolidated with active order tracking.
* [x] **Session Order History & Fills**: Implemented real-time tracking of executed manual and bot trades with a dedicated history pane.
* [x] **Steelers "Star" UI Theme**: Rebranded the entire TUI with a Deep Black and Steelers Gold palette, accented by Star Blue (Buy) and Star Red (Sell/Stop) highlights.
* [x] **Open Orders & Positions Tracking**: Integrated periodic background polling for resting limit/stop orders and active trading positions with live color-coded PnL readouts.
* [x] **Browser-Style Page Scrolling**: Implemented a vertical scrollable viewport (`VerticalScroll`) allowing panels to expand naturally beyond the terminal window height.
* [x] **Terminal Candlestick Engine**: Integrated `plotext` and `Rich` to render live, auto-refreshing ASCII price charts with clickable timeframe selectors.
* [x] **TUI Rendering Polish**: Resolved ASCII "ghosting" and duplication artifacts through precise coordinate locking, ANSI sequence cleaning, and disabling text wrapping on chart widgets.
* [x] **Minimalist UI**: Hidden the visual scrollbar and refined notification borders to eliminate layout "eye sores" while maintaining full navigation functionality.
* [x] **Cross-Platform Compatibility**: Implemented environment detection and adaptive rendering to support stable, synchronized charts on both Windows (PowerShell) and Linux (Termux/mobile). Standardized on `plotext==5.3.2` for cross-platform API stability.

---

## 5. Feature Roadmap & Brainstorming
### High-Priority Enhancements
* [x] **Technical Overlays**: Added EMA-9, EMA-21, and RSI-14 indicators using a robust **Decoupled Multi-Container Chart Architecture** for maximum cross-platform stability.
* [ ] **Strategy Engine Core**: Implement the trade logic in `strategy_engine.py` and wire it to the TUI "Start/Stop" controls.
* [ ] **Market Watchlist**: Add a multi-asset ticker tape or "Top Movers" grid for broader market oversight.
* [x] **Order History & Session Fills**: Added a dedicated view to track executed orders and bot fills for the active session.
* [x] **Session Live PnL**: Implement live calculation of cumulative profit/loss for the current active bot session.
* [x] **Advanced Orders**: Add inputs for Stop-Loss (SL) and Take-Profit (TP) to the Order Entry panel.
* [x] **Multi-Pair Switching**: Implement hotkeys or a picker to swap instruments (e.g., BTC to ETH) without restarts.
* [x] **Grid Bot Hooks**: Integrate hooks to monitor live PnL and threshold data from active bots.
* [x] **Candle Stick Charts**: Integrated live, auto-refreshing ASCII candlestick charts with `plotext` and `Rich` for a professional-grade TUI aesthetic.
* [x] **Handling Open Orders/Positions Tracking**: Tracking of unfilled orders that are on the books either higher or lower than current market.
* [ ] **Expanding Our DEX/Token Telemetry Feeds**: making a dedicated section for DEX based assets away from MAINNET.
* [ ] **Bot Range**: we need to add the target range for bots execution e.g. 60k to 85k
---
# ================================================================================================
## 6. NOTES FOR HOW TO COMPLETE THE WORK ABOVE (delete as work finishes)
# ================================================================================================
Textual can definitely handle ASCII/Unicode charting, and bringing candlestick or line charts 
directly into the TUI layout will give OXX Terminal that authentic, professional-grade trading 
terminal aesthetic. look at pulling historical candle data via REST for terminal chart view.

That is the exact right approach. Building a live, multi-indicator ASCII chart in a TUI requires solid architecture upfront so it doesn't stutter when you switch pairs or choke on high-frequency candle updates.

Let's break down the blueprint for our **Terminal Candlestick Engine** so we can architect it cleanly before writing a single line of charting code.

---

### 1. Timeframe Strategy: Fixed vs. Customizable

* **The Verdict:** Start with a **default timeframe (e.g., 15m or 1H)**, but build it with a dynamic parameter so you can toggle it.
* **Why:** Hardcoding 15m is great for a stable default view, but professional dashboards always need flexibility. If we pass the timeframe variable (e.g., `1m`, `5m`, `15m`, `1H`, `1D`) into both our REST fetcher and WebSocket candle subscription channel, we can easily hook up a keyboard shortcut (like pressing `T` to cycle timeframes) down the road.
* **OKX Endpoint Support:** OKX provides native candle channels (`candle1m`, `candle15m`, `candle1H`, etc.) via both REST (`/api/v5/market/candles`) and their public WebSocket.
make the time periods like the web browser .. you can click them to change time frame if possible... will have to work that one out 
### 2. Technical Indicators: RSI & EMA Lines

Adding an Exponential Moving Average (EMA) and a Relative Strength Index (RSI) sub-panel transforms the chart from a novelty into a genuine analytical tool.

* **EMA (Exponential Moving Average):** Highly recommended. A short-term EMA (like a 9-period or 21-period EMA) rendered as an overlay line right on top of the ASCII candles gives immediate visual trend context. It's relatively lightweight to calculate locally in Python from the candle close array.
* **RSI (Relative Strength Index):** Can be placed as a compact sub-pane directly below or beside the main price chart (e.g., a standard 14-period RSI). However, vertical terminal space is tight, so we should design the chart widget to optionally toggle or stack indicators cleanly.

### 3. Handling Token Switching & Fresh Rendering

Just like we fixed for the Last Trades feed, switching instruments on a chart requires a strict lifecycle sequence to prevent ghost data from a previous token:

1. **Purge Buffer:** Clear the local candle history array (`self.cached_candles = []`) instantly on switch.
2. **REST Snapshot Hydration:** Fetch a historical batch of candles (e.g., the last 50–100 candles via `/api/v5/market/candles?instId=...&bar=15m`) so the chart populates *immediately* upon landing on a new pair.
3. **WebSocket Sub-Swap:** Unsubscribe from the old candle channel and subscribe to the new token's candle channel (`candle15m`) so live ticks append or update the current forming candle in real-time.

---

### Recommended Tooling for Textual

To render this smoothly inside a Textual `Static` widget without external graphical dependencies, we have two primary contenders:

* **Plotext:** Excellent for ASCII/ANSI plots, supports multiple lines (great for price candles + EMA lines), and handles terminal resizing well.
* **AsciiChartPy:** Lightweight, clean, but sometimes more rigid with multi-line overlays. (Plotext is usually the favorite for full dashboard charting).

How to structure the initial prototype for this? we draft a standalone `chart_renderer.py` module first to test pulling and drawing a 15m BTC-USD ASCII chart, or map out the specific UI layout space in `renderer.py`? or rename it and combine it to be the ultimate renderer view file 
