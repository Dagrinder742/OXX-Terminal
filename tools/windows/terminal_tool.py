# terminal_tool.py
import subprocess

def run_shell_command(command: str, timeout: int = 15) -> dict:
    """
    Executes a shell command safely with a strict timeout and returns 
    a structured dictionary containing exit codes, stdout, and stderr.
    """
    # Optional safety filter to block obviously catastrophic commands
    blocked_keywords = ["rm -rf /", ":(){ :|:& };:", "mkfs", "dd if=/dev/zero"]
    if any(keyword in command for keyword in blocked_keywords):
        return {
            "success": False,
            "stdout": "",
            "stderr": "SECURITY ERROR: Command blocked by safety filter."
        }

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Error: Command timed out after {timeout} seconds."
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e)
        }

