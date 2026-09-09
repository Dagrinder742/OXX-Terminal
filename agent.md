# OXX-Terminal Quant Agent: Technical Documentation

This document tracks the architecture, workflow, and evolution of the **OXX Quant Agent**, an autonomous analytical layer for the OXX Terminal.

## 1. Core Philosophy: The Trinity Quantitative Protocol
Agent Trinity is engineered as a **strictly technical analytical layer**. It prioritizes data deltas and objective telemetry over narrative interpretation. It utilizes a bifurcated perception/analysis cycle to maintain high-fidelity quantitative standards.

## 2. Architectural Components

### **A. Perception (Technical Tools)**
The Agent utilizes Python-based calculators to process raw OKX telemetry.
*   `fetch_okx_ticker`: Real-time instrument statistics.
*   `fetch_okx_candles`: Historical OHLCV data retrieval.
*   `fetch_rpi_index`: Relative Range Position Index (Mean Reversion).
*   `fetch_technical_indicators`: Recursive EMA and RSI calculation.
*   `fetch_order_book_walls`: Institutional liquidity block identification.
*   `check_quantitative_confluence`: Hierarchical 1H Macro and 15m Tactical gate evaluation.
*   `fetch_market_sentiment`: Multi-asset swap funding, Open Interest, and Liquidations.
*   `fetch_global_market_status`: Correlated basket scan (BTC, ETH, SOL, OKB).
*   `fetch_volatility_metrics`: ATR-based volatility and breakout assessment.
*   `record_structural_insight`: Persistent storage of institutional floors and macro shifts.
*   `fetch_historical_lookback`: Multi-day statistical analysis (Range/Volume/Performance).

### **B. Reasoning (LLM Engine)**
*   **Model Backend**: `llama-cpp-python` (Direct GGUF inference).
*   **Execution Strategy**: Forced CPU inference (`-ngl 0`) with a optimized **2048 token** context window (`-c 2048`) for high-efficiency on 8GB RAM hardware.
*   **Loop**: Perception -> Tool Call -> Observation -> Quantitative Analysis.
*   **Objective**: To deliver objective, data-driven market breakdowns.

### **C. Persistence (Memory Architecture)**
Trinity utilizes a bifurcated memory system:
*   **Long-Term (Structural)**: Permanent technical insights that do not expire.
*   **Short-Term (Tactical)**: Last 20 historical state transitions for trend delta detection.
*   **File**: `agent_memory.json`.

## 3. The "Recall" Workflow
1.  **Initialize**: Agent loads `agent_memory.json`.
2.  **Prompt**: User asks a question.
3.  **Context Injection**: Agent prepends the last 10 memory entries to the prompt.
4.  **Tool Catalog**: Agent sees all available tools and their descriptions.
5.  **Execution**: Agent calls the tool, receives data, and saves the new state to memory.
6.  **Analysis**: Agent provides a breakdown based on *Current Data* + *Memory*.

## 4. Autonomous Monitoring Mode
Trinity has been upgraded to a **standalone, persistent monitoring system**.
*   **GGUF Native**: Trinity runs directly via `llama-cpp-python`, eliminating the need for an external Ollama server.
*   **Bifurcated Loop**: The agent operates in an asynchronous loop, triggering a full quantitative deep-dive every **15 minutes** (synchronized with tactical candle closes).
*   **Autonomous Scribing**: The loop now explicitly instructs Trinity to identify and record significant structural support and resistance levels into her long-term memory.
*   **Dedicated Reporting**: Insights are streamed to a dedicated terminal, providing real-time strategic awareness alongside the main execution TUI.
*   **Resiliency**: The system handles network transients and inference timeouts with automatic re-alignment protocols.


## 5. Current Build Status
*   [x] Integrated `AgentMemory` into `agent.py`.
*   [x] Implemented Dynamic Tool Catalog injection.
*   [x] Enabled "Recall" (Memory-to-Prompt) context.
*   [ ] Integration of Technical Indicator tools (RSI/EMA).
*   [ ] Long-term "Key Levels" persistence.

---
*Note: This agent is powered by `phi4-mini`. To mitigate hallucinations, we use strict JSON schemas for tool output and comprehensive system instructions.*
