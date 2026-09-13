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

# Setup basic logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("KalshiTrinity")

# ================================================================================================
# TRADE EXECUTION, PORTFOLIO & SETTLEMENT AUTHORITY
# ================================================================================================

import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_private_key

KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "837934ae-214d-4a46-86ff-dbfb21619e49")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", r"C:\Users\krayz\AndroidStudioProjects\OXXTerminal\app\src\main\Python\kalshi\main.txt")
KALSHI_REST_HOST = "https://api.elections.kalshi.com/trade-api/v2"

def _generate_kalshi_headers(method: str, endpoint: str) -> dict:
    """Generates the required RSA signed headers for Kalshi REST endpoints."""
    timestamp = str(int(datetime.now().timestamp() * 1000))
    msg_string = timestamp + method.upper() + endpoint

    signature_str = ""
    try:
        if os.path.exists(KALSHI_PRIVATE_KEY_PATH):
            with open(KALSHI_PRIVATE_KEY_PATH, "rb") as key_file:
                private_key = load_pem_private_key(key_file.read(), password=None)

            signature = private_key.sign(
                msg_string.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            signature_str = base64.b64encode(signature).decode('utf-8')
        else:
            logger.error(f"Private key file not found at path: {KALSHI_PRIVATE_KEY_PATH}")
    except Exception as e:
        logger.error(f"RSA Signature Generation Failure: {e}")

    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature_str
    }

def get_kalshi_balance():
    """Queries the Kalshi portfolio balance endpoint to retrieve available capital."""
    endpoint = "/trade-api/v2/portfolio/balance"
    url = f"https://api.elections.kalshi.com{endpoint}"
    headers = _generate_kalshi_headers("GET", endpoint)

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            balance_cents = data.get("balance", 0)
            if isinstance(balance_cents, str):
                balance_cents = int(float(balance_cents) * 100)
            elif balance_cents < 1000 and isinstance(balance_cents, float):
                balance_cents = int(balance_cents * 100)

            return {
                "balance_cents": balance_cents,
                "balance_dollars": round(balance_cents / 100.0, 2),
                "portfolio_value": data.get("portfolio_value", 0)
            }
        else:
            logger.error(f"Failed to fetch portfolio balance [{response.status_code}]: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Balance Query Transport Error: {e}")
        return None

def get_kalshi_settlements():
    """Fetches resolved market outcomes and cash settlements for performance grading."""
    endpoint = "/trade-api/v2/portfolio/settlements"
    url = f"https://api.elections.kalshi.com{endpoint}"
    headers = _generate_kalshi_headers("GET", endpoint)

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get("settlements", [])
        else:
            logger.error(f"Failed to fetch settlements [{response.status_code}]: {response.text}")
            return []
    except Exception as e:
        logger.error(f"Settlements Query Transport Error: {e}")
        return []

def execute_kalshi_trade(ticker: str, side: str, count: int = 1, price_cents: int = 50):
    """Signs and submits a live order to the Kalshi REST API."""
    endpoint = "/trade-api/v2/portfolio/orders"
    url = f"{KALSHI_REST_HOST.replace('/trade-api/v2', '')}{endpoint}"
    headers = _generate_kalshi_headers("POST", endpoint)

    payload = {
        "ticker": ticker,
        "action": "buy",
        "type": "limit",
        "side": side.lower(),
        "count": count,
    }

    if side.lower() == "yes":
        payload["yes_price"] = price_cents
    else:
        payload["no_price"] = price_cents

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
# EXPANDED PERFORMANCE MEMORY ENGINE
# ================================================================================================

class AgentMemory:
    """Handles persistent JSON storage for market history, trade audits, and success tracking."""
    def __init__(self, memory_file="kalshi_agent_memory.json"):
        self.memory_file = memory_file
        self.data = self.load_memory()

    def load_memory(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if "trade_audit_log" not in content: content["trade_audit_log"] = []
                    if "history" not in content: content["history"] = []
                    return content
            except Exception as e:
                logger.error(f"Memory load error: {e}")
        return {"trade_audit_log": [], "history": []}

    def save_memory(self):
        try:
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Memory save failure: {e}")

    def log_trade_decision(self, ticker: str, recommended_side: str, price_cents: int, status: str):
        """
        Logs a recommendation and its initial handling status.
        status options: 'PENDING_USER_APPROVAL', 'APPROVED_EXECUTED', 'DENIED_BY_USER'
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "recommended_side": recommended_side,
            "entry_cost_cents": price_cents,
            "status": status,
            "outcome": "PENDING_SETTLEMENT",
            "profit_loss_cents": 0
        }
        self.data["trade_audit_log"].append(entry)
        self.save_memory()
        return entry

    def update_latest_trade_status(self, ticker: str, new_status: str):
        """Updates the status of the most recent audit entry for a given ticker."""
        for entry in reversed(self.data["trade_audit_log"]):
            if entry["ticker"] == ticker and entry["status"] == "PENDING_USER_APPROVAL":
                entry["status"] = new_status
                self.save_memory()
                break

    def reconcile_outcomes(self, settlements):
        """Cross-references audit logs with real exchange settlements to compute win rates."""
        updated = False
        for entry in self.data["trade_audit_log"]:
            if entry["outcome"] == "PENDING_SETTLEMENT" and entry["status"] == "APPROVED_EXECUTED":
                # Find matching settlement by ticker
                for stl in settlements:
                    if stl.get("ticker") == entry["ticker"]:
                        market_result = stl.get("market_result", "").upper() # 'yes' or 'no'
                        revenue = stl.get("revenue", 0) # payout in cents
                        cost = entry["entry_cost_cents"] * stl.get("count", 1)

                        if market_result == entry["recommended_side"]:
                            entry["outcome"] = "WIN"
                            entry["profit_loss_cents"] = revenue - cost
                        else:
                            entry["outcome"] = "LOSS"
                            entry["profit_loss_cents"] = -cost
                        updated = True
        if updated:
            self.save_memory()

    def get_performance_summary(self):
        """Calculates win rate and performance metrics for the agent prompt."""
        logs = self.data["trade_audit_log"]
        completed = [l for l in logs if l["outcome"] in ["WIN", "LOSS"]]
        if not completed:
            return "No settled trade outcomes recorded yet."

        wins = len([l for l in completed if l["outcome"] == "WIN"])
        total = len(completed)
        win_rate = round((wins / total) * 100, 1)
        total_pnl = sum([l["profit_loss_cents"] for l in completed])

        return f"Total Settled: {total} | Wins: {wins} | Win Rate: {win_rate}% | Net P&L: {total_pnl:+d}¢"

    def get_audit_history_string(self):
        if not self.data["trade_audit_log"]: return "No trade audit history available."
        return json.dumps(self.data["trade_audit_log"][-5:], indent=2)

    def record_pulse(self, ticker: str, yes_price: int, no_price: int):
        """Appends a price pulse, calculates deltas, and maintains a rolling window."""
        history = self.data.setdefault("rolling_price_history", [])

        # Calculate delta from the last recorded point
        last_entry = history[-1] if history else {"yes_price": yes_price, "no_price": no_price}
        yes_delta = yes_price - last_entry["yes_price"]
        no_delta = no_price - last_entry["no_price"]

        pulse_entry = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "yes_price": yes_price,
            "no_price": no_price,
            "yes_delta": yes_delta,
            "no_delta": no_delta
        }

        history.append(pulse_entry)
        # Keep a rolling window of the last 20 pulses
        if len(history) > 20:
            self.data["rolling_price_history"] = history[-20:]

        self.save_memory()
        return pulse_entry

    def get_trend_analysis(self):
        """Computes moving averages and momentum vectors from rolling history."""
        history = self.data.get("rolling_price_history", [])
        if len(history) < 2:
            return "Insufficient historical pulses for trend calculation (Accumulating baseline...)"

        recent_yes = [h["yes_price"] for h in history[-5:]]
        ma_yes = round(sum(recent_yes) / len(recent_yes), 1)
        latest_delta = history[-1]["yes_delta"]

        direction = "STABLE / PINNED"
        if latest_delta > 0:
            direction = f"BULLISH MOMENTUM (+{latest_delta}¢)"
        elif latest_delta < 0:
            direction = f"BEARISH MOMENTUM ({latest_delta}¢)"

        return f"Recent MA (Yes): {ma_yes}¢ | Current Momentum: {direction} | Total Pulses Tracked: {len(history)}"

# ================================================================================================
# DETERMINISTIC KALSHI QUANT LOGIC
# ================================================================================================

def calculate_kalshi_setup(yes_price: int, no_price: int) -> dict:
    max_payout = 100
    implied_yes_prob = yes_price / 100.0

    return {
        "strategy": "BINARY_EVENT_POSITIONING",
        "yes_ask_cents": yes_price,
        "no_ask_cents": no_price,
        "implied_probability": round(implied_yes_prob * 100, 1),
        "max_risk_cents": yes_price,
        "max_reward_cents": max_payout - yes_price,
        "valid_setup": yes_price > 0 and yes_price < 95
    }

def get_kalshi_market_snapshot(ticker: str = "KXBTC15M-26SEP112215-15"):
    try:
        resp = requests.get(f"{KALSHI_REST_HOST}/markets/{ticker}", timeout=5)
        if resp.status_code != 200:
            logger.error(f"Kalshi API error: {resp.status_code}")
            return None

        data = resp.json().get("market", {})
        yes_ask = data.get("yes_ask", 50)
        no_ask = data.get("no_ask", 50)
        last_price = data.get("last_price", 50)

        news = []
        if os.path.exists("articles.json"):
            with open("articles.json", "r") as f: news = json.load(f)[:3]

        return {
            "ticker": ticker,
            "title": data.get("title", "Unknown Contract"),
            "yes_price": yes_ask,
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
            "2. OBJECTIVE: Evaluate the [KALSHI MARKET SNAPSHOT], [ACCOUNT PORTFOLIO STATUS], and [HISTORICAL PERFORMANCE TRACK RECORD].\n"
            "3. CRITICAL: Learn from your past win/loss history to refine edge calibration. Use exact pre-computed setup pricing.\n\n"
            "NOTIFICATION CARD FORMAT:\n"
            "--- KALSHI SETUP NOTIFICATION CARD ---\n"
            "TICKER: [Contract Ticker]\n"
            "STRATEGY: [BINARY_EVENT_POSITIONING]\n"
            "RECOMMENDED SIDE: [YES or NO]\n"
            "ENTRY COST (CENTS): [Exact Pre-computed Entry Price]\n"
            "MAX PAYOUT (CENTS): 100\n"
            "IMPLIED PROBABILITY: [Pre-computed %]\n"
            "EXPLANATION: [Mentor-style justification factoring in performance history and current edge]\n"
            "---------------------------------------"
        )

    def run_cycle(self, target_ticker="KXBTC15M-26SEP112215-15"):
        print(f"[*] Starting Kalshi Autonomous Pipeline Pulse for {target_ticker}...")

        # 0. Background Reconcile Settlements & Balance
        settlements = get_kalshi_settlements()
        if settlements:
            self.memory.reconcile_outcomes(settlements)

        portfolio_balance = get_kalshi_balance()
        balance_str = f"${portfolio_balance['balance_dollars']} (Available)" if portfolio_balance else "Balance Unavailable"
        performance_summary = self.memory.get_performance_summary()

        print(f"[*] Portfolio Status -> Buying Power: {balance_str} | Performance: {performance_summary}")

        # 1. Programmatic Perception
        snapshot = get_kalshi_market_snapshot(target_ticker)
        if not snapshot:
            return "Pipeline Error: Kalshi market data retrieval failed."

        # Record pulse into rolling history and calculate momentum
        self.memory.record_pulse(target_ticker, snapshot['yes_price'], snapshot['no_price'])
        trend_analysis = self.memory.get_trend_analysis()
        audit_history = self.memory.get_audit_history_string()

        # 2. Context Injection
        prompt = f"""
        [ACCOUNT PORTFOLIO STATUS]
        Available Balance: {balance_str}

        [AGENT PERFORMANCE TRACK RECORD]
        Metrics: {performance_summary}
        Recent Audit History:
        {audit_history}

        [MARKET TREND & VELOCITY VECTOR]
        {trend_analysis}

        [KALSHI MARKET SNAPSHOT: BINARY CONTRACTS]
        Ticker: {snapshot['ticker']} | Title: {snapshot['title']}
        Current Yes Ask: {snapshot['yes_price']}垄 | Current No Ask: {snapshot['no_price']}垄 | Last: {snapshot['last_price']}垄

        [LIVE NEWS CONTEXT]
        {json.dumps(snapshot['news_sentiment'], indent=2)}

        [PRE-COMPUTED CONTRACT SETUP]
        {snapshot['contract_setup']}

        TASK: Deliberate inside <thinking>...</thinking> tags, factoring in historical moving averages, price momentum, success rates, and capital limits. Output ONLY the KALSHI SETUP NOTIFICATION CARD.
        """

        conversation = [
            {"role": "system", "content": self.system_instructions},
            {"role": "user", "content": prompt}
        ]

        # 3. Single-Shot Inference
        print("[*] Kalshi Trinity Reasoning Phase...")
        try:
            response = self.llm.create_chat_completion(
                messages=conversation,
                temperature=0.1,
                max_tokens=4096,
                stop=["</thought>", "</s>"]
            )
            reply = response['choices'][0]['message']['content']

            # 4. Extract and print internal voice
            thought_match = re.search(r'<thinking>(.*?)</thinking>', reply, re.DOTALL)
            if thought_match:
                print(f"\n[Trinity Thought]: {thought_match.group(1).strip().replace(chr(10), ' ')}")

            # 5. Clean verdict extraction
            clean_verdict = re.sub(r'<thinking>.*?</thinking>', '', reply, flags=re.DOTALL).strip()
            clean_verdict = re.sub(r'</?thinking>', '', clean_verdict).strip()

            # 6. Initial Log Entry (Pending User Approval)
            side_match = re.search(r'RECOMMENDED SIDE:\s*(YES|NO)', clean_verdict, re.IGNORECASE)
            price_match = re.search(r'ENTRY COST \(CENTS\):\s*(\d+)', clean_verdict)
            if side_match and price_match:
                self.memory.log_trade_decision(
                    ticker=snapshot['ticker'],
                    recommended_side=side_match.group(1).upper(),
                    price_cents=int(price_match.group(1)),
                    status="PENDING_USER_APPROVAL"
                )

            return clean_verdict
        except Exception as e:
            return f"Inference Error: {e}"

# ================================================================================================
# MAIN ORCHESTRATION
# ================================================================================================

async def run_autonomous_pipeline(agent_instance):
    logger.info("Kalshi Autonomous Pipeline Engine Active (Performance Tracking Enabled).")
    active_ticker = "KXBTC15M-26SEP112215-15"
    while True:
        try:
            print(f"\n[!] KALSHI TRINITY PIPELINE CYCLE: {datetime.now().strftime('%H:%M:%S')}")
            verdict = agent_instance.run_cycle(active_ticker)
            print(f"\n[Autonomous Output]:\n{verdict}\n" + "-" * 80)

            # --- INTERACTIVE EXECUTION GATE ---
            match = re.search(r'RECOMMENDED SIDE:\s*(YES|NO)', verdict, re.IGNORECASE)
            if match:
                recommended_side = match.group(1).upper()
                if recommended_side in ["YES", "NO"]:
                    choice = input(f"\n[?] Trinity recommends taking a **{recommended_side}** position. Execute order? (y/n): ").strip().lower()
                    if choice == 'y':
                        price_match = re.search(r'ENTRY COST \(CENTS\):\s*(\d+)', verdict)
                        price_cents = int(price_match.group(1)) if price_match else 50

                        current_bal = get_kalshi_balance()
                        if current_bal and current_bal["balance_cents"] >= price_cents:
                            success = execute_kalshi_trade(active_ticker, recommended_side, count=1, price_cents=price_cents)
                            if success:
                                agent_instance.memory.update_latest_trade_status(active_ticker, "APPROVED_EXECUTED")
                            else:
                                agent_instance.memory.update_latest_trade_status(active_ticker, "EXECUTION_FAILED")
                        else:
                            logger.error("Trade aborted: Insufficient available funds in Kalshi balance.")
                            print("[!] Order blocked locally due to insufficient capital balance.")
                            agent_instance.memory.update_latest_trade_status(active_ticker, "DENIED_INSUFFICIENT_FUNDS")
                    else:
                        print("[*] Trade execution skipped by user.")
                        agent_instance.memory.update_latest_trade_status(active_ticker, "DENIED_BY_USER")

            await asyncio.sleep(900)
        except Exception as e:
            logger.error(f"Pipeline Loop Error: {e}")
            await asyncio.sleep(60)

async def main():
    gguf_path = "C:/ai_models/microsoft_Phi-4-mini-instruct-Q4_K_M.gguf"
    try:
        agent = QuantAgentKalshiTrinity(model_path=gguf_path)
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
