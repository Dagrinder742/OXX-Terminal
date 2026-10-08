import subprocess
import sys
import os

# Configuration paths for local Termux environment
MODEL_PATH = "/data/data/com.termux/files/home/trinity_master/vault/models/llama-3.2-1b.Q4_K_M.gguf"
PROJECT_DIR = "/data/data/com.termux/files/home/OKX-Terminal/project"

def run_local_prompt(step_filename):
    prompt_path = os.path.join(PROJECT_DIR, step_filename)
    
    if not os.path.exists(prompt_path):
        print(f"[-] Error: Prompt file not found at {prompt_path}")
        return

    print(f"[*] Ingesting prompt from: {step_filename}")
    
    # Construct llama-cli command using the file flag (-f)
    cmd = [
        "llama-cli",
        "-m", MODEL_PATH,
        "--color", "on",
        "-c", "16384",
        "-n", "-1",
        "-f", prompt_path
    ]

    try:
        # Execute subprocess streaming output in real-time
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(line, end="")
        process.wait()
    except Exception as e:
        print(f"[-] Execution failed: {e}")

if __name__ == "__main__":
    target_step = sys.argv[1] if len(sys.argv) > 1 else "step1_resilience.txt"
    run_local_prompt(target_step)
