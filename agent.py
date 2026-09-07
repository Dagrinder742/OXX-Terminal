import json
import os
import requests
import difflib
from ollama import chat
from datetime import datetime

# ================================================================================================
# MEMORY ENGINE (Integrated from memory.py)
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
                    if "notes" not in content: content["notes"] = {}
                    if "history" not in content: content["history"] = []
                    return content
            except (json.JSONDecodeError, KeyError):
                pass
        return {"notes": {}, "history": []}

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
        self.data["history"] = self.data["history"][-10:]  # Keep last 10
        self.save_memory()
        return f"Successfully committed memory state for {inst_id} to disk."

    def get_recent_history_string(self):
        if not self.data["history"]:
            return "No recent market history available."
        return json.dumps(self.data["history"], indent=2)

# ================================================================================================
# CORE AGENT ENGINE
# ================================================================================================

OKX_REST_HOST = "https://us.okx.com"

class ScratchAgent:
    def __init__(self, model_name="phi4-mini", memory_file="agent_memory.json"):
        self.model_name = model_name
        self.memory = AgentMemory(memory_file)
        self.tools = {}
        
        # Base system prompt
        self.system_instructions = (
            "You are the OXX Quant Agent. Your goal is to analyze OKX market data and provide structural insights.\n\n"
            "STEP 1: Check the 'RECENT MEMORY' below for historical context.\n"
            "STEP 2: Use the 'TOOL CATALOG' to fetch fresh market data via JSON.\n"
            "STEP 3: Once you receive 'OBSERVATION DATA', provide a deep analysis.\n\n"
            "JSON TOOL SCHEMA:\n"
            "{\n  \"tool_name\": \"name\",\n  \"arguments\": {\"key\": \"value\"}\n}\n"
            "Do not talk or explain your reasoning until AFTER you have the observation data."
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
        
        # Build the dynamic prompt with Memory and Tools
        recent_memory = self.memory.get_recent_history_string()
        tool_catalog = self.get_tool_catalog()
        
        dynamic_system_prompt = (
            f"{self.system_instructions}\n\n"
            f"--- RECENT MEMORY ---\n{recent_memory}\n\n"
            f"--- TOOL CATALOG ---\n{tool_catalog}"
        )

        conversation = [
            {"role": "system", "content": dynamic_system_prompt},
            {"role": "user", "content": user_input}
        ]

        # 1. Thought & Action phase
        print(f"[*] Agent Trinity is thinking (Model: {self.model_name})...")
        response = self.llm_call(conversation)
        
        # 2. Execution phase
        tool_output = self.execute_tool_call(response)

        # 3. Observation & Analysis phase
        if tool_output and "Error" not in tool_output and "not valid JSON" not in tool_output:
            # Auto-commit to memory before final analysis
            self.auto_commit_memory(tool_output)

            # Refined analysis prompt to encourage depth
            analysis_prompt = (
                f"You have successfully fetched this market data:\n{tool_output}\n\n"
                "TASK: Provide a professional quantitative analysis. Speak in plain English now. "
                "Highlight the Verdict, the 1H Boss status, and the tactical score. "
                "Compare this price to the RECENT MEMORY to identify the trend."
            )

            conversation.append({"role": "assistant", "content": response})
            conversation.append({"role": "user", "content": analysis_prompt})

            print("[*] Agent Trinity is analyzing results (Transitioning to Plain Text)...")
            final_response = self.llm_call(conversation)
            return final_response
        
        # If it wasn't a tool call, or tool failed, return the raw response
        return response

    def execute_tool_call(self, response_text):
        """Parse agent output and execute registered tools. Supports multiple JSON blocks."""
        results = []
        try:
            # 1. Extraction: Look for anything between { and }
            import re
            json_blocks = re.findall(r'\{.*?\}', response_text, re.DOTALL)
            
            if not json_blocks:
                # Fallback for plain text "tool_name: name" format if JSON fails
                lines = response_text.split("\n")
                tool_name = None
                args = {}
                for line in lines:
                    if "tool_name:" in line:
                        tool_name = line.split("tool_name:")[1].strip()
                    if "arguments:" in line:
                        try:
                            arg_str = line.split("arguments:")[1].strip()
                            args = json.loads(arg_str) if arg_str != "{}" else {}
                        except: pass
                if tool_name:
                    json_blocks = [json.dumps({"tool_name": tool_name, "arguments": args})]

            if not json_blocks:
                return "No tool calls detected; treating as plain text."

            for block in json_blocks:
                try:
                    data = json.loads(block)
                    req_name = data.get("tool_name")
                    args = data.get("arguments", {})

                    # Fuzzy matching
                    available_names = list(self.tools.keys())
                    matches = difflib.get_close_matches(req_name, available_names, n=1, cutoff=0.6)
                    
                    if matches:
                        matched_name = matches[0]
                        # Argument Normalization
                        if "inst_id" not in args:
                            for alt in ["instrument", "symbol", "instId", "pair"]:
                                if alt in args:
                                    args["inst_id"] = args.pop(alt)
                                    break
                        
                        print(f"[*] Executing: {matched_name}")
                        output = self.tools[matched_name]["function"](**args)
                        results.append(f"TOOL: {matched_name}\nOUTPUT:\n{output}")
                    else:
                        results.append(f"Error: Tool '{req_name}' not found.")
                except Exception as e:
                    results.append(f"Error parsing/executing block: {str(e)}")

            return "\n\n".join(results)
                
        except Exception as e:
            return f"Critical Parser Error: {str(e)}"

    def auto_commit_memory(self, tool_output):
        """Distills tool output into the memory engine. Handles multi-tool strings."""
        blocks = tool_output.split("TOOL: ")
        for block in blocks:
            if not block.strip(): continue
            try:
                # Find the JSON section
                if "OUTPUT:\n{" in block:
                    json_str = "{" + block.split("OUTPUT:\n{")[1]
                    data = json.loads(json_str)
                    
                    # Handle dict output (ticker/sentiment)
                    inst = data.get("instrument", "Unknown")
                    last_price = float(data.get("last_price", 0))
                    high = float(data.get("high_24h", 0))
                    low = float(data.get("low_24h", 0))
                    
                    if inst != "Unknown":
                        state = f"Market Ticker: {last_price}" if last_price > 0 else "Analysis Observation"
                        self.memory.save_market_memory(inst, state, low, high)
                        print(f"[*] Memory committed for {inst}.")
            except:
                continue

    def llm_call(self, messages):
        """Route the conversation history to local Ollama inference."""
        try:
            response = chat(
                model=self.model_name,
                messages=messages
            )
            return response['message']['content']
        except Exception as e:
            return f"Inference Error: {str(e)}"

# ================================================================================================
# LIVE TOOLS
# ================================================================================================

def fetch_okx_ticker(inst_id: str = "BTC-USDT"):
    """Fetches real-time ticker data directly from OKX V5 REST API."""
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

def fetch_okx_candles(inst_id: str = "BTC-USDT", bar: str = "1H", limit: int = 10):
    """Fetches recent OHLCV candlestick data directly from OKX V5 REST API."""
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

def read_trade_ledger(lines: int = 15):
    """Reads the latest entries from the trade signals ledger markdown file."""
    ledger_path = "trade_signals_ledger.md"
    if not os.path.exists(ledger_path):
        return "Ledger file not found yet."
    with open(ledger_path, "r", encoding="utf-8") as f:
        content = f.readlines()
    return "".join(content[-lines:])

def fetch_rpi_index(inst_id: str = "BTC-USDT"):
    """Calculates the Daily Range Position Index (RPI) for an instrument."""
    ticker_json = fetch_okx_ticker(inst_id)
    if "Error" in ticker_json:
        return ticker_json
    try:
        data = json.loads(ticker_json)
        last = float(data["last_price"])
        high = float(data["high_24h"])
        low = float(data["low_24h"])
        rpi = ((last - low) / (high - low)) * 100 if (high - low) > 0 else 50
        data["rpi_index"] = round(rpi, 2)
        data["sentiment"] = "Star Blue (Dip)" if rpi < 30 else "Star Red (Chase)" if rpi > 70 else "Neutral"
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error calculating RPI: {str(e)}"

def fetch_technical_indicators(inst_id: str = "BTC-USDT", bar: str = "1H"):
    """Calculates EMA-9, EMA-21, and RSI-14 from recent candles."""
    candles_json = fetch_okx_candles(inst_id, bar, limit=50)
    if "Error" in candles_json:
        return candles_json
    try:
        candles = json.loads(candles_json)
        closes = [float(c[4]) for c in candles][::-1]
        if len(closes) < 21:
            return "Error: Not enough data for indicators."

        def calculate_ema(data, period):
            ema = [sum(data[:period]) / period]
            multiplier = 2 / (period + 1)
            for price in data[period:]:
                ema.append((price - ema[-1]) * multiplier + ema[-1])
            return ema[-1]

        def calculate_rsi(data, period=14):
            gains = [max(data[i] - data[i-1], 0) for i in range(1, len(data))]
            losses = [max(data[i-1] - data[i], 0) for i in range(1, len(data))]
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            for i in range(period, len(gains)):
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0: return 100
            return 100 - (100 / (1 + (avg_gain / avg_loss)))

        ema9 = calculate_ema(closes, 9)
        ema21 = calculate_ema(closes, 21)
        rsi14 = calculate_rsi(closes, 14)
        return json.dumps({
            "instrument": inst_id,
            "ema_9": round(ema9, 2),
            "ema_21": round(ema21, 2),
            "rsi_14": round(rsi14, 2),
            "trend": "Bullish" if ema9 > ema21 else "Bearish"
        }, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

def fetch_order_book_walls(inst_id: str = "BTC-USDT"):
    """Identifies large liquidity walls in the order book."""
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/books"
        params = {"instId": inst_id, "sz": 20}
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json().get("data", [])[0]
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            top_bid = max(bids, key=lambda x: float(x[1]))
            top_ask = max(asks, key=lambda x: float(x[1]))
            return json.dumps({
                "instrument": inst_id,
                "buy_wall": {"price": top_bid[0], "size": top_bid[1]},
                "sell_wall": {"price": top_ask[0], "size": top_ask[1]}
            }, indent=2)
        return "Error: Failed to fetch book."
    except Exception as e:
        return f"Error: {str(e)}"

def fetch_quantitative_setup(inst_id: str = "BTC-USDT", **kwargs):
    """
    Implements the 'Hierarchical Analytics Engine' logic.
    Accepts **kwargs to prevent crashes from hallucinated arguments.
    """
    try:
        # 1. Macro Check (1H)
        macro_json = fetch_okx_candles(inst_id, bar="1H", limit=250)
        if "Error" in macro_json: return macro_json
        macro_candles = json.loads(macro_json)[::-1]
        macro_closes = [float(c[4]) for c in macro_candles]

        def get_ema(data, period):
            ema = [sum(data[:period]) / period]
            mult = 2 / (period + 1)
            for p in data[period:]:
                ema.append((p - ema[-1]) * mult + ema[-1])
            return ema[-1]

        macro_ema50 = get_ema(macro_closes, 50)
        macro_ema200 = get_ema(macro_closes, 200)
        macro_bullish = (macro_closes[-1] > macro_ema200) and (macro_ema50 > macro_ema200)

        # 2. Tactical Check (15m)
        tact_json = fetch_okx_candles(inst_id, bar="15m", limit=250)
        if "Error" in tact_json: return tact_json
        tact_candles = json.loads(tact_json)[::-1]
        
        c = [float(x[4]) for x in tact_candles] # Closes
        v = [float(x[5]) for x in tact_candles] # Volumes
        h = [float(x[2]) for x in tact_candles] # Highs
        l = [float(x[3]) for x in tact_candles] # Lows

        # EMA Gates
        ema50 = get_ema(c, 50)
        ema200 = get_ema(c, 200)
        gate_trend = (c[-1] > ema200) and (ema50 > ema200)

        # MACD Gates (12, 26, 9)
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

        # Volume Surge Gate (1.4x MA20)
        vol_ma20 = sum(v[-20:]) / 20
        gate_volume = v[-1] > (vol_ma20 * 1.4)

        # Bar Strength Gate
        bar_range = h[-1] - l[-1]
        strength = (c[-1] - l[-1]) / bar_range if bar_range > 0 else 0
        gate_strength = strength >= 0.60

        tactical_score = sum([gate_trend, gate_momentum, gate_volume, gate_strength])

        return json.dumps({
            "instrument": inst_id,
            "last_price": c[-1],
            "macro_boss_bullish": macro_bullish,
            "tactical_score": f"{tactical_score}/4",
            "gates": {
                "trend": "Bullish" if gate_trend else "Neutral/Bearish",
                "momentum": "Accelerating" if gate_momentum else "Decelerating/Negative",
                "volume": "Surge" if gate_volume else "Normal",
                "strength": f"{round(strength*100, 1)}% of range"
            },
            "verdict": "ELITE SETUP" if macro_bullish and tactical_score == 4 else "STRONG CONFLUENCE" if tactical_score >= 3 else "MONITORING"
        }, indent=2)
    except Exception as e:
        return f"Error in Quantitative Engine: {str(e)}"

def fetch_market_sentiment(inst_id: str = "BTC-USDT", **kwargs):
    """
    Fetches institutional sentiment metrics:
    1. Funding Rate (Leverage Bias)
    2. Open Interest (Money Flow)
    3. 24h Liquidations (Pain Points)
    Note: Hits global endpoints for sentiment context as US is Spot-only.
    """
    sentiment_data = {"instrument": inst_id}
    global_host = "https://www.okx.com"
    # Map BTC-USDT to BTC-USDC-SWAP for derivatives sentiment
    swap_inst = inst_id.split("-")[0] + "-USDC-SWAP"

    try:
        # 1. Funding Rate
        f_url = f"{global_host}/api/v5/public/funding-rate"
        f_resp = requests.get(f_url, params={"instId": swap_inst}, timeout=5).json()
        if f_resp.get("code") == "0" and f_resp.get("data"):
            sentiment_data["funding_rate"] = f_resp["data"][0].get("fundingRate")
            sentiment_data["next_funding_time"] = f_resp["data"][0].get("fundingTime")

        # 2. Open Interest
        oi_url = f"{global_host}/api/v5/public/open-interest"
        oi_resp = requests.get(oi_url, params={"instId": swap_inst}, timeout=5).json()
        if oi_resp.get("code") == "0" and oi_resp.get("data"):
            sentiment_data["open_interest"] = oi_resp["data"][0].get("oi")
            sentiment_data["oi_ccy"] = oi_resp["data"][0].get("oiCcy")

        # 3. Liquidations (24h snapshot approximation)
        liq_url = f"{global_host}/api/v5/public/liquidation-info"
        liq_params = {"instId": swap_inst, "mgnMode": "cross", "limit": 20}
        liq_resp = requests.get(liq_url, params=liq_params, timeout=5).json()
        if liq_resp.get("code") == "0" and liq_resp.get("data"):
            total_liq = sum(float(x.get("sz", 0)) for x in liq_resp["data"])
            sentiment_data["recent_liquidations_sz"] = round(total_liq, 2)
            
        return json.dumps(sentiment_data, indent=2)
    except Exception as e:
        return f"Error fetching sentiment: {str(e)}"

# ================================================================================================
# MAIN EXECUTION
# ================================================================================================

if __name__ == "__main__":
    print("[*] Initializing OXX Quant Agent Trinity(phi4-mini)...")

    agent = ScratchAgent()

    # Register live tools
    agent.register_tool("fetch_okx_ticker", fetch_okx_ticker, "Fetches real-time ticker stats.")
    agent.register_tool("fetch_okx_candles", fetch_okx_candles, "Fetches recent OHLCV candles.")
    agent.register_tool("fetch_rpi_index", fetch_rpi_index, "Calculates RPI sentiment (Dip/Chase).")
    agent.register_tool("fetch_technical_indicators", fetch_technical_indicators, "Calculates EMA and RSI.")
    agent.register_tool("fetch_order_book_walls", fetch_order_book_walls, "Identifies liquidity walls.")
    agent.register_tool("check_quantitative_confluence", fetch_quantitative_setup, "Runs the full Hierarchical Analytics Engine (1H Boss + 15m Tactical Gates).")
    agent.register_tool("fetch_market_sentiment", fetch_market_sentiment, "Fetches institutional metrics: Funding Rate, Open Interest, and Liquidations.")

    # Test run
    prompt = "Perform a deep-dive analysis on BTC-USDT. I need the quantitative confluence score AND the institutional market sentiment (funding/OI) to see if we are over-leveraged."
    print(f"\n[*] User Request: {prompt}\n")

    reply = agent.run_step(prompt)
    print(f"\n[Agent Final Analysis]:\n{reply}")
