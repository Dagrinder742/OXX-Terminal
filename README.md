# OXX-Terminal

OXX-Terminal is a high-performance trading environment for OKX, featuring a hybrid architecture of a **Reactive TUI Dashboard** and an autonomous **Quant AI Agent (Trinity)**. Designed for dual-terminal operation, it provides professional traders with a unified execution and analytical suite.

## 🏗️ Dual-Terminal Architecture

The system is engineered to run in a bifurcated environment:
1.  **OXX TUI (The Executioner)**: A high-resolution Textual dashboard for real-time market depth, technical charting, and multi-strategy order execution.
2.  **Quant Agent Trinity (The Brain)**: A local LLM-powered analytical layer (`phi4-mini`) that processes institutional telemetry and technical indicators to provide objective, non-custodial market breakdowns.

## 🚀 Key Components & Features

### **1. OXX TUI Terminal (`main.py`)**
- **Multi-Pane Dashboard**: Real-time ticker metadata, order book, trade feeds, and portfolio views.
- **Order Execution**: Integrated limit and market order entry with stop-loss (SL) and take-profit (TP) support.
- **Strategy Control**: Management panel for Arithmetic/Geometric Grid bots and DCA execution.
- **Smart Input**: Flexible instrument search (e.g., `btc` -> `BTC-USDT`).
- **ASCII Charting**: High-fidelity Unicode charting engine with live EMA and RSI overlays.

### **2. Quant Agent Trinity (`agent.py`)**
- **Hierarchical Analytics Engine**: Autonomous evaluation of 1H Macro Filters and 15m Tactical Confluence Gates.
- **Institutional Sentiment**: Real-time tracking of Funding Rates, Open Interest, and Global Liquidations.
- **Temporal Memory (Recall)**: Persistent JSON memory allows the agent to identify trend deltas and structural shifts between sessions.
- **Multi-Tool Perception**: Dynamic orchestration of technical indicators and order book liquidity walls.

## 🛠️ Architectural Stack

- **UI Framework**: [Textual](https://textual.textualize.io/) & [Rich](https://rich.readthedocs.io/)
- **AI Engine**: Local [Ollama](https://ollama.com/) running `phi4-mini`.
- **Logic Layer**: Strictly objective Python-based quantitative math (EMA, MACD, RSI).
- **Security**: AES-128 GCM encrypted credential storage via `keyrings.cryptfile`.
- **Data Source**: OKX v5 REST & WebSocket API.

## 📁 Project Structure

- `main.py`: TUI Application orchestrator.
- `agent.py`: Quant Agent Trinity (AI Analytical Engine).
- `api_client.py`: Public market data management (WS/REST).
- `okx_private.py`: Authenticated trading and account management.
- `chart_renderer.py`: ASCII/Unicode candlestick rendering engine.
- `strategy_engine.py`: Local execution logic for automated strategies.
- `secure_vault.py`: Secure credential persistence layer.

## 🚦 Getting Started

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com/) with `phi4-mini` installed.
- OKX API Credentials (Key, Secret, Passphrase).

### Setup
1. **Install Python dependencies**:
   ```bash
   pip install textual rich websockets requests keyring keyrings.cryptfile ollama
   ```

2. **Launch the TUI (Terminal 1)**:
   ```bash
   python3 main.py
   ```

3. **Launch Trinity (Terminal 2)**:
   ```bash
   python3 agent.py
   ```

## ⌨️ Global Hotkeys
- `Ctrl+Q`: Exit Application.
- `Enter`: Submit order / search.
- `T`: (Planned) Cycle chart timeframes.

---
*Disclaimer: This is a professional trading tool. Use at your own risk.*
