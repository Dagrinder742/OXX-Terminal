import json
import os
import sys
import logging
import requests
import difflib
import asyncio
from llama_cpp import Llama
from datetime import datetime

# Configure professional logging standard
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("QuantAgentTrinity")

# ================================================================================================
# MEMORY ENGINE
# ================================================================================================

class AgentMemory:
    """Handles persistent JSON storage for historical telemetry and notes."""
    def __init__(self, memory_file="agent_memory.json"):
        self.memory_file = memory_file
        self.data = self.load_memory()

    def load_memory(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if "structural_insights" not in content: content["structural_insights"] = {}
                    if "history" not in content: content["history"] = []
                    return content
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Memory parse error: {e}", exc_info=True)
        return {"structural_insights": {}, "history": []}

    def save_memory(self):
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def save_market_memory(self, inst_id: str, market_state: str, support_level: float, resistance_level: float):
        memory_entry = {
            "timestamp": datetime.now().isoformat(),
            "instrument": inst_id,
            "market_state": market_state,
            "support": support_level,
            "resistance": resistance_level
        }
        self.data["history"].append(memory_entry)
        self.data["history"] = self.data["history"][-20:]  # Expanded history capacity
        self.save_memory()
        return f"Successfully committed memory state for {inst_id} to disk."

    def save_structural_insight(self, key: str, value: str):
        """Saves a permanent structural insight (support/resistance/macro trend)."""
        self.data["structural_insights"][key] = {
            "timestamp": datetime.now().isoformat(),
            "data": value
        }
        self.save_memory()
        return f"Structural insight '{key}' committed to long-term memory."

    def get_all_structural_insights(self):
        return json.dumps(self.data["structural_insights"], indent=2)

    def get_recent_history_string(self):
        if not self.data["history"]:
            return "No recent market history available."
        return json.dumps(self.data["history"], indent=2)

# ================================================================================================
# CORE AGENT ENGINE
# ================================================================================================

OKX_REST_HOST = "https://us.okx.com"

class QuantAgentTrinity:
    def __init__(self, model_path="C:/ai_models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf", memory_file="agent_memory.json"):
        self.model_path = model_path
        self.model_name = os.path.basename(model_path)
        self.memory = AgentMemory(memory_file)
        self.tools = {}
        
        # Initialize local GGUF model via llama-cpp-python
        print(f"[*] Loading Trinity's Core GGUF: {model_path}")
        try:
            self.llm = Llama(
                model_path=self.model_path,
                n_ctx=4096,  # Expanded to 4096 to prevent "token overflow" on complex reports
                n_gpu_layers=0,
                n_threads=4,
                verbose=False
            )
        except Exception as e:
            logger.error(f"Failed to load GGUF model: {e}", exc_info=True)
            raise

        # Base system prompt
        self.system_instructions = (
            "You are Quant Agent Trinity, a high-fidelity analytical extension of the OXX Terminal. "
            "Your identity is rooted in technical precision and objective market analysis.\n\n"
            "OPERATIONAL PROTOCOL:\n"
            "1. Perception Phase: Use multiple tools from the catalog to gather all required data for a comprehensive answer.\n"
            "2. Generate valid JSON objects for each tool invocation. You may output multiple separate JSON blocks.\n"
            "3. Maintain strict technical nomenclature. Utilize precise quantitative terminology.\n"
            "4. Omit reasoning or conversational filler during the perception phase.\n\n"
            "JSON SCHEMA:\n"
            "{\n  \"tool_name\": \"exact_identifier\",\n  \"arguments\": {\"key\": \"value\"}\n}\n"
        )

    def register_tool(self, name, func, description):
        """Register a Python function as an executable tool for the agent."""
        self.tools[name] = {
            "function": func,
            "description": description
        }

    def get_tool_catalog(self):
        """Returns a string representation of all available tools for the prompt."""
        catalog = "AVAILABLE TOOLS CATALOG:\n"
        for name, info in self.tools.items():
            catalog += f"- {name}: {info['description']}\n"
        return catalog

    def run_step(self, user_input):
        """Single turn perception -> reasoning -> action loop with memory recall."""
        
        # Limit history injection to last 5 entries to save context space
        recent_history = json.dumps(self.memory.data["history"][-5:], indent=2)
        structural_insights = self.memory.get_all_structural_insights()
        tool_catalog = self.get_tool_catalog()
        
        dynamic_system_prompt = (
            f"{self.system_instructions}\n\n"
            f"--- LONG-TERM STRUCTURAL INSIGHTS ---\n{structural_insights}\n\n"
            f"--- RECENT MARKET HISTORY (Last 5) ---\n{recent_history}\n\n"
            f"--- TOOL CATALOG ---\n{tool_catalog}"
        )

        conversation = [
            {"role": "system", "content": dynamic_system_prompt},
            {"role": "user", "content": user_input}
        ]

        # 1. Perception & Action phase
        print(f"[*] Trinity is processing perception (Model: {self.model_name})...")
        response = self.llm_call(conversation)
        
        # 2. Execution phase
        tool_output = self.execute_tool_call(response)

        # 3. Observation & Analysis phase
        if tool_output and "Error" not in tool_output and "No tool calls detected" not in tool_output:
            self.auto_commit_memory(tool_output)

            # Technical analysis prompt
            analysis_prompt = (
                f"Retrieved Market Data:\n{tool_output}\n\n"
                "OBJECTIVE: Conduct a professional quantitative analysis. Provide your final response in plain English. "
                "CRITICAL: Do NOT use braces {}, JSON syntax, or markdown code blocks in your response. "
                "Explicitly detail the Verdict, the 1H Macro Filter alignment, and the Confluence Score. "
                "Identify trend variances relative to RECENT MARKET HISTORY using objective technical descriptions."
            )

            conversation.append({"role": "assistant", "content": response})
            conversation.append({"role": "user", "content": analysis_prompt})

            print("[*] Trinity is generating technical analysis...")
            final_response = self.llm_call(conversation)
            return final_response
        
        return response

    def execute_tool_call(self, response_text):
        """Parse agent output and execute registered tools. Supports multiple JSON blocks."""
        results = []
        try:
            import re
            json_blocks = []
            stack = 0
            start = -1
            for i, char in enumerate(response_text):
                if char == '{':
                    if stack == 0: start = i
                    stack += 1
                elif char == '}':
                    stack -= 1
                    if stack == 0 and start != -1:
                        json_blocks.append(response_text[start:i+1])
            
            if not json_blocks:
                json_blocks = re.findall(r'\{.*?\}', response_text, re.DOTALL)

            if not json_blocks:
                return "No tool calls detected; treating as plain text."

            for block in json_blocks:
                try:
                    cleaned_block = block.strip()
                    cleaned_block = re.sub(r',\s*\}', '}', cleaned_block)
                    cleaned_block = re.sub(r',\s*\]', ']', cleaned_block)
                    
                    data = json.loads(cleaned_block)
                    req_name = data.get("tool_name")
                    args = data.get("arguments", {})

                    available_names = list(self.tools.keys())
                    matches = difflib.get_close_matches(req_name, available_names, n=1, cutoff=0.6)
                    
                    if matches:
                        matched_name = matches[0]
                        # Robust Argument Mapping
                        if "inst_id" not in args:
                            for alt in ["instrument", "symbol", "instId", "pair"]:
                                if alt in args:
                                    args["inst_id"] = args.pop(alt)
                                    break
                        
                        print(f"[*] Executing Tool: {matched_name}")
                        output = self.tools[matched_name]["function"](**args)
                        results.append(f"TOOL: {matched_name}\nOUTPUT:\n{output}")
                    else:
                        results.append(f"Error: Tool identifier '{req_name}' not found.")
                except Exception as e:
                    results.append(f"Error executing block: {str(e)}")

            return "\n\n".join(results)
        except Exception as e:
            return f"Critical Parser Error: {str(e)}"

    def auto_commit_memory(self, tool_output):
        """Distills tool output into the memory engine."""
        blocks = tool_output.split("TOOL: ")
        for block in blocks:
            if not block.strip(): continue
            try:
                if "OUTPUT:\n{" in block:
                    json_str = "{" + block.split("OUTPUT:\n{")[1]
                    data = json.loads(json_str)
                    inst = data.get("instrument", "Unknown")
                    last_price = float(data.get("last_price", 0))
                    high = float(data.get("high_24h", 0))
                    low = float(data.get("low_24h", 0))
                    
                    if inst != "Unknown":
                        state = f"Market State Delta: {last_price}" if last_price > 0 else "Analysis Delta"
                        self.memory.save_market_memory(inst, state, low, high)
                        logger.info(f"State Committed: {inst}")
            except:
                continue

    def llm_call(self, messages):
        """Route to local GGUF model."""
        try:
            response = self.llm.create_chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=1024
            )
            return response['choices'][0]['message']['content']
        except Exception as e:
            return f"Inference Error: {str(e)}"

# ================================================================================================
# LIVE TOOLS
# ================================================================================================

def fetch_okx_ticker(inst_id: str = "BTC-USDT", **kwargs):
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/ticker"
        params = {"instId": inst_id}
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json().get("data", [])
            if data:
                t = data[0]
                return json.dumps({
                    "instrument": inst_id,
                    "last_price": t.get("last"),
                    "high_24h": t.get("high24h"),
                    "low_24h": t.get("low24h"),
                    "volume_24h": t.get("vol24h"),
                    "timestamp": t.get("ts")
                }, indent=2)
        return f"Error: Failed to fetch ticker for {inst_id}"
    except Exception as e:
        return f"API Exception: {str(e)}"

def fetch_okx_candles(inst_id: str = "BTC-USDT", bar: str = "1H", limit: int = 10, **kwargs):
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/candles"
        params = {"instId": inst_id, "bar": bar, "limit": limit}
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("code") == "0":
                return json.dumps(res_json.get("data", []), indent=2)
        return f"Error: Failed to fetch candles for {inst_id}"
    except Exception as e:
        return f"API Exception: {str(e)}"

def read_trade_ledger(**kwargs):
    ledger_path = "trade_signals_ledger.md"
    if not os.path.exists(ledger_path):
        return "Ledger file not found yet."
    with open(ledger_path, "r", encoding="utf-8") as f:
        content = f.readlines()
    return "".join(content[-15:])

def fetch_rpi_index(inst_id: str = "BTC-USDT", **kwargs):
    ticker_json = fetch_okx_ticker(inst_id)
    if "Error" in ticker_json: return ticker_json
    try:
        data = json.loads(ticker_json)
        last, high, low = float(data["last_price"]), float(data["high_24h"]), float(data["low_24h"])
        rpi = ((last - low) / (high - low)) * 100 if (high - low) > 0 else 50
        data["rpi_index"] = round(rpi, 2)
        if rpi <= 30: data["rpi_classification"] = "Lower-Range Compression"
        elif rpi >= 70: data["rpi_classification"] = "Upper-Range Expansion"
        else: data["rpi_classification"] = "Mid-Range Equilibrium"
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

def fetch_technical_indicators(inst_id: str = "BTC-USDT", bar: str = "1H", **kwargs):
    candles_json = fetch_okx_candles(inst_id, bar, limit=50)
    if "Error" in candles_json: return candles_json
    try:
        candles = json.loads(candles_json)
        closes = [float(c[4]) for c in candles][::-1]
        if len(closes) < 21: return "Error: Not enough data."
        def get_ema(data, period):
            ema = [sum(data[:period]) / period]
            mult = 2 / (period + 1)
            for p in data[period:]: ema.append((p - ema[-1]) * mult + ema[-1])
            return ema[-1]
        def get_rsi(data, period=14):
            gains = [max(data[i] - data[i-1], 0) for i in range(1, len(data))]
            losses = [max(data[i-1] - data[i], 0) for i in range(1, len(data))]
            avg_g, avg_l = sum(gains[:period])/period, sum(losses[:period])/period
            for i in range(period, len(gains)):
                avg_g, avg_l = (avg_g * (period-1) + gains[i])/period, (avg_l * (period-1) + losses[i])/period
            if avg_l == 0: return 100
            return 100 - (100 / (1 + (avg_g / avg_l)))
        ema9, ema21, rsi14 = get_ema(closes, 9), get_ema(closes, 21), get_rsi(closes, 14)
        return json.dumps({"instrument": inst_id, "ema_9": round(ema9, 2), "ema_21": round(ema21, 2), "rsi_14": round(rsi14, 2), "trend": "Bullish" if ema9 > ema21 else "Bearish"}, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

def fetch_order_book_walls(inst_id: str = "BTC-USDT", **kwargs):
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/books"
        params = {"instId": inst_id, "sz": 20}
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data_list = response.json().get("data", [])
            if not data_list: return "Error: No data."
            data = data_list[0]
            bids, asks = data.get("bids", []), data.get("asks", [])
            if not bids or not asks: return "Error: Empty book."
            top_bid = max(bids, key=lambda x: float(x[1]))
            top_ask = max(asks, key=lambda x: float(x[1]))
            return json.dumps({"instrument": inst_id, "buy_wall": {"price": top_bid[0], "size": top_bid[1]}, "sell_wall": {"price": top_ask[0], "size": top_ask[1]}}, indent=2)
        return "Error: Failed to fetch."
    except Exception as e:
        return f"Error: {str(e)}"

def fetch_quantitative_setup(inst_id: str = "BTC-USDT", **kwargs):
    try:
        macro_json = fetch_okx_candles(inst_id, bar="1H", limit=250)
        if "Error" in macro_json: return macro_json
        macro_closes = [float(c[4]) for c in json.loads(macro_json)[::-1]]
        def get_ema(data, period):
            ema = [sum(data[:period]) / period]
            mult = 2 / (period + 1)
            for p in data[period:]: ema.append((p - ema[-1]) * mult + ema[-1])
            return ema[-1]
        macro_ema50, macro_ema200 = get_ema(macro_closes, 50), get_ema(macro_closes, 200)
        macro_bullish = (macro_closes[-1] > macro_ema200) and (macro_ema50 > macro_ema200)
        tact_json = fetch_okx_candles(inst_id, bar="15m", limit=250)
        if "Error" in tact_json: return tact_json
        tact_candles = json.loads(tact_json)[::-1]
        c, v, h, l = [float(x[4]) for x in tact_candles], [float(x[5]) for x in tact_candles], [float(x[2]) for x in tact_candles], [float(x[3]) for x in tact_candles]
        ema50, ema200 = get_ema(c, 50), get_ema(c, 200)
        gate_trend = (c[-1] > ema200) and (ema50 > ema200)
        def get_macd_hist(data):
            ema12 = [sum(data[:12])/12]
            for x in data[12:]: ema12.append((x - ema12[-1]) * (2/13) + ema12[-1])
            ema26 = [sum(data[:26])/26]
            for x in data[26:]: ema26.append((x - ema26[-1]) * (2/27) + ema26[-1])
            macd_line = [e12 - e26 for e12, e26 in zip(ema12[26-12:], ema26)]
            signal_line = [sum(macd_line[:9])/9]
            for x in macd_line[9:]: signal_line.append((x - signal_line[-1]) * (2/10) + signal_line[-1])
            return [m - s for m, s in zip(macd_line[9-1:], signal_line)]
        hist = get_macd_hist(c)
        gate_momentum = (hist[-1] > 0) and (hist[-1] > hist[-2]) and (hist[-2] > hist[-3])
        vol_ma20 = sum(v[-20:]) / 20
        gate_volume = v[-1] > (vol_ma20 * 1.4)
        bar_range = h[-1] - l[-1]
        strength = (c[-1] - l[-1]) / bar_range if bar_range > 0 else 0
        gate_strength = strength >= 0.60
        tactical_score = sum([gate_trend, gate_momentum, gate_volume, gate_strength])
        return json.dumps({"instrument": inst_id, "last_price": c[-1], "macro_filter_bullish": macro_bullish, "tactical_confluence_score": f"{tactical_score}/4", "gates": {"structural_trend": "Bullish" if gate_trend else "Neutral/Bearish", "momentum_acceleration": "Active" if gate_momentum else "Decelerating", "volume_surge": "Confirmed" if gate_volume else "Nominal", "price_location": f"{round(strength*100, 1)}% of range"}, "verdict": "CONFLUENCE_LEVEL_4" if macro_bullish and tactical_score == 4 else "CONFLUENCE_LEVEL_3" if tactical_score >= 3 else "MONITORING"}, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

def fetch_market_sentiment(inst_id: str = "BTC-USDT", **kwargs):
    sentiment_data = {"instrument": inst_id}
    global_host = "https://www.okx.com"
    asset = inst_id.split("-")[0]
    swap_candidates = [f"{asset}-USDT-SWAP", f"{asset}-USDC-SWAP"]
    for swap_inst in swap_candidates:
        try:
            f_url = f"{global_host}/api/v5/public/funding-rate"
            f_resp = requests.get(f_url, params={"instId": swap_inst}, timeout=5).json()
            if f_resp.get("code") == "0" and f_resp.get("data"):
                sentiment_data["active_swap_instrument"] = swap_inst
                sentiment_data["funding_rate"] = f_resp["data"][0].get("fundingRate")
                oi_url = f"{global_host}/api/v5/public/open-interest"
                oi_resp = requests.get(oi_url, params={"instId": swap_inst}, timeout=5).json()
                if oi_resp.get("code") == "0" and oi_resp.get("data"):
                    sentiment_data["open_interest"] = oi_resp["data"][0].get("oi")
                    sentiment_data["oi_ccy"] = oi_resp["data"][0].get("oiCcy")
                liq_url = f"{global_host}/api/v5/public/liquidation-info"
                liq_resp = requests.get(liq_url, params={"instId": swap_inst, "mgnMode": "cross", "limit": 20}, timeout=5).json()
                if liq_resp.get("code") == "0" and liq_resp.get("data"):
                    total_liq = sum(float(x.get("sz", 0)) for x in liq_resp["data"])
                    sentiment_data["recent_liquidations_sz"] = round(total_liq, 2)
                if sentiment_data.get("funding_rate"): break
        except Exception as e:
            logger.warning(f"Sentiment failed for {swap_inst}: {e}")
            continue
    return json.dumps(sentiment_data, indent=2)

def fetch_global_market_status(**kwargs):
    watchlist = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "OKB-USDT", "USDC-USDT"]
    results = {}
    try:
        for inst in watchlist:
            ticker_json = fetch_okx_ticker(inst)
            data = json.loads(ticker_json)
            results[inst] = {"price": float(data.get("last_price", 0)), "24h_high": data.get("high_24h"), "24h_low": data.get("low_24h")}
        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

def fetch_volatility_metrics(inst_id: str = "BTC-USDT", **kwargs):
    try:
        candles_json = fetch_okx_candles(inst_id, bar="1H", limit=30)
        candles = json.loads(candles_json)
        true_ranges = []
        for i in range(1, len(candles)):
            h, l, prev_c = float(candles[i][2]), float(candles[i][3]), float(candles[i-1][4])
            true_ranges.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
        atr = sum(true_ranges[-14:]) / 14 if len(true_ranges) >= 14 else 0
        return json.dumps({"instrument": inst_id, "hourly_atr": round(atr, 2), "volatility_ratio": round(atr / float(candles[-1][4]) * 100, 4) if candles else 0}, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

def record_structural_insight(key: str, value: str, **kwargs):
    global agent
    try: return agent.memory.save_structural_insight(key, value)
    except Exception as e: return f"Error: {str(e)}"

def fetch_historical_lookback(inst_id: str = "BTC-USDT", days: int = 7, **kwargs):
    try:
        if "lookback_days" in kwargs: days = int(kwargs["lookback_days"])
        limit = days * 24
        candles_json = fetch_okx_candles(inst_id, bar="1H", limit=limit)
        candles = json.loads(candles_json)
        closes, vols = [float(x[4]) for x in candles], [float(x[5]) for x in candles]
        avg_vol, max_px, min_px = sum(vols) / len(vols), max(closes), min(closes)
        delta_pct = ((closes[-1] - closes[0]) / closes[0]) * 100
        return json.dumps({"instrument": inst_id, "lookback_period_days": days, "high": max_px, "low": min_px, "avg_hourly_volume": round(avg_vol, 2), "period_performance": f"{delta_pct:+.2f}%"}, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

async def run_autonomous_loop(agent_instance):
    """
    Continuous monitoring loop for Quant Agent Trinity.
    Executes analytical cycle every 15 minutes (aligned with tactical candle closes).
    """
    logger.info("Autonomous Monitoring Active. Trinity is operational.")
    while True:
        try:
            # Enhanced objective prompt for autonomous reporting and level tracking
            prompt = (
                "Execute autonomous analytical cycle for BTC-USDT. "
                "1. Assess macro filter alignment, tactical confluence, and institutional sentiment. "
                "2. Identify major structural levels (Support/Resistance) using fetch_historical_lookback. "
                "3. If a new significant structural level is identified, use record_structural_insight to save it. "
                "4. Cross-reference RECENT MARKET HISTORY for trend deltas."
            )
            
            print(f"\n[!] TRINITY AUTONOMOUS CYCLE: {datetime.now().strftime('%H:%M:%S')}")
            reply = agent_instance.run_step(prompt)
            print(f"\n[Autonomous Report]:\n{reply}\n")
            print("-" * 80)
            await asyncio.sleep(900)
        except Exception as e:
            logger.error(f"Loop error: {e}", exc_info=True)
            await asyncio.sleep(60)

if __name__ == "__main__":
    print("[*] Initializing Quant Agent Trinity (GGUF Mode)...")
    gguf_path = "C:/ai_models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf"
    try:
        agent = QuantAgentTrinity(model_path=gguf_path)
        agent.register_tool("fetch_okx_ticker", fetch_okx_ticker, "Retrieves real-time instrument telemetry.")
        agent.register_tool("fetch_okx_candles", fetch_okx_candles, "Retrieves historical OHLCV data.")
        agent.register_tool("fetch_rpi_index", fetch_rpi_index, "Calculates RPI for relative price location analysis.")
        agent.register_tool("fetch_technical_indicators", fetch_technical_indicators, "Calculates EMA and RSI metrics.")
        agent.register_tool("fetch_order_book_walls", fetch_order_book_walls, "Identifies institutional liquidity blocks.")
        agent.register_tool("check_quantitative_confluence", fetch_quantitative_setup, "Evaluates macro trend and tactical confluence.")
        agent.register_tool("fetch_market_sentiment", fetch_market_sentiment, "Retrieves institutional leverage and flow metrics.")
        agent.register_tool("fetch_global_market_status", fetch_global_market_status, "Scans major assets for market-wide context.")
        agent.register_tool("fetch_volatility_metrics", fetch_volatility_metrics, "Calculates ATR and volatility ratios.")
        agent.register_tool("record_structural_insight", record_structural_insight, "Records a permanent technical observation.")
        agent.register_tool("fetch_historical_lookback", fetch_historical_lookback, "Performs a multi-day statistical lookback.")
        asyncio.run(run_autonomous_loop(agent))
    except (KeyboardInterrupt, SystemExit):
        print("\n[*] Trinity successfully deactivated by user.")
    except Exception as e:
        print(f"[!] Critical Launch Failure: {e}")
        sys.exit(1)
