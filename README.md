# OXX-Terminal

OXX-Terminal is a high-performance Terminal User Interface (TUI) dashboard for OKX traders, built with **Textual** and **Rich**. It replicates a multi-pane web dashboard experience directly in the terminal, focusing on low-latency data feeds and secure credential management.

## 🚀 Features

- **Multi-Pane Dashboard**: Real-time ticker metadata, order book, trade feeds, and portfolio views.
- **Secure Auth**: OS-level encrypted credential storage using `keyring` (AES-128 GCM).
- **Live Market Data**: Hybrid data pipeline using `asyncio` + WebSockets for live updates and REST for instant hydration.
- **Order Execution**: Integrated limit and market order entry with stop-loss (SL) and take-profit (TP) support.
- **Smart Input**: Flexible instrument search (e.g., `btc` -> `BTC-USD`).
- **Technical Analysis**: ASCII/Unicode charting engine with support for candlesticks and indicators (EMA/RSI).

## 🛠️ Architectural Stack

- **UI Framework**: [Textual](https://textual.textualize.io/) & [Rich](https://rich.readthedocs.io/)
- **Network**: `asyncio`, `websockets`, `requests`
- **Security**: `keyrings.cryptfile` (AES-128 GCM)
- **Data Source**: [OKX v5 API](https://www.okx.com/docs-v5/)

## 📁 Project Structure

- `main.py`: Entry point and application orchestration.
- `api_client.py`: Manages public WebSocket streams and REST market data.
- `okx_private.py`: Handles authenticated REST requests (orders, balance, positions).
- `auth.py`: Signature mapping and authentication helpers.
- `chart_renderer.py`: ASCII charting engine for candlesticks.
- `secure_vault.py` & `secure_store.py`: Secure credential persistence layer.
- `strategy_engine.py`: Logic for automated trading strategies (Grid/DCA).

## 🚦 Getting Started

### Prerequisites

- Python 3.10+
- A valid OKX API Key, Secret, and Passphrase.

### Setup

1. **Install dependencies**:
   ```bash
   pip install textual rich websockets requests keyring keyrings.cryptfile
   ```

2. **Run the application**:
   ```bash
   python3 main.py
   ```

3. **Authentication**:
   On the first run, the application will prompt you for your OKX API credentials via a secure modal. These are stored using your OS's secure keyring.

## ⌨️ Hotkeys

- `Ctrl+Q`: Quit the application.
- `Enter`: Submit order or search.
- `T`: (Planned) Cycle chart timeframes.

---
*Disclaimer: This is a trading tool. Use at your own risk.*
