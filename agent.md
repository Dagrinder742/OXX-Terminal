# OXX-Terminal Quant Agent: Technical Documentation

This document tracks the architecture, workflow, and evolution of the **OXX Quant Agent**, an autonomous analytical layer for the OXX Terminal.

## 1. Core Philosophy
The Agent is designed as a **read-only reasoning layer**. It observes market telemetry and historical data to provide tactical insights without the risk of autonomous execution. It adheres to the "Snowman Standard" of high-fidelity data processing and secure memory management.

## 2. Architectural Components

### **A. Perception (Tools)**
The Agent interacts with the outside world (OKX API) through registered Python functions.
*   `fetch_okx_ticker`: Real-time 24h stats.
*   `fetch_okx_candles`: Historical OHLCV data.
*   `fetch_rpi_index`: Proprietary Daily Range Position Index (Sentiment).
*   `fetch_technical_indicators`: Real-time EMA-9, EMA-21, and RSI-14 calculation.
*   `fetch_order_book_walls`: Liquidity depth analysis (Big Money tracking).
*   `check_quantitative_confluence`: Hierarchical Analytics Engine (1H Boss + 15m Tactical Gates).
*   `fetch_market_sentiment`: Institutional metrics (Funding Rates, Open Interest, Liquidations).
*   `read_internal_signals`: Local quantitative signal history (Ledger).

### **B. Reasoning (LLM Loop)**
*   **Model**: `phi4-mini` (Local Ollama).
*   **Loop**: Perception -> Tool Call -> Observation -> Analysis.
*   **Dynamic Tool Selection**: Instead of hardcoded aliases, the Agent is provided with a "Tool Catalog" in its system prompt. It selects the best tool based on the functional description.

### **C. Persistence (Memory)**
*   **File**: `agent_memory.json`
*   **Recall**: Before every analytical turn, the Agent reads the last 10 historical events. This allows for **Temporal Awareness** (e.g., comparing current price to the last recorded support level).
*   **Auto-Commit**: Successful tool observations are automatically distilled and saved to the memory ledger.

## 3. The "Recall" Workflow
1.  **Initialize**: Agent loads `agent_memory.json`.
2.  **Prompt**: User asks a question.
3.  **Context Injection**: Agent prepends the last 10 memory entries to the prompt.
4.  **Tool Catalog**: Agent sees all available tools and their descriptions.
5.  **Execution**: Agent calls the tool, receives data, and saves the new state to memory.
6.  **Analysis**: Agent provides a breakdown based on *Current Data* + *Memory*.

## 4. Current Build Status
*   [x] Integrated `AgentMemory` into `agent.py`.
*   [x] Implemented Dynamic Tool Catalog injection.
*   [x] Enabled "Recall" (Memory-to-Prompt) context.
*   [ ] Integration of Technical Indicator tools (RSI/EMA).
*   [ ] Long-term "Key Levels" persistence.

---
*Note: This agent is powered by `phi4-mini`. To mitigate hallucinations, we use strict JSON schemas for tool output and comprehensive system instructions.*
