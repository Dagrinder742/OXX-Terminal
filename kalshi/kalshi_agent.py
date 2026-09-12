"""
KALSHI-TERMINAL ENDPOINTS GUIDANCE:
REST: https://api.elections.kalshi.com / trade-api/v2/
WSS:  wss://api.elections.kalshi.com/trade-api/ws/v2
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

# ================================================================================================
# TRADE EXECUTION AUTHORITY
# ================================================================================================

import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.serialization import load_pem_private_key

# Configure your API credentials here or via environment variables
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "837934ae-214d-4a46-86ff-dbfb21619e49")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", r"C:\Users\krayz\AndroidStudioProjects\OXXTerminal\app\src\main\Python\kalshi\main.txt")

def execute_kalshi_trade(ticker: str, side: str, count: int = 1, price_cents: int = 50):
    """Signs and submits a live order to the Kalshi REST API."""
    endpoint = "/trade-api/v2/portfolio/orders"
    url = f"{KALSHI_REST_HOST.replace('/trade-api/v2', '')}{endpoint}"

    timestamp = str(int(datetime.now().timestamp() * 1000))
    method = "POST"

    # 1. Build the message string required by Kalshi: timestamp + method + endpoint path
    # (Note: Kalshi path should match the exact endpoint route excluding host)
    msg_string = timestamp + method + endpoint

    signature_str = ""
    try:
        # 2. Load the RSA private key from your specified text/PEM file
        if os.path.exists(KALSHI_PRIVATE_KEY_PATH):
            with open(KALSHI_PRIVATE_KEY_PATH, "rb") as key_file:
                private_key = load_pem_private_key(key_file.read(), password=None)

            # 3. Sign using RSA-PKCS1v15 and SHA256 as required by Kalshi
            signature = private_key.sign(
                msg_string.encode('utf-8'),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            # 4. Base64 encode the resulting signature bytes for the HTTP header string
            signature_str = base64.b64encode(signature).decode('utf-8')
        else:
            logger.error(f"Private key file not found at path: {KALSHI_PRIVATE_KEY_PATH}")
            return False
    except Exception as e:
        logger.error(f"RSA Signature Generation Failure: {e}")
        return False

    payload = {
        "ticker": ticker,
        "action": "buy",
        "type": "limit",
        "side": side.lower(), # "yes" or "no"
        "count": count,
        "yes_price" if side.lower() == "yes" else "no_price": price_cents
    }

    headers = {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature_str
    }

    try:
        logger.info(f"Dispatching live order to Kalshi: {side} on {ticker} ({count} contract @ {price_cents}¢)")
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code in [200, 201]:
            logger.info("Order successfully executed on Kalshi!")
            return True
        else:
            logger.error(f"Order rejected by Kalshi API [{response.status_code}]: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Execution Transport Error: {e}")
        return False

# ================================================================================================
# MEMORY ENGINE
# ================================================================================================

class AgentMemory:
    """Handles persistent JSON storage for historical telemetry and structural insights."""
    def __init__(self, memory_file="kalshi_agent_memory.json"):
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

    def save_market_memory(self, ticker: str, market_state: str, yes_bid: float = 0.0, no_bid: float = 0.0):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "market_state": market_state,
            "yes_bid": yes_bid,
            "no_bid": no_bid
        }
        self.data["history"].append(entry)
        self.data["history"] = self.data["history"][-20:] # Keep last 20 records
        self.save_memory()
        return f"Memory Committed: {ticker}"

    def get_recent_history_string(self):
        if not self.data["history"]: return "No recent market history available."
        return json.dumps(self.data["history"][-5:], indent=2)

# ================================================================================================
# DETERMINISTIC KALSHI QUANT LOGIC (Binary Option Pricing)
# ================================================================================================

KALSHI_REST_HOST = "https://api.elections.kalshi.com/trade-api/v2"

def calculate_kalshi_setup(yes_price: int, no_price: int) -> dict:
    """Evaluates binary contract value, implied probability, and risk-reward structure."""
    # Kalshi contracts settle at 100 cents ($1.00) or 0 cents ($0.00)
    max_payout = 100

    # Simple expected value / risk-reward boundary check
    implied_yes_prob = yes_price / 100.0

    return {
        "strategy": "BINARY_EVENT_POSITIONING",
        "yes_ask_cents": yes_price,
        "no_ask_cents": no_price,
        "implied_probability": round(implied_yes_prob * 100, 1),
        "max_risk_cents": yes_price,
        "max_reward_cents": max_payout - yes_price,
        "valid_setup": yes_price > 0 and yes_price < 95 # Avoid dead markets
    }

def get_kalshi_market_snapshot(ticker: str = "KXBTC15M-26SEP112215-15"):
    """Programmatic data gathering pipeline for Kalshi 15M / Event tickers."""
    try:
        # Fetch Market Orderbook / Details via Kalshi Public API
        resp = requests.get(f"{KALSHI_REST_HOST}/markets/{ticker}", timeout=5)
        if resp.status_code != 200:
            logger.error(f"Kalshi API error: {resp.status_code}")
            return None

        data = resp.json().get("market", {})
        yes_bid = data.get("yes_bid", 50)
        yes_ask = data.get("yes_ask", 50)
        no_bid = data.get("no_bid", 50)
        no_ask = data.get("no_ask", 50)
        last_price = data.get("last_price", 50)

        # Fetch News Memory if available
        news = []
        if os.path.exists("articles.json"):
            with open("articles.json", "r") as f: news = json.load(f)[:3]

        return {
            "ticker": ticker,
            "title": data.get("title", "Unknown Contract"),
            "yes_price": yes_ask, # Using ask as entry reference
            "no_price": no_ask,
            "last_price": last_price,
            "news_sentiment": news,
            "contract_setup": calculate_kalshi_setup(yes_ask, no_ask)
        }
    except Exception as e:
        logger.error(f"Kalshi Snapshot Pipeline Error: {e}")
        return None

# ================================================================================================
# AGENT ENGINE (Pipeline Inference)
# ================================================================================================

class QuantAgentKalshiTrinity:
    def __init__(self, model_path="C:/ai_models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf", memory_file="kalshi_agent_memory.json"):
        self.model_path = model_path
        self.model_name = os.path.basename(model_path)
        self.memory = AgentMemory(memory_file)

        logger.info(f"Kalshi Trinity Pipeline Booting: {self.model_name}")
        self.llm = Llama(model_path=self.model_path, n_ctx=16384, n_gpu_layers=0, n_threads=4, verbose=False)

        self.system_instructions = (
            "You are Quant Agent Trinity, the analytical brain of the Kalshi Terminal.\n\n"
            "OPERATIONAL PROTOCOL:\n"
            "1. INTERNAL VOICE: You MUST start every response with a <thinking> block detailing your strategic deliberation.\n"
            "2. TRADING REGION: US (BINARY EVENT CONTRACTS - YES/NO SETTLEMENTS AT $1.00).\n"
            "3. OBJECTIVE: Evaluate the [KALSHI MARKET SNAPSHOT] against news sentiment and pre-computed contract probabilities.\n"
            "4. CRITICAL: Use the exact contract pricing from [PRE-COMPUTED CONTRACT SETUP]. Do NOT calculate your own.\n\n"
            "NOTIFICATION CARD FORMAT:\n"
            "--- KALSHI SETUP NOTIFICATION CARD ---\n"
            "TICKER: [Contract Ticker]\n"
            "STRATEGY: [BINARY_EVENT_POSITIONING]\n"
            "RECOMMENDED SIDE: [YES or NO]\n"
            "ENTRY COST (CENTS): [Exact Pre-computed Entry Price]\n"
            "MAX PAYOUT (CENTS): 100\n"
            "IMPLIED PROBABILITY: [Pre-computed %]\n"
            "EXPLANATION: [Mentor-style justification of why the event outcome favors this side]\n"
            "---------------------------------------"
        )

    def run_cycle(self, target_ticker="KXBTC15M-26SEP112215-15"):
        """Unified Pipeline: Data -> Memory Context -> Logic -> Inference -> State Commit."""
        print(f"[*] Starting Kalshi Autonomous Pipeline Pulse for {target_ticker}...")

        # 1. Programmatic Perception
        snapshot = get_kalshi_market_snapshot(target_ticker)
        if not snapshot:
            return "Pipeline Error: Kalshi market data retrieval failed."

        # 2. Retrieve Recent Memory Context for Continuity
        recent_history = self.memory.get_recent_history_string()

        # 3. Context Injection
        prompt = f"""
        [KALSHI MARKET SNAPSHOT: BINARY CONTRACTS]
        Ticker: {snapshot['ticker']} | Title: {snapshot['title']}
        Current Yes Ask: {snapshot['yes_price']}¢ | Current No Ask: {snapshot['no_price']}¢ | Last: {snapshot['last_price']}¢

        [RECENT AGENT MEMORY LOGS]
        {recent_history}

        [LIVE NEWS CONTEXT]
        {json.dumps(snapshot['news_sentiment'], indent=2)}

        [PRE-COMPUTED CONTRACT SETUP]
        {snapshot['contract_setup']}

        TASK: Deliberate inside <thinking>...</thinking> tags. Then output ONLY the KALSHI SETUP NOTIFICATION CARD. Do not include raw tags outside your thinking block.
        """

        conversation = [
            {"role": "system", "content": self.system_instructions},
            {"role": "user", "content": prompt}
        ]

        # 4. Single-Shot Inference
        print("[*] Kalshi Trinity Reasoning Phase...")
        try:
            response = self.llm.create_chat_completion(
                messages=conversation, 
                temperature=0.1, 
                max_tokens=4096,
                stop=["</thought>", "</s>"]
            )
            reply = response['choices'][0]['message']['content']

            # 5. Extract and print internal voice
            thought_match = re.search(r'<thinking>(.*?)</thinking>', reply, re.DOTALL)
            if thought_match:
                print(f"\n[Trinity Thought]: {thought_match.group(1).strip().replace(chr(10), ' ')}")

            # 6. Commit state to memory
            self.memory.save_market_memory(
                snapshot['ticker'], 
                f"Pulse: Yes@{snapshot['yes_price']}¢ / No@{snapshot['no_price']}¢",
                snapshot['yes_price'],
                snapshot['no_price']
            )

            # 7. Strip thinking blocks from final output card
            clean_verdict = re.sub(r'<thinking>.*?</thinking>', '', reply, flags=re.DOTALL).strip()
            clean_verdict = re.sub(r'</?thinking>', '', clean_verdict).strip()

            return clean_verdict
        except Exception as e:
            return f"Inference Error: {e}"

# ================================================================================================
# MAIN ORCHESTRATION
# ================================================================================================

async def run_autonomous_pipeline(agent_instance):
    logger.info("Kalshi Autonomous Pipeline Engine Active (Execution Mode Ready).")
    active_ticker = "KXBTC15M-26SEP112215-15"
    while True:
        try:
            print(f"\n[!] KALSHI TRINITY PIPELINE CYCLE: {datetime.now().strftime('%H:%M:%S')}")
            verdict = agent_instance.run_cycle(active_ticker)
            print(f"\n[Autonomous Output]:\n{verdict}\n" + "-" * 80)

            # --- INTERACTIVE EXECUTION GATE ---
            # Parse the side recommended by Trinity from her output card
            match = re.search(r'RECOMMENDED SIDE:\s*(YES|NO)', verdict, re.IGNORECASE)
            if match:
                recommended_side = match.group(1).upper()
                if recommended_side in ["YES", "NO"]:
                    choice = input(f"\n[?] Trinity recommends taking a **{recommended_side}** position. Execute order? (y/n): ").strip().lower()
                    if choice == 'y':
                        # Extract entry price or default safely
                        price_match = re.search(r'ENTRY COST \(CENTS\):\s*(\d+)', verdict)
                        price_cents = int(price_match.group(1)) if price_match else 50

                        execute_kalshi_trade(active_ticker, recommended_side, count=1, price_cents=price_cents)
                    else:
                        print("[*] Trade execution skipped by user.")

            await asyncio.sleep(900)
        except Exception as e:
            logger.error(f"Pipeline Loop Error: {e}")
            await asyncio.sleep(60)

async def main():
    gguf_path = "C:/ai_models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf"
    try:
        agent = QuantAgentKalshiTrinity(model_path=gguf_path)
        asyncio.create_task(background_news_poller(interval=600))
        await run_autonomous_pipeline(agent)
    except (KeyboardInterrupt, SystemExit):
        print("\n[*] Kalshi Trinity successfully deactivated.")
    except Exception as e:
        print(f"[!] Critical Launch Failure: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Kalshi Trinity successfully deactivated by user.")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
