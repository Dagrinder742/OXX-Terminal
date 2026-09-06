import json
import urllib.request
import subprocess
import sys
from ollama import chat

class ScratchAgent:
    def __init__(self, model_name="phi4-mini"):
        self.model_name = model_name
        self.conversation_history = [
            {"role": "system", "content": (
                "You are an autonomous Python quantitative trading agent for OXX Terminal. "
                "OXX Terminal is a custom Python TUI application driven by main.py. "
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

        # Automatically try to execute if it's a tool call
        tool_output = self.execute_tool_call(response)
        if "not valid JSON" not in tool_output and "Error:" not in tool_output:
            return f"Tool Output: {tool_output}"
        return response

    def execute_tool_call(self, response_text):
        """Parse agent JSON output and execute the corresponding registered tool."""
        try:
            clean_json = response_text.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            tool_name = data.get("tool_name")
            args = data.get("arguments", {})

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

def run_terminal_command(command: str):
    """Executes a safe terminal command and returns output."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        return str(e)

def test_direct_ollama():
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": "phi4-mini",
        "messages": [{"role": "user", "content": "System check: respond with OK."}],
        "stream": False
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

    print("[*] Sending direct POST request to local Ollama server...")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
            print(f"[Direct Success]: {result['message']['content']}")
    except Exception as e:
        print(f"[-] Direct request failed: {e}")

if __name__ == "__main__":
    print("[*] Initializing ScratchAgent with phi4-mini...")
    test_direct_ollama()

    agent = ScratchAgent()
    agent.register_tool("run_terminal_command", run_terminal_command, "Executes a shell command.")

    reply = agent.run_step("Give me a quick system check for OXX Terminal.")
    print(f"[Agent Response]: {reply}")
