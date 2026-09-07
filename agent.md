# OXX-Terminal Quant Agent: Technical Documentation

This document tracks the architecture, workflow, and evolution of the **OXX Quant Agent**, an autonomous analytical layer for the OXX Terminal.

## 1. Core Philosophy
The Agent is designed as a **read-only analytical layer**. It observes market telemetry and historical data to provide professional quantitative insights. It follows a high-fidelity engineering standard for data processing and secure memory management.

## 2. Architectural Components

### **A. Perception (Tools)**
The Agent interacts with the outside world through strictly technical Python functions.
*   `fetch_okx_ticker`: Real-time instrument statistics.
*   `fetch_okx_candles`: Historical OHLCV data.
*   `fetch_rpi_index`: Relative price location index.
*   `fetch_technical_indicators`: Real-time EMA and RSI calculation.
*   `fetch_order_book_walls`: Liquidity depth analysis.
*   `check_quantitative_confluence`: Hierarchical trend and tactical gate evaluation.
*   `fetch_market_sentiment`: Institutional leverage and money flow metrics.

### **B. Reasoning (LLM Loop)**
*   **Model**: `phi4-mini`.
*   **Loop**: Perception -> Tool Call -> Observation -> Quantitative Analysis.
*   **Objective**: To deliver objective, data-driven market breakdowns.

### **C. Persistence (Memory)**
*   **Recall**: The Agent references the last 10 historical state transitions before analyzing new data to identify trend deltas.

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
