import subprocess
import sys
import traceback

class AICodingAgent:
    def __init__(self):
        self.memory = []  # Stores reasoning steps and code history

    def think(self, task_description):
        """
        Simulate AI reasoning for coding tasks.
        """
        reasoning = f"Analyzing task: {task_description}\n"
        reasoning += "Step 1: Understand requirements.\n"
        reasoning += "Step 2: Plan code structure.\n"
        reasoning += "Step 3: Write and validate code.\n"
        self.memory.append(reasoning)
        return reasoning

    def generate_code(self, task_description):
        """
        Generate Python code based on the task.
        For demo purposes, we'll handle a simple example.
        """
        if "hello world" in task_description.lower():
            code = 'print("Hello, World!")'
        else:
            code = (
                'print("Task not recognized. Please refine description.")'
            )
        self.memory.append(f"Generated code:\n{code}")
        return code

    def execute_code(self, code):
        """
        Execute generated Python code safely.
        """
        try:
            exec(code, {})
            self.memory.append("Execution successful.")
        except Exception as e:
            self.memory.append(f"Execution failed: {e}")
            traceback.print_exc()

    def execute_terminal_command(self, command):
        """
        Execute a terminal command safely.
        """
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True
            )
            self.memory.append(f"Terminal output:\n{result.stdout}")
            if result.stderr:
                self.memory.append(f"Terminal error:\n{result.stderr}")
            return result.stdout.strip()
        except Exception as e:
            self.memory.append(f"Terminal execution failed: {e}")
            traceback.print_exc()
            return None

    def show_memory(self):
        """
        Display the AI's thought process and history.
        """
        print("\n=== AI Thought Process ===")
        for step in self.memory:
            print(step)


if __name__ == "__main__":
    agent = AICodingAgent()

    # Example: AI reasoning
    reasoning = agent.think("Create a Hello World program in Python")
    print(reasoning)

    # Generate code
    code = agent.generate_code("Hello World program")
    print("\nGenerated Code:\n", code)

    # Execute code
    agent.execute_code(code)

    # Execute a safe terminal command
    terminal_output = agent.execute_terminal_command("echo AI Terminal Test")
    print("\nTerminal Output:", terminal_output)

    # Show AI's internal thought process
    agent.show_memory()
