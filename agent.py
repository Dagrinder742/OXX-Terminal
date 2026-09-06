import json
import urllib.request
import subprocess
import os
from ollama import chat

class ScratchAgent:
    def __init__(self, model_name="phi4-mini"):
        self.model_name = model_name
        self.conversation_history = [
            {"role": "system", "content": (
                "You are an autonomous Python quantitative trading agent for OXX Terminal. "
                "OXX Terminal is a custom Python TUI application driven by analytics and automated engines. "
                "You have access to local registered tools. When you need to execute a tool, "
                "respond ONLY with a valid JSON block using this exact schema:\n"
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

        # If a tool was successfully executed, feed the output back to the model for final analysis
        if "Error:" not in tool_output and "not valid JSON" not in tool_output:
            self.conversation_history.append({"role": "system", "content": f"Tool Execution Result:\n{tool_output}"})
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

            # Flexible mapping if the model short-names the tool
            if tool_name == "trade_signals_ledger":
                tool_name = "read_trade_ledger"

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

# --- REGISTERED AGENT TOOLS ---

def run_terminal_command(command: str):
    """Executes a safe terminal command and returns output."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        return str(e)

def read_trade_ledger(lines: int = 30):
    """Reads the latest entries from the trade signals ledger markdown file."""
    ledger_path = "trade_signals_ledger.md"
    if not os.path.exists(ledger_path):
        return "Ledger file (trade_signals_ledger.md) not found yet. Run analytics engine first."
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            content = f.readlines()
        # Return the tail end of the ledger for recent context
        return "".join(content[-lines:])
    except Exception as e:
        return f"Error reading ledger: {str(e)}"

if __name__ == "__main__":
    print("[*] Initializing Upgraded OXX Quantitative Agent with phi4-mini...")

    agent = ScratchAgent()

    # Register tools
    agent.register_tool("system_check", lambda: "OXX Terminal TUI Core: ONLINE | Model: phi4-mini", "Performs quick system check.")
    agent.register_tool("run_terminal_command", run_terminal_command, "Executes a shell command.")
    agent.register_tool("read_trade_ledger", read_trade_ledger, "Reads the recent history of trade signals and telemetry logs from trade_signals_ledger.md.")

    # Test prompt inviting the agent to read your market history
    prompt = "Please check our trade signals ledger to see what setups have recently fired and give me a brief narrative study of the market action."
    print(f"\n[*] Sending Prompt to Agent: {prompt}\n")

    reply = agent.run_step(prompt)
    print(f"\n[Agent Response Final]:\n{reply}")
