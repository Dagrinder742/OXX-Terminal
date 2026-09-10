# OXX-Terminal Quant Agent: Technical Documentation

This document tracks the architecture, workflow, and evolution of **Agent Trinity**, an autonomous analytical layer for the OXX Terminal.

## 1. Core Philosophy: The Trinity Quantitative Protocol
Agent Trinity is a **strictly technical spot-only analytical unit**. She is engineered for US-compliant trading (Buy Low / Sell High) and prioritizes deterministic data over narrative interpretation. She utilizes a **Pipeline Architecture** to ensure mathematical precision and logical grounding.

## 2. Architectural Components

### **A. Pre-Inference Pipeline (Python Engine)**
Unlike standard agents that "guess" how to use tools, Trinity uses a hard-coded Python pre-processor to gather a high-fidelity **Market Snapshot** before reasoning begins:
*   **Deterministic Perception**: Automatically fetches Ticker data, calculates EMA (9/21), and scans News Wire sentiment.
*   **Hard-Coded Math**: Pre-computes **SPOT_ACCUMULATION** levels (Entry, SL, TP) using strict risk parameters (0.75% Stop-Loss, 1.5% net profit hurdle + 0.4% OKX fees).
*   **US Endpoint Lock**: All telemetry is routed through `us.okx.com`.

### **B. Strategic Reasoning (LLM Engine)**
*   **Chain of Thought (CoT)**: Trinity is programmed with an "Internal Voice." Every response begins with a `<thinking>` block to deliberate on technical trend vs. news sentiment.
*   **Spot-Only Logic**: Restricted to US Spot mechanics. No mention of shorting, margin, or leverage.
*   **Single-Shot Verdict**: Evaluates the pre-computed snapshot to provide a professional Strategic Verdict and Notification Card.
*   **Hardware Profile**: Optimized for 8GB RAM using `llama-cpp-python` with a **16,384 token** context window.

### **C. Persistence & Intelligence**
*   **News Engine**: A bifurcated async background poller (`news_engine.py`) that synchronizes the Cointelegraph RSS wire and performs VADER sentiment scoring every 10 minutes.
*   **Memory Architecture**: Bifurcated system in `agent_memory.json` tracking **Long-Term Structural Insights** and **Short-Term Tactical History** (Last 20 entries).

## 3. The "Pipeline" Workflow
1.  **Pulse**: Python gathers live telemetry and news sentiment.
2.  **Snapshot**: Python calculates fee-aware SL/TP levels.
3.  **Inference**: The LLM evaluates the snapshot through a single-shot prompt.
4.  **Verdict**: Trinity provides a plain-text breakdown and Notification Card.
5.  **Commit**: The final state is committed to historical memory.

## 4. Autonomous Monitoring Mode
Trinity operates as a **standalone, persistent monitoring system** requiring no external servers.
*   **Dual-Engine Sync**: Main agent and News Engine run concurrently via `asyncio`.
*   **15-Minute Cycles**: Full quantitative deep-dives synchronized with tactical candle closes.
*   **Setup Hunting**: Specifically looks for high-probability Spot Accumulation zones that overcome the 0.4% round-trip fee hurdle.

## 5. Current Build Status
*   [x] Transitioned to **Spot-Only US Architecture**.
*   [x] Implemented **Single-Shot Pipeline** logic (Eliminated loop slippage).
*   [x] Integrated **Async News Engine** with Sentiment Scoring.
*   [x] Expanded context window to **16k tokens**.
*   [x] Locked **Chain of Thought** internal reasoning.

---
*Note: Trinity is powered by `phi4-mini`. We use deterministic Python pre-processing to eliminate hallucinations and ground the model in real-time technical reality.*
