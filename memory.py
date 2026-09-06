import json
import os
from datetime import datetime

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
            except json.JSONDecodeError:
                pass
        return {"notes": {}, "history": []}

    def save_memory(self):
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def save_market_memory(self, inst_id: str, market_state: str, support_level: float, resistance_level: float):
        memory_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "instrument": inst_id,
            "market_state": market_state,
            "support": support_level,
            "resistance": resistance_level
        }
        self.data["history"].append(memory_entry)
        self.data["history"] = self.data["history"][-10:] # Keep last 10
        self.save_memory()
        return f"Successfully committed memory state for {inst_id} to disk."

    def get_recent_history(self):
        return json.dumps(self.data["history"], indent=2)


class ScratchAgent:
    """Main agent class that handles loop execution and takes memory as an optional dependency."""
    def __init__(self, model_name="phi4-mini", memory_manager=None):
        self.model_name = model_name
        self.memory = memory_manager  # <--- Plug memory manager in here!
        self.conversation_history = [
            {"role": "system", "content": "You are an autonomous Python quantitative trading data analysis agent..."}
        ]
        self.tools = {}

    def run_step(self, user_input):
        """Single turn perception -> reasoning -> action loop with auto-memory logging."""
        self.conversation_history.append({"role": "user", "content": user_input})
        response = self.llm_call(self.conversation_history)
        self.conversation_history.append({"role": "assistant", "content": response})

        tool_output = self.execute_tool_call(response)

        if "Error:" not in tool_output and "not valid JSON" not in tool_output:
            self.conversation_history.append({
                "role": "system",
                "content": f"Here is the live market data retrieved from the tool:\n{tool_output}\nNow, provide a professional qualitative breakdown."
            })

            final_response = self.llm_call(self.conversation_history)
            self.conversation_history.append({"role": "assistant", "content": final_response})

            # --- AUTOMATED MEMORY HOOK ---
            if self.memory:
                try:
                    data = json.loads(tool_output)
                    inst = data.get("instrument", "BTC-USD")
                    last_price = float(data.get("last_price", 0.0))
                    high_24h = float(data.get("high_24h", 0.0))
                    low_24h = float(data.get("low_24h", 0.0))

                    market_state = f"Trading at {last_price}, 24h High: {high_24h}, 24h Low: {low_24h}"

                    self.memory.save_market_memory(
                        inst_id=inst,
                        market_state=market_state,
                        support_level=low_24h,
                        resistance_level=high_24h
                    )
                    print("[*] Memory successfully committed to disk.")
                except Exception as e:
                    print(f"[!] Warning: Failed to auto-commit memory: {str(e)}")
            # -----------------------------

            return final_response

        return response

    def llm_call(self, messages):
        # (Ollama call logic...)
        pass

    def execute_tool_call(self, response_text):
        # (Tool parser logic...)
        pass

if __name__ == "__main__":
    my_memory = AgentMemory("agent_memory.json")
    agent = ScratchAgent(memory_manager=my_memory)

    # Now every run_step will automatically log market state to my_memory!

