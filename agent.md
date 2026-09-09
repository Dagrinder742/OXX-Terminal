# OXX-Terminal Quant Agent: Technical Documentation

This document tracks the architecture, workflow, and evolution of the **OXX Quant Agent**, an autonomous analytical layer for the OXX Terminal.

## 1. Core Philosophy: The Trinity Quantitative Protocol
Agent Trinity is engineered as a **strictly technical analytical layer**. It prioritizes data deltas and objective telemetry over narrative interpretation. It utilizes a bifurcated perception/analysis cycle to maintain high-fidelity quantitative standards.

## 2. Architectural Components

### **A. Perception (Technical Tools)**
*   `ai_chart_analyzer`: Aggregated analysis of Price, Volatility, and Indicators.
*   `fetch_smart_patterns`: Structural identification of Channels and Volatility Compression.
*   `ai_mentor`: Real-time quantitative tutor for market nomenclature.
*   `fetch_market_sentiment`: Institutional money flow (Funding/OI/Liquidations).
*   `check_quantitative_confluence`: 4-Gate tactical setup evaluation.

### **B. Reasoning (Strategy & Education)**
*   **MOMENTUM**: Focused on breakout confluence and trend acceleration.
*   **BALANCED**: Focused on mean reversion from compression zones near support.
*   **Notification Cards**: Standardized alerts with Entry, SL, and Target specifications.
*   **AI Mentor**: Trinity acts as a tutor, explaining the 'Why' behind every setup match in plain language.



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
