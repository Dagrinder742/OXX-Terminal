import json
import os
import sys
import logging
import requests
import difflib
import asyncio
import re
import urllib.request
import xml.etree.ElementTree as ET
from llama_cpp import Llama
from datetime import datetime

# Configure professional logging standard
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("QuantAgentTrinity")

# ================================================================================================
# MEMORY ENGINE
# ================================================================================================

class AgentMemory:
    """Handles persistent JSON storage for historical telemetry and structural insights."""
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
        self.data["history"] = self.data["history"][-20:]  # Last 20 entries
        self.save_memory()
        return f"State committed for {inst_id}."

    def save_structural_insight(self, key: str, value: str):
        """Saves a permanent structural level or macro shift."""
        self.data["structural_insights"][key] = {
            "timestamp": datetime.now().isoformat(),
            "data": value
        }
        self.save_memory()
        return f"Structural insight '{key}' committed."

    def get_all_structural_insights(self):
        return json.dumps(self.data["structural_insights"], indent=2)

    def get_recent_history_string(self):
        if not self.data["history"]:
            return "No recent market history available."
        return json.dumps(self.data["history"][-5:], indent=2) # Last 5 for prompt context

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

        logger.info(f"Loading GGUF Engine: {self.model_name}")
        try:
            self.llm = Llama(
                model_path=self.model_path,
                n_ctx=4096,
                n_gpu_layers=0,
                n_threads=4,
                verbose=False
            )
        except Exception as e:
            logger.error(f"GGUF Init Failure: {e}", exc_info=True)
            raise

        self.system_instructions = (
            "You are Quant Agent Trinity, the analytical brain of the OXX Terminal.\n\n"
            "PHILOSOPHY:\n"
            "Identify professional spot trade setups based on technical probabilities. "
            "You MUST account for trading costs (0.2% fee per side, 0.4% total) to ensure setups are 'Trade-Ready'.\n\n"
            "STRATEGY PRESETS:\n"
            "1. MOMENTUM: Confluence >= 3/4, accelerating MACD. Setup MUST target >= 1.5% profit to cover fees and risk.\n"
            "2. BALANCED: Mean reversion from compression (RPI <= 30) near support. Setup MUST target >= 1.5% profit.\n\n"
            "OPERATIONAL PROTOCOL (STRICT TURNS):\n"
            "TURN 1 (PERCEPTION): Call tools (ai_chart_analyzer, etc.). Output ONLY JSON.\n"
            "TURN 2 (ANALYSIS): Generate a NOTIFICATION CARD only if a 'Trade-Ready' setup exists.\n"
            "   --- SETUP NOTIFICATION CARD ---\n"
            "   ASSET: BTC-USDT\n"
            "   STRATEGY: [MOMENTUM/BALANCED]\n"
            "   PROPOSED ENTRY: [Price from Live Data]\n"
            "   STOP LOSS: [Calculated: Price - 0.75%]\n"
            "   PROFIT TARGET: [Calculated: Price + 1.5% minimum]\n"
            "   EXPLANATION: [Technical justification + Fee-Adjusted logic]\n"
            "   --------------------------------\n"
        )

    def register_tool(self, name, func, description):
        self.tools[name] = {"function": func, "description": description}

    def get_tool_catalog(self):
        catalog = "AVAILABLE TOOLS CATALOG:\n"
        for name, info in self.tools.items():
            catalog += f"- {name}: {info['description']}\n"
        return catalog

    def run_step(self, user_input):
        recent_history = self.memory.get_recent_history_string()
        structural_insights = self.memory.get_all_structural_insights()
        tool_catalog = self.get_tool_catalog()
        
        dynamic_system_prompt = (
            f"{self.system_instructions}\n\n"
            f"--- LONG-TERM STRUCTURAL INSIGHTS ---\n{structural_insights}\n\n"
            f"--- RECENT MARKET HISTORY ---\n{recent_history}\n\n"
            f"--- TOOL CATALOG ---\n{tool_catalog}"
        )

        conversation = [
            {"role": "system", "content": dynamic_system_prompt},
            {"role": "user", "content": user_input}
        ]

        print(f"[*] Trinity Processing (Model: {self.model_name})...")
        response = self.llm_call(conversation)
        
        tool_output = self.execute_tool_call(response)

        # 3. Observation & Analysis phase
        if tool_output and "No tool calls detected" not in tool_output:
            self.auto_commit_memory(tool_output)

            analysis_prompt = (
                f"LIVE MARKET OBSERVATION DATA:\n{tool_output}\n\n"
                "OBJECTIVE: Conduct a professional quantitative analysis. "
                "CRITICAL: A trade is only valid if the profit target is at least 1.5% away from entry to cover the 0.4% round-trip fee.\n\n"
                "REPORTING FORMAT:\n"
                "If a Trade-Ready setup exists, generate a NOTIFICATION CARD:\n"
                "   --- SETUP NOTIFICATION CARD ---\n"
                "   ASSET: BTC-USDT\n"
                "   STRATEGY: [MOMENTUM/BALANCED]\n"
                "   PROPOSED ENTRY: [Current Price]\n"
                "   STOP LOSS: [Entry - 0.75% (Min)]\n"
                "   PROFIT TARGET: [Entry + 1.5% (Min)]\n"
                "   EXPLANATION: [Justify why this setup overcomes the 0.4% fee hurdle]\n"
                "   --------------------------------\n"
                "If no setup meets the 1.5% hurdle, provide a MONITORING report explaining that volatility is too low for a fee-efficient trade."
            )

            conversation.append({"role": "assistant", "content": response})
            conversation.append({"role": "user", "content": analysis_prompt})

            print("[*] Generating Technical Analysis...")
            return self.llm_call(conversation)
        
        # ERROR HANDLING: If the model failed to call tools, force a re-prompt
        if "No tool calls detected" in tool_output:
            logger.warning("Agent failed to initiate Perception Phase. Retrying with strict enforcement.")
            retry_prompt = "You failed to call any tools. You MUST use 'ai_chart_analyzer' to see the actual market price before talking."
            conversation.append({"role": "user", "content": retry_prompt})
            return self.llm_call(conversation)
            
        return response

    def execute_tool_call(self, response_text):
        results = []
        try:
            # Stack-based JSON extractor
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
                return "No tool calls detected."

            for block in json_blocks:
                try:
                    cleaned = re.sub(r',\s*\}', '}', block.strip())
                    data = json.loads(cleaned)
                    req_name = data.get("tool_name")
                    args = data.get("arguments", {})

                    available_names = list(self.tools.keys())
                    matches = difflib.get_close_matches(req_name, available_names, n=1, cutoff=0.6)
                    
                    if matches:
                        matched_name = matches[0]
                        # Argument normalization
                        if "inst_id" not in args:
                            for alt in ["instrument", "symbol", "instId", "pair"]:
                                if alt in args: args["inst_id"] = args.pop(alt); break
                        
                        print(f"[*] Executing Tool: {matched_name}")
                        output = self.tools[matched_name]["function"](**args)
                        results.append(f"TOOL: {matched_name}\nOUTPUT:\n{output}")
                    else:
                        results.append(f"Error: Tool '{req_name}' not found.")
                except Exception as e:
                    results.append(f"Error executing block: {str(e)}")

            return "\n\n".join(results)
        except Exception as e:
            return f"Critical Parser Error: {str(e)}"

    def auto_commit_memory(self, tool_output):
        blocks = tool_output.split("TOOL: ")
        for block in blocks:
            if not block.strip(): continue
            try:
                if "OUTPUT:\n{" in block:
                    data = json.loads("{" + block.split("OUTPUT:\n{")[1])
                    inst = data.get("instrument", "Unknown")
                    last_price = float(data.get("last_price", 0))
                    high = float(data.get("high_24h", 0))
                    low = float(data.get("low_24h", 0))
                    
                    if inst != "Unknown":
                        self.memory.save_market_memory(inst, f"Delta: {last_price}", low, high)
                        logger.info(f"State Committed: {inst}")
            except: continue

    def llm_call(self, messages):
        try:
            response = self.llm.create_chat_completion(
                messages=messages, temperature=0.1, max_tokens=1024
            )
            return response['choices'][0]['message']['content']
        except Exception as e:
            return f"Inference Error: {str(e)}"

# ================================================================================================
# TECHNICAL TOOLS
# ================================================================================================

def fetch_okx_ticker(inst_id: str = "BTC-USDT", **kwargs):
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/ticker"
        resp = requests.get(url, params={"instId": inst_id}, timeout=5).json()
        if resp.get("code") == "0" and resp.get("data"):
            t = resp["data"][0]
            return json.dumps({"instrument": inst_id, "last_price": t.get("last"), "high_24h": t.get("high24h"), "low_24h": t.get("low24h"), "volume_24h": t.get("vol24h")}, indent=2)
        return f"Error: No data for {inst_id}"
    except Exception as e: return f"API Error: {str(e)}"

def fetch_okx_candles(inst_id: str = "BTC-USDT", bar: str = "1H", limit: int = 10, **kwargs):
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/candles"
        resp = requests.get(url, params={"instId": inst_id, "bar": bar, "limit": limit}, timeout=5).json()
        if resp.get("code") == "0": return json.dumps(resp.get("data", []), indent=2)
        return "Error: Candle fetch failed."
    except Exception as e: return f"API Error: {str(e)}"

def fetch_rpi_index(inst_id: str = "BTC-USDT", **kwargs):
    ticker = json.loads(fetch_okx_ticker(inst_id))
    if "Error" in ticker: return ticker
    try:
        last, high, low = float(ticker["last_price"]), float(ticker["high_24h"]), float(ticker["low_24h"])
        rpi = ((last - low) / (high - low)) * 100 if (high - low) > 0 else 50
        classification = "Lower-Range Compression" if rpi <= 30 else "Upper-Range Expansion" if rpi >= 70 else "Mid-Range Equilibrium"
        return json.dumps({"instrument": inst_id, "rpi_index": round(rpi, 2), "rpi_classification": classification}, indent=2)
    except Exception as e: return f"Error: {str(e)}"

def fetch_technical_indicators(inst_id: str = "BTC-USDT", bar: str = "1H", **kwargs):
    candles_json = fetch_okx_candles(inst_id, bar, limit=50)
    if "Error" in candles_json: return candles_json
    try:
        candles = json.loads(candles_json)
        closes = [float(c[4]) for c in candles][::-1]
        if len(closes) < 21: return "Error: Data Insufficient."
        def get_ema(data, period):
            ema = [sum(data[:period])/period]
            mult = 2/(period+1)
            for p in data[period:]: ema.append((p - ema[-1]) * mult + ema[-1])
            return ema[-1]
        def get_rsi(data, period=14):
            gains = [max(data[i]-data[i-1], 0) for i in range(1, len(data))]
            losses = [max(data[i-1]-data[i], 0) for i in range(1, len(data))]
            avg_g, avg_l = sum(gains[:period])/period, sum(losses[:period])/period
            for i in range(period, len(gains)):
                avg_g, avg_l = (avg_g*(period-1)+gains[i])/period, (avg_l*(period-1)+losses[i])/period
            if avg_l == 0: return 100
            return 100 - (100/(1+(avg_g/avg_l)))
        ema9, ema21, rsi14 = get_ema(closes, 9), get_ema(closes, 21), get_rsi(closes, 14)
        return json.dumps({"instrument": inst_id, "ema_9": round(ema9, 2), "ema_21": round(ema21, 2), "rsi_14": round(rsi14, 2), "trend": "Bullish" if ema9 > ema21 else "Bearish"}, indent=2)
    except Exception as e: return f"Error: {str(e)}"

def fetch_order_book_walls(inst_id: str = "BTC-USDT", **kwargs):
    try:
        url = f"{OKX_REST_HOST}/api/v5/market/books"
        resp = requests.get(url, params={"instId": inst_id, "sz": 20}, timeout=5).json()
        if resp.get("code") == "0" and resp.get("data"):
            data = resp["data"][0]
            bids, asks = data.get("bids", []), data.get("asks", [])
            if not bids or not asks: return "Error: Empty Book."
            top_bid = max(bids, key=lambda x: float(x[1]))
            top_ask = max(asks, key=lambda x: float(x[1]))
            return json.dumps({"instrument": inst_id, "buy_wall": {"price": top_bid[0], "size": top_bid[1]}, "sell_wall": {"price": top_ask[0], "size": top_ask[1]}}, indent=2)
        return "Error: Fetch failed."
    except Exception as e: return f"Error: {str(e)}"

def fetch_quantitative_setup(inst_id: str = "BTC-USDT", **kwargs):
    try:
        macro_json = fetch_okx_candles(inst_id, bar="1H", limit=250)
        if "Error" in macro_json: return macro_json
        macro_closes = [float(c[4]) for c in json.loads(macro_json)[::-1]]
        def get_ema(data, period):
            ema = [sum(data[:period])/period]
            mult = 2/(period+1)
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
    except Exception as e: return f"Error: {str(e)}"

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
                liq_url = f"{global_host}/api/v5/public/liquidation-info"
                liq_resp = requests.get(liq_url, params={"instId": swap_inst, "mgnMode": "cross", "limit": 20}, timeout=5).json()
                if liq_resp.get("code") == "0" and liq_resp.get("data"):
                    sentiment_data["recent_liquidations_sz"] = round(sum(float(x.get("sz", 0)) for x in liq_resp["data"]), 2)
                if sentiment_data.get("funding_rate"): break
        except Exception as e: logger.warning(f"Sentiment failed: {e}"); continue
    return json.dumps(sentiment_data, indent=2)

def fetch_global_market_status(**kwargs):
    watchlist = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "OKB-USDT", "USDC-USDT"]
    results = {}
    try:
        for inst in watchlist:
            ticker = json.loads(fetch_okx_ticker(inst))
            results[inst] = {"price": float(ticker.get("last_price", 0)), "24h_high": ticker.get("high_24h"), "24h_low": ticker.get("low_24h")}
        return json.dumps(results, indent=2)
    except Exception as e: return f"Error: {str(e)}"

def fetch_volatility_metrics(inst_id: str = "BTC-USDT", **kwargs):
    try:
        candles = json.loads(fetch_okx_candles(inst_id, bar="1H", limit=30))
        true_ranges = []
        for i in range(1, len(candles)):
            h, l, prev_c = float(candles[i][2]), float(candles[i][3]), float(candles[i-1][4])
            true_ranges.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
        atr = sum(true_ranges[-14:]) / 14 if len(true_ranges) >= 14 else 0
        return json.dumps({"instrument": inst_id, "hourly_atr": round(atr, 2), "volatility_ratio": round(atr / float(candles[-1][4]) * 100, 4)}, indent=2)
    except Exception as e: return f"Error: {str(e)}"

def record_structural_insight(key: str, value: str, **kwargs):
    global agent
    try: return agent.memory.save_structural_insight(key, value)
    except Exception as e: return f"Error: {str(e)}"

def fetch_historical_lookback(inst_id: str = "BTC-USDT", days: int = 7, **kwargs):
    try:
        if "lookback_days" in kwargs: days = int(kwargs["lookback_days"])
        limit = days * 24
        candles = json.loads(fetch_okx_candles(inst_id, bar="1H", limit=limit))
        closes, vols = [float(x[4]) for x in candles], [float(x[5]) for x in candles]
        delta_pct = ((closes[-1] - closes[0]) / closes[0]) * 100
        return json.dumps({"instrument": inst_id, "lookback_period_days": days, "high": max(closes), "low": min(closes), "avg_hourly_volume": round(sum(vols)/len(vols), 2), "period_performance": f"{delta_pct:+.2f}%"}, indent=2)
    except Exception as e: return f"Error: {str(e)}"

def fetch_smart_patterns(inst_id: str = "BTC-USDT", bar: str = "1H", **kwargs):
    try:
        candles = json.loads(fetch_okx_candles(inst_id, bar, limit=50))
        h, l = [float(x[2]) for x in candles][::-1], [float(x[3]) for x in candles][::-1]
        h_trend = (h[-1] > h[-10]) and (h[-10] > h[-20])
        l_trend = (l[-1] > l[-10]) and (l[-10] > l[-20])
        recent_range, hist_range = max(h[-5:]) - min(l[-5:]), max(h[-20:]) - min(l[-20:])
        pattern, prob = "Neutral/Chop", 50
        if h_trend and l_trend: pattern, prob = "Ascending Channel", 65
        elif not h_trend and not l_trend: pattern, prob = "Descending Channel", 60
        if recent_range < (hist_range * 0.5): pattern, prob = "Volatility Compression (Squeeze)", 70
        return json.dumps({"instrument": inst_id, "detected_pattern": pattern, "historical_resolution_probability": f"{prob}%"}, indent=2)
    except Exception as e: return f"Error: {str(e)}"

def ai_mentor_lookup(term: str = "RSI", **kwargs):
    glossary = {"RSI": "Relative Strength Index. Measures 'overbought' (>70) or 'oversold' (<30).", "EMA": "Exponential Moving Average. Trend-following line weighting recent price more.", "ATR": "Average True Range. Volatility measurement.", "CONFLUENCE": "Multiple indicators aligning for higher probability.", "FUNDING_RATE": "Leverage bias fee. High positive = Long heavy.", "OPEN_INTEREST": "Total active contracts. Rising = New capital entry."}
    matches = difflib.get_close_matches(term.upper(), list(glossary.keys()), n=1, cutoff=0.4)
    if matches: return json.dumps({"term": matches[0], "explanation": glossary[matches[0]]}, indent=2)
    return f"Term '{term}' not found."

def fetch_news_wire(keywords: str = "bitcoin,btc,sec,liquidation,etf,solana", max_items: int = 5, **kwargs):
    """
    FETCH_NEWS_WIRE:
    Scans live crypto news wire feeds for market-moving keywords using zero-dependency XML parsing.
    """
    feed_url = "https://cointelegraph.com/rss"
    target_keywords = [kw.strip().lower() for kw in keywords.split(",")]
    
    try:
        req = urllib.request.Request(
            feed_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        channel = root.find('channel')
        if channel is None:
            return json.dumps({"error": "Invalid RSS structure"})
            
        items = []
        for item in channel.findall('item'):
            title = item.find('title')
            description = item.find('description')
            
            title_text = title.text if title is not None else ""
            desc_text = description.text if description is not None else ""
            
            # Check text relevance
            combined_text = f"{title_text} {desc_text}".lower()
            matched = any(kw in combined_text for kw in target_keywords)
            
            if matched or not target_keywords:
                items.append({
                    "title": title_text.strip(),
                    "published": item.find('pubDate').text.strip() if item.find('pubDate') is not None else "",
                    "snippet": desc_text[:140].strip() + "..." if len(desc_text) > 140 else desc_text.strip()
                })
                
            if len(items) >= max_items:
                break
                
        return json.dumps({
            "wire_source": feed_url,
            "matched_articles_count": len(items),
            "articles": items
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch news wire: {str(e)}"})

def ai_chart_analyzer(inst_id: str = "BTC-USDT", **kwargs):
    """
    AI_CHART_ANALYZER:
    Aggregated analysis tool: Price Action, Volatility, Indicators, and News Wire.
    """
    try:
        ticker = json.loads(fetch_okx_ticker(inst_id))
        volatility = json.loads(fetch_volatility_metrics(inst_id))
        indicators = json.loads(fetch_technical_indicators(inst_id))
        news = json.loads(fetch_news_wire()) # Default keywords for general context
        
        return json.dumps({
            "instrument": inst_id,
            "price_action": ticker,
            "volatility": volatility,
            "indicators": indicators,
            "recent_news_wire": news
        }, indent=2)
    except Exception as e:
        return f"Error in aggregated analyzer: {str(e)}"

async def run_autonomous_loop(agent_instance):
    logger.info("Autonomous Strategy Scanning Active.")
    while True:
        try:
            prompt = (
                "Scan BTC-USDT using the BALANCED and MOMENTUM strategy presets. "
                "1. Utilize ai_chart_analyzer and fetch_smart_patterns. "
                "2. Check market sentiment and institutional walls. "
                "3. If a setup criteria is met, generate a SETUP NOTIFICATION CARD with Entry, SL, and Target. "
                "4. If no setup exists, provide a professional quantitative monitoring report."
            )
            print(f"\n[!] TRINITY STRATEGY SCAN: {datetime.now().strftime('%H:%M:%S')}")
            reply = agent_instance.run_step(prompt)
            print(f"\n[Autonomous Output]:\n{reply}\n" + "-" * 80)
            await asyncio.sleep(900)
        except Exception as e: logger.error(f"Loop error: {e}", exc_info=True); await asyncio.sleep(60)

if __name__ == "__main__":
    print("[*] Initializing Quant Agent Trinity (GGUF Mode)...")
    gguf_path = "C:/ai_models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf"
    try:
        agent = QuantAgentTrinity(model_path=gguf_path)
        agent.register_tool("fetch_okx_ticker", fetch_okx_ticker, "Real-time telemetry.")
        agent.register_tool("fetch_okx_candles", fetch_okx_candles, "Historical OHLCV.")
        agent.register_tool("fetch_rpi_index", fetch_rpi_index, "Relative price location (RPI).")
        agent.register_tool("fetch_technical_indicators", fetch_technical_indicators, "EMA/RSI metrics.")
        agent.register_tool("fetch_order_book_walls", fetch_order_book_walls, "Institutional liquidity blocks.")
        agent.register_tool("check_quantitative_confluence", fetch_quantitative_setup, "Macro/Tactical confluence scoring.")
        agent.register_tool("fetch_market_sentiment", fetch_market_sentiment, "Funding/OI/Liquidations.")
        agent.register_tool("fetch_global_market_status", fetch_global_market_status, "Market-wide majors scan.")
        agent.register_tool("fetch_volatility_metrics", fetch_volatility_metrics, "ATR/Volatility ratios.")
        agent.register_tool("record_structural_insight", record_structural_insight, "Save permanent technical insights.")
        agent.register_tool("fetch_historical_lookback", fetch_historical_lookback, "Multi-day statistical analysis.")
        agent.register_tool("ai_chart_analyzer", ai_chart_analyzer, "Aggregated analysis: price action, volatility, indicators, and news wire.")
        agent.register_tool("fetch_smart_patterns", fetch_smart_patterns, "Identify chart structures and probabilities.")
        agent.register_tool("ai_mentor", ai_mentor_lookup, "Explain market terminology in plain language.")
        agent.register_tool("fetch_news_wire", fetch_news_wire, "Scans live crypto news feeds for market-moving keywords.")
        asyncio.run(run_autonomous_loop(agent))
    except (KeyboardInterrupt, SystemExit): print("\n[*] Trinity deactivated.")
    except Exception as e: print(f"[!] Launch Failure: {e}"); sys.exit(1)
