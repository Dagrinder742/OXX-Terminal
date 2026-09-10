"""
OXX-Terminal-US ENDPOINTS GUIDANCE:
REST: us.okx.com / api/v5/
WSS:  wss://ws.okx.com:8443/ws/v5/public
"""

import json
import os
import sys
import logging
import requests
import asyncio
import re
from llama_cpp import Llama
from datetime import datetime

# Configure professional logging standard
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("QuantAgentTrinity")

# Import News Engine with fallback
try:
    from news_engine import background_news_poller
except Exception:
    logger.error("news_engine.py not found. Background news sync disabled.")
    async def background_news_poller(**kwargs): pass

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
            except Exception as e:
                logger.error(f"Memory load error: {e}")
        return {"structural_insights": {}, "history": []}

    def save_memory(self):
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Memory save failure: {e}")

    def save_market_memory(self, inst_id: str, market_state: str, support: float = 0.0, resistance: float = 0.0):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "instrument": inst_id,
            "market_state": market_state,
            "support": support,
            "resistance": resistance
        }
        self.data["history"].append(entry)
        self.data["history"] = self.data["history"][-20:] # Keep 20 for internal storage
        self.save_memory()
        return f"Memory Committed: {inst_id}"

    def save_structural_insight(self, key: str, value: str):
        self.data["structural_insights"][key] = {"timestamp": datetime.now().isoformat(), "data": value}
        self.save_memory()
        return f"Insight Saved: {key}"

    def get_all_structural_insights(self):
        return json.dumps(self.data["structural_insights"], indent=2)

    def get_recent_history_string(self):
        if not self.data["history"]: return "No recent market history available."
        return json.dumps(self.data["history"][-5:], indent=2)

# ================================================================================================
# DETERMINISTIC QUANT LOGIC (Python Side)
# ================================================================================================

OKX_REST_HOST = "https://us.okx.com"

def calculate_spot_setup(price: float) -> dict:
    """Calculates fee-aware spot entry/exit levels with a 1.5% net profit hurdle and 0.75% SL."""
    fee_hurdle = 0.004   # 0.4% round-trip maker fee
    min_gain = 0.015     # 1.5% target net expansion
    stop_loss_pct = 0.0075 # 0.75% max risk
    
    # Spot math: Stop loss is always below entry, take profit is always above entry
    sl = price * (1.0 - stop_loss_pct)
    tp = price * (1.0 + min_gain + fee_hurdle)
        
    risk = price - sl
    reward = tp - price
    rr_ratio = reward / risk if risk > 0 else 0
    
    return {
        "strategy": "SPOT_ACCUMULATION",
        "entry": round(price, 2),
        "stop_loss": round(sl, 2),
        "take_profit": round(tp, 2),
        "risk_reward_ratio": round(rr_ratio, 2),
        "valid_setup": rr_ratio >= 2.0
    }

def get_market_snapshot(inst_id: str = "BTC-USDT"):
    """Programmatic data gathering pipeline (Pre-Inference)."""
    try:
        # 1. Fetch Ticker
        t_resp = requests.get(f"{OKX_REST_HOST}/api/v5/market/ticker?instId={inst_id}", timeout=5).json()
        ticker = t_resp["data"][0] if t_resp.get("code") == "0" else {}
        last_px = float(ticker.get("last", 0))
        
        # 2. Fetch Technicals (EMA 9/21)
        c_resp = requests.get(f"{OKX_REST_HOST}/api/v5/market/candles?instId={inst_id}&bar=1H&limit=50", timeout=5).json()
        candles = c_resp.get("data", [])
        closes = [float(c[4]) for c in candles][::-1]
        
        def ema(data, p):
            if len(data) < p: return 0
            m = 2/(p+1); e = [sum(data[:p])/p]
            for x in data[p:]: e.append((x-e[-1])*m + e[-1])
            return e[-1]
        
        ema9, ema21 = ema(closes, 9), ema(closes, 21)
        trend = "Bullish" if last_px > ema21 and ema9 > ema21 else "Bearish" if last_px < ema21 else "Neutral"

        # 3. Fetch News Memory
        news = []
        if os.path.exists("articles.json"):
            with open("articles.json", "r") as f: news = json.load(f)[:3]

        return {
            "asset": inst_id,
            "price": last_px,
            "trend": trend,
            "indicators": {"ema9": round(ema9, 2), "ema21": round(ema21, 2)},
            "news_sentiment": news,
            "spot_setup": calculate_spot_setup(last_px)
        }
    except Exception as e:
        logger.error(f"Snapshot Pipeline Error: {e}")
        return None

# ================================================================================================
# AGENT ENGINE (Pipeline Inference)
# ================================================================================================

class QuantAgentTrinity:
    def __init__(self, model_path="C:/ai_models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf", memory_file="agent_memory.json"):
        self.model_path = model_path
        self.model_name = os.path.basename(model_path)
        self.memory = AgentMemory(memory_file)
        
        logger.info(f"Trinity Pipeline Booting: {self.model_name}")
        self.llm = Llama(model_path=self.model_path, n_ctx=16384, n_gpu_layers=0, n_threads=4, verbose=False)

        self.system_instructions = (
            "You are Quant Agent Trinity, the analytical brain of the OXX Terminal.\n\n"
            "OPERATIONAL PROTOCOL:\n"
            "1. INTERNAL VOICE: You MUST start every response with a <thinking> block detailing your strategic deliberation.\n"
            "2. TRADING REGION: US (SPOT ONLY - BUY LOW / SELL HIGH).\n"
            "3. OBJECTIVE: Evaluate the [MARKET SNAPSHOT] against news sentiment and pre-computed levels.\n"
            "4. CRITICAL: Use the exact prices from [PRE-COMPUTED SPOT SETUP]. Do NOT calculate your own.\n\n"
            "NOTIFICATION CARD FORMAT:\n"
            "--- SETUP NOTIFICATION CARD ---\n"
            "ASSET: [Ticker]\n"
            "STRATEGY: [SPOT_ACCUMULATION]\n"
            "PROPOSED ENTRY: [Exact Pre-computed Entry]\n"
            "STOP LOSS: [Exact Pre-computed Stop Loss]\n"
            "TAKE PROFIT: [Exact Pre-computed Take Profit]\n"
            "EXPLANATION: [Mentor-style justification of why the setup aligns with sentiment]\n"
            "--------------------------------"
        )

    def run_cycle(self):
        """Unified Pipeline: Data -> Logic -> Inference -> Memory."""
        print(f"[*] Starting Autonomous Pipeline Pulse...")
        
        # 1. Programmatic Perception
        snapshot = get_market_snapshot("BTC-USDT")
        if not snapshot or snapshot["price"] == 0:
            return "Pipeline Error: Market data retrieval failed."

        # 2. Context Injection
        prompt = f"""
        [MARKET SNAPSHOT: SPOT TRADING ONLY (US REGION)]
        Asset: {snapshot['asset']} | Current Price: ${snapshot['price']}
        Trend: {snapshot['trend']} (EMA9: {snapshot['indicators']['ema9']} / EMA21: {snapshot['indicators']['ema21']})
        
        [LIVE NEWS CONTEXT]
        {json.dumps(snapshot['news_sentiment'], indent=2)}
        
        [PRE-COMPUTED SPOT SETUP]
        {snapshot['spot_setup']}
        
        TASK: Deliberate in a <thinking> block, then provide the strategic verdict.
        Strictly enforce Spot-Only parameters (Buy Low / Sell High).
        """

        conversation = [
            {"role": "system", "content": self.system_instructions},
            {"role": "user", "content": prompt}
        ]

        # 3. Single-Shot Inference
        print("[*] Trinity Reasoning Phase...")
        try:
            response = self.llm.create_chat_completion(messages=conversation, temperature=0.1, max_tokens=4096)
            reply = response['choices'][0]['message']['content']
            
            # 4. Extract and print the internal voice (Thinking Block)
            thought_match = re.search(r'<thinking>(.*?)</thinking>', reply, re.DOTALL)
            if thought_match:
                print(f"\n[Trinity Thought]: {thought_match.group(1).strip()}")
            
            # 5. Commit state to memory
            self.memory.save_market_memory(
                snapshot['asset'], 
                f"Pulse: {snapshot['price']} ({snapshot['trend']})",
                snapshot['spot_setup']['stop_loss'],
                snapshot['spot_setup']['take_profit']
            )

            # Return cleaned verdict for the UI
            return re.sub(r'<thinking>.*?</thinking>', '', reply, flags=re.DOTALL).strip()
        except Exception as e:
            return f"Inference Error: {e}"

# ================================================================================================
# MAIN ORCHESTRATION
# ================================================================================================

async def run_autonomous_pipeline(agent_instance):
    logger.info("Autonomous Pipeline Engine Active.")
    while True:
        try:
            print(f"\n[!] TRINITY PIPELINE CYCLE: {datetime.now().strftime('%H:%M:%S')}")
            verdict = agent_instance.run_cycle()
            print(f"\n[Autonomous Output]:\n{verdict}\n" + "-" * 80)
            await asyncio.sleep(900)
        except Exception as e:
            logger.error(f"Pipeline Loop Error: {e}")
            await asyncio.sleep(60)

async def main():
    gguf_path = "C:/ai_models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf"
    try:
        agent = QuantAgentTrinity(model_path=gguf_path)
        # Run news engine in background
        asyncio.create_task(background_news_poller(interval=600))
        # Run main agent pipeline
        await run_autonomous_pipeline(agent)
    except (KeyboardInterrupt, SystemExit):
        print("\n[*] Trinity successfully deactivated.")
    except Exception as e:
        print(f"[!] Critical Launch Failure: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Standard exit for CLI tools to prevent traceback dumps
        print("\n[*] Trinity successfully deactivated by user.")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
