# ================================================================================================
# OXX-Terminal-US ENDPOINTS
# us.okx.com
# wss://ws.okx.com:8443/ws/v5/public
# ================================================================================================
# OXX Terminal Project Roadmap

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
* `strategy_engine.py`: Local logic for grid bots/DCA execution.

---

## 4. Development Log (Completed)
* [x] **Modular Structure**: Initialized core project files (`main.py`, `api_client.py`, `okx_private.py`, `secure_vault.py`, `auth.py`, `renderer.py`, `secure_store.py`, `strategy_engine.py`)[cite: 2].
* [x] **Secure Auth**: Implemented `keyrings.cryptfile` and the `AuthModal` TUI for first-run setup[cite: 2].
* [x] **API Connectivity**: Wired `us.okx.com` endpoints for account balance and order execution[cite: 2].
* [x] **TUI Dashboard**: Built reactive layout with Portfolio, Order Book, Last Trades, and Execution Log[cite: 2].
* [x] **OXX Terminal Rebranding**: Updated dynamic header UI strings and layout branding across `main.py` and `renderer.py`.
* [x] **Smart Input Normalization**: Added flexible search parsing supporting space-to-hyphen translation and defaulting bare tickers strictly to USD quotes.
* [x] **Instant Last Trades Hydration**: Implemented a hybrid REST snapshot fetch (`/api/v5/market/trades`) on pair switch for immediate browser-grade trade feed loading before live WebSockets take over.

---

## 5. Feature Roadmap & Brainstorming
### High-Priority Enhancements
* [ ] **Order History/Fills**: Add a view to track executed orders for the active session.
* [ ] **Advanced Orders**: Add inputs for Stop-Loss (SL) and Take-Profit (TP) to the Order Entry panel.
* [x] **Multi-Pair Switching**: Implement hotkeys or a picker to swap instruments (e.g., BTC to ETH) without restarts.
* [ ] **Grid Bot Hooks**: Integrate hooks to monitor live PnL and threshold data from active bots.
* [ ] **Candle Stick Charts**: Intergrate candle stick charts in the textual environment for greater visual effects.
