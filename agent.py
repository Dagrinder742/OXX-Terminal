import json
import urllib.request
import subprocess
import os
import requests
from ollama import chat

OKX_REST_HOST = "https://us.okx.com"

class ScratchAgent:
    def __init__(self, model_name="phi4-mini"):
        self.model_name = model_name
        self.conversation_history = [
            {"role": "system", "content": (
                "You are an autonomous Python quantitative trading data analysis agent for OXX Terminal. "
                "Your role is strictly analytical: you study live OKX V5 telemetry, market mechanics, "
                "candle structures, and order book behavior to deliver deep structural insights. "
                "You do not execute live orders; you serve as the analytical reasoning and research layer. "
                "When you need to fetch data, respond ONLY with a valid JSON block using this exact schema:\n"
                "{\n  \"tool_name\": \"name_of_tool\",\n  \"arguments\": {\"arg_name\": \"value\"}\n}\n"
                "Do not include conversational filler or markdown explanations when invoking tools."
            )}
        ]
        self.tools = {}

    def register_tool(self, name, func, description):
        """Register a Python function as an executable tool for the agent."""
        self.tools[name] = {
            "function": func,
            "description": description
        }

    def run_step(self, user_input):
        """Single turn perception -> reasoning -> action loop."""
        self.conversation_history.append({"role": "user", "content": user_input})
        response = self.llm_call(self.conversation_history)
        self.conversation_history.append({"role": "assistant", "content": response})

        # Try to execute tool call
        tool_output = self.execute_tool_call(response)

        if "Error:" not in tool_output and "not valid JSON" not in tool_output:
            self.conversation_history.append({"role": "system", "content": f"Here is the live market data retrieved from the tool:\n{tool_output}\nNow, provide a professional qualitative breakdown and market state analysis based on this data without outputting any more tool calls."})

            final_response = self.llm_call(self.conversation_history)
            self.conversation_history.append({"role": "assistant", "content": final_response})
            return final_response

        return response

    def execute_tool_call(self, response_text):
        """Parse agent JSON output and execute the corresponding registered tool."""
        try:
            clean_json = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            tool_name = data.get("tool_name")
            args = data.get("arguments", {})

            # Flexible mapping aliases for tool names
            if tool_name in ["trade_signals_ledger", "read_ledger"]:
                tool_name = "read_trade_ledger"
            elif tool_name in ["getLiveMarketTicker", "fetch_ticker", "get_ticker", "market_ticker"]:
                tool_name = "fetch_okx_ticker"
            elif tool_name in ["getLiveMarketCandles", "fetch_candles", "market_candles"]:
                tool_name = "fetch_okx_candles"

            if "symbol" in args and "inst_id" not in args:
                args["inst_id"] = args.pop("symbol")

            # --- UNIVERSAL SYMBOL CLEANER ---
            if "inst_id" in args:
                raw_inst = str(args["inst_id"]).upper().strip()
                cleaned = raw_inst.replace("/", "").replace("\\", "").replace(" ", "")

                if "-" not in cleaned:
                    if cleaned.endswith("USDT"):
                        args["inst_id"] = cleaned[:-4] + "-USDT"
                    elif cleaned.endswith("USD"):
                        args["inst_id"] = cleaned[:-3] + "-USD"
                    elif cleaned.endswith("BTC"):
                        args["inst_id"] = cleaned[:-3] + "-BTC"
                    else:
                        args["inst_id"] = cleaned
                else:
                    args["inst_id"] = cleaned
            # --------------------------------

            if tool_name in self.tools:
                print(f"[*] Executing tool: {tool_name} with args: {args}")
                return self.tools[tool_name]["function"](**args)
            else:
                return f"Error: Tool '{tool_name}' not found."
        except json.JSONDecodeError:
            return "Response was not valid JSON; treating as plain text response."

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

# --- REGISTERED LIVE OKX TOOLS ---

def fetch_okx_ticker(inst_id: str = "BTC-USD"):
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

def fetch_okx_candles(inst_id: str = "BTC-USD", bar: str = "1H", limit: int = 10):
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

if __name__ == "__main__":
    print("[*] Initializing Live OKX-Integrated Agent with phi4-mini...")

    agent = ScratchAgent()

    # Register live tools
    agent.register_tool("fetch_okx_ticker", fetch_okx_ticker, "Fetches real-time ticker stats for an instrument like BTC-USD from OKX.")
    agent.register_tool("fetch_okx_candles", fetch_okx_candles, "Fetches recent OHLCV candles for an instrument and timeframe from OKX.")
    agent.register_tool("read_trade_ledger", read_trade_ledger, "Reads recent entries from trade_signals_ledger.md.")

    # Test prompt requesting live market investigation
    prompt = "Check the live OKX market ticker for BTC-USD and give me a professional breakdown of its current price position and market state."
    print(f"\n[*] Sending Prompt to Agent: {prompt}\n")

    reply = agent.run_step(prompt)
    print(f"\n[Agent Response Final]:\n{reply}")
