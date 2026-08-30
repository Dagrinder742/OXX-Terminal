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
## THE ONYX TERMINAL (The code is just the vehicle; the conversation is where the actual architecture lives.)
# ------------------------------------------------------------------------------------------------
Are we approaching a tipping point if a developer can distill the extreme mathematical of 
visual complexity of a high frequency financial platform back down to pure hyper fast 
terminal text strings? What other massive daily software applications are secretly ripe for 
a retro TUI revolution? We are so obsessed with pushing graphics forward, what if the 
future of software development forces us to look backwards?

#the start 
The goal is to replicate a multi-pane web dashboard layout within a terminal environment 
using **Textual** and **Rich**. This project focuses on high-performance data pipelines and secure, 
OS-level credential management.

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
* [x] **Flattened Bot UI Architecture**: Resolved layout "bottoming out" issues by flattening nested horizontal rows into a linear vertical sequence for reliable border rendering.
* [x] **Cross-Platform Compatibility**: Implemented environment detection and adaptive rendering to support stable, synchronized charts on both Windows (PowerShell) and Linux (Termux/mobile). Standardized on `plotext==5.3.2` for cross-platform API stability.

---

## 5. Feature Roadmap & Brainstorming
### High-Priority Enhancements
* [x] **Technical Overlays**: Added EMA-9, EMA-21, and RSI-14 indicators using a robust **Decoupled Multi-Container Chart Architecture** for maximum cross-platform stability.
* [x] **Strategy Engine Core**: Fully implemented Grid and DCA trade logic with robust position tracking and PnL calculation.
* [x] **Onyx Ticker Board (Live Watchlist)**: Integrated a high-performance, 24-pair market hub that tracks live prices and 24h % changes across Majors, L1s, and DeFi assets, featuring a dedicated `USDT-USD` macro liquidity anchor.
* [x] **Order History & Session Fills**: Added a dedicated view to track executed orders and bot fills for the active session.
* [x] **Session Live PnL**: Implement live calculation of cumulative profit/loss for the current active bot session.
* [x] **Advanced Orders**: Add inputs for Stop-Loss (SL) and Take-Profit (TP) to the Order Entry panel.
* [x] **Multi-Pair Switching**: Implement hotkeys or a picker to swap instruments (e.g., BTC to ETH) without restarts.
* [x] **Grid Bot Hooks**: Integrate hooks to monitor live PnL and threshold data from active bots.
* [x] **Candle Stick Charts**: Integrated live, auto-refreshing ASCII candlestick charts with `plotext` and `Rich` for a professional-grade TUI aesthetic.
* [x] **Handling Open Orders/Positions Tracking**: Tracking of unfilled orders that are on the books either higher or lower than current market.
* [x] **Market Sentiment Hub**: Integrated a custom Daily Range Position Index (RPI) to provide a tactical edge without cluttering the layout.
* [x] **Bot Range**: Added dedicated inputs for Lower and Upper price bounds to define the trading corridor for Grid bots.
* [x] **Dynamic Credential Manager**: Added a "MANAGE API KEYS" interface to allow on-the-fly updates to API credentials without restarting the application.
* [x] **Smart Quick Load (25%-100%)**: Implemented a professional-grade percentage selector for order entry that automatically calculates buy/sell quantities based on real-time portfolio balances and market price.
* [x] **Total USD Cost Estimation**: Integrated a dedicated price estimation field that synchronizes with the Quick Load feature to provide immediate transparency on the total cost of an order.
* [x] **Exchange-Grade Validation**: Implemented production-grade OKX validation rules for spot grid creation, including price containment, investment thresholds, and grid limits.
* [ ] **The Money Counter (Session PnL Aggregator)**: Build a high-fidelity USD readout that aggregates every manual trade, grid fill, and DCA action into a single "Session Net" score. [IN EXPLORATION]
* [ ] **The Flash Trigger (Global Hotkeys)**: Implement keyboard shortcuts (e.g., SHIFT+B/S) for instant market execution on the focus instrument. [IN EXPLORATION]
* [ ] **The Alert Hub (Deep Value Pings)**: Add a background monitor that triggers visual/log alerts when high-liquidity assets hit the RPI "Star Blue" Dip Zone (<15%). [IN EXPLORATION]
---

## 6. TUI Architectural Lessons & Troubleshooting
### The "Bottom Falling Out" Border Issue
*   **Problem**: In complex Textual layouts, borders around panels with nested `Horizontal` and `Vertical` rows often fail to render or "bottom out" (leaving the bottom border open).
*   **Cause**: Textual's layout engine can struggle to calculate the cumulative height of nested rows containing `Input` or `Button` widgets before the parent's `height: auto` border is drawn.
*   **Solution (Flattening)**: Flatten the composition of dynamic panels. Instead of nesting widgets in multiple horizontal rows, yield them in a direct vertical sequence. This ensures the layout engine calculates the height correctly and locks the borders.
*   **Scrollbar Stability**: For complex dashboards, a single page-level `VerticalScroll` is significantly more stable than nested `VerticalScroll` containers for sidebar components, which can cause height calculation conflicts.
*  * **Fixed vs. Fluid Widths**: Using fixed character widths (e.g., `width: 48;`) for sidebar columns prevents text-wrapping reflows that can break border alignments during terminal resizing.

### The "Telemetry Clutter" Trap
*   **Lesson**: Adding too much secondary data (like broad market tickers) into a focused execution terminal can dilute the user's tactical focus.
*   **Result**: Scrapped the "DEX & MAINNET Hub" experiment. It added visual noise (generic tables) without improving execution speed or trend analysis. 
*   **Takeaway**: Keep the primary dashboard optimized for the active instrument. Secondary telemetry should be high-signal (like volatility or RSI across a watchlist) or hidden behind a toggle.

---

## 7. OKX Exchange Compliance & Grid Validation
To ensure the OXX Terminal operates as a production-grade portal for the OKX ecosystem, we have implemented the following rigorous exchange-side rules:

### Spot Grid Core Constraints
*   **Arithmetic vs. Geometric Spacing**: 
    *   **Arithmetic**: Equal price difference between levels ($P_{n} - P_{n-1} = \text{Constant}$).
    *   **Geometric**: Equal ratio/percentage difference between levels ($\frac{P_n}{P_{n-1}} = \text{Constant}$).
*   **Price Boundary Containment**: The bot initialization is strictly blocked unless the current market price sits within the user-defined `[Lower Price, Upper Price]` range.
*   **Investment Thresholds**: Enforces a minimum investment per grid slice (default: $1.00) to ensure orders meet exchange minimum size requirements.
*   **Grid Quantity Limits**: Enforces OKX-standard grid counts between **2 and 150** levels.

### User Feedback & Safety
*   **Real-Time Validation**: The terminal performs a pre-flight check before submitting algo orders. If validation fails, the UI provides immediate visual feedback (e.g., a "Validation Error" toast) and logs the specific rule violation to the Execution Log.
*   **Dynamic Range Defaulting**: If range inputs are left blank, the system intelligently defaults to a $\pm 2\%$ corridor around the current mid-price to prevent "trigger errors" on launch.

---

## 8. Custom Indicator: Daily Range Position Index (RPI)
To provide users with an immediate, high-signal decision support tool, the OXX Terminal features a proprietary **Daily Range Position Index (RPI)**. This indicator is engineered to solve the "Is it a good time to buy?" dilemma by visualizing exactly where the current price sits within its 24-hour cycle.

### How It Works (The Math)
The RPI is calculated locally for all 24 pairs in the Market Hub using live WebSocket ticker data:

$$RPI = \frac{Current Price - Low_{24h}}{High_{24h} - Low_{24h}} \times 100$$

*   **0%**: The asset is trading at its absolute 24-hour low.
*   **100%**: The asset is trading at its absolute 24-hour high.

### Tactical Visual Cues (Steelers Star Theme)
The Market Hub uses professional, high-contrast color coding to allow traders to scan 24 pairs in under a second:

| Zone | RPI Range | Color | Signal |
| :--- | :--- | :--- | :--- |
| **Dip Zone** | 0% - 30% | **Star Blue (#3399ff)** | High Value: Asset is cooling near its daily floor. |
| **Neutral** | 30% - 70% | **White (#ffffff)** | Consolidation: Trading within normal mid-range bounds. |
| **Chase Zone** | 70% - 100% | **Star Red (#ff3333)** | Caution: Asset is overextended and pushing daily highs. |

### User Benefits
*   **Zero-Gap Coverage**: Unlike standard sentiment APIs that only support "Major" pairs, the RPI works for all 24 pairs in the watchlist.
*   **Anti-FOMO Guardrail**: Prevents "chasing green candles" by visually flagging assets that are already at the top of their daily range.
*   **Mean Reversion Edge**: Helps identify deep-value dips that are objectively oversold relative to the last 24 hours of price action.

---

## 9. Engineering Best Practices: Robust Error Handling & Logging
To ensure the OXX Terminal remains grounded and maintainable across future updates, we have standardized on a high-fidelity logging pattern across the entire codebase.

### The `exc_info=True` Standard
Every critical `try...except` block in the application is engineered to capture full tracebacks rather than just generic error strings.

**The Pattern:**
```python
try:
    # Critical UI or Data Operation
    self.query_one(widget_id, Static).update("\n".join(lines))
except Exception as e:
    logging.warning(f"Operation failed: {e}", exc_info=True)
```

### Why This Matters
1.  **Immediate Diagnostics**: When a widget update glitches or an async race condition occurs, the logs provide the exact line number and function call stack.
2.  **Zero-Blind Updates**: Future developers (or AI agents) can refactor core logic with confidence, knowing that any regression will be explicitly detailed in the console or log files.
3.  **Proactive Triage**: By differentiating between `logging.debug`, `warning`, and `error` while always tacking on the traceback, we ensure that session stability can be monitored in real-time without hunting through the codebase.

This architectural requirement is enforced across `main.py`, `api_client.py`, `okx_private.py`, and the `chart_renderer.py` to maintain production-grade reliability.

### Worker Exclusivity (The Singleton Pattern)
To prevent "CPU Traffic Jams" and terminal freezes in resource-constrained environments (like Termux/mobile), we enforce a **Singleton Worker** pattern for heavy UI renders.

**The Implementation:**
```python
self.run_worker(load_task, name="chart_update", exclusive=True)
```

**Key Advantages:**
*   **Zero-Freeze Performance**: By using `exclusive=True`, the application automatically kills any existing background task with the same name before starting a new one. This prevents multiple heavy threads (like ASCII chart builders) from fighting for the same CPU resources.
*   **Race Condition Mitigation**: Ensures that if a user rapidly clicks through timeframes, the TUI only ever renders the *latest* request, maintaining a snappy and responsive interface regardless of hardware power.
