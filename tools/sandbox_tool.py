#!/usr/bin/env python3
"""
sandbox_tool.py - lets a local GGUF model run a small allowlist of terminal
commands and secure file modification tools inside one sandbox directory.
"""
import glob
import json
import os
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

SANDBOX = Path(os.environ.get(
    "SANDBOX_DIR", "/data/data/com.termux/files/home/OKX-Terminal/tools")).resolve()
TIMEOUT_S = 300
MAX_OUTPUT = 8000
MAX_GLOB = 200
ALLOW_SED_INPLACE = True

_F = "flag"
_V = "value"
_P = "pattern"
_I = "inplace"

_HEADTAIL = {"lines": _V, "bytes": _V, "quiet": _F, "silent": _F, "verbose": _F}

POLICY = {
    "cat": dict(pattern=False, short_val="", pattern_short="", short_deny="",
                long={k: _F for k in (
                    "number", "number-nonblank", "show-all", "show-ends",
                    "show-tabs", "squeeze-blank", "show-nonprinting")}),
    "ls": dict(pattern=False, short_val="", pattern_short="", short_deny="",
               long={k: _F for k in (
                   "all", "almost-all", "human-readable", "recursive", "reverse",
                   "size", "classify", "directory", "color",
                   "group-directories-first")}),
    "wc": dict(pattern=False, short_val="", pattern_short="", short_deny="",
               long={k: _F for k in (
                   "lines", "words", "bytes", "chars", "max-line-length")}),
    "head": dict(pattern=False, short_val="nc", pattern_short="", short_deny="",
                 long=dict(_HEADTAIL)),
    "tail": dict(pattern=False, short_val="nc", pattern_short="", short_deny="fF",
                 long=dict(_HEADTAIL)),
    "grep": dict(pattern=True, short_val="ABCmdDeX", pattern_short="e",
                 short_deny="fR",
                 long={
                     "regexp": _P, "max-count": _V, "after-context": _V,
                     "before-context": _V, "context": _V, "binary-files": _V,
                     "devices": _V, "directories": _V, "include": _V,
                     "exclude": _V, "exclude-dir": _V,
                     **{k: _F for k in (
                         "line-number", "recursive", "ignore-case", "invert-match",
                         "count", "files-with-matches", "files-without-match",
                         "only-matching", "word-regexp", "line-regexp",
                         "fixed-strings", "extended-regexp", "perl-regexp",
                         "basic-regexp", "no-filename", "with-filename", "quiet",
                         "no-messages", "text", "color", "colour")}}),
    "sed": dict(pattern=True, short_val="el", pattern_short="e", short_deny="f",
                long={"expression": _P, "line-length": _V, "in-place": _I,
                      **{k: _F for k in (
                          "quiet", "silent", "regexp-extended", "separate",
                          "null-data", "posix", "unbuffered")}}),
}
SHELL_TOKENS = {"|", "||", "&", "&&", ";", ">", ">>", "<", "<<", "2>", "2>&1"}


class Refused(Exception):
    pass


def _inside(p: str) -> bool:
    real = Path(os.path.realpath(SANDBOX / p))
    return real == SANDBOX or SANDBOX in real.parents


def _check_path(p: str):
    if not _inside(p):
        raise Refused(f"path outside sandbox: {p}")


def log_to_index(filename: str, action: str):
    """Logs created or modified files to the tracking index per user specifications."""
    try:
        index_path = SANDBOX / "file_index.txt"
        existing = index_path.read_text().splitlines() if index_path.exists() else []
        entry = f"{filename} ({action})"
        if entry not in existing:
            existing.append(entry)
            index_path.write_text("\n".join(existing) + "\n")
    except Exception:
        pass


def cmd_read_file(path_str: str, start: int = 1, count: int = 40) -> str:
    # 40 lines keeps prompt evaluation fast on ARM CPU
    """Safe built-in tool to read a file with line numbers and optional range slicing."""
    try:
        _check_path(path_str)
        target = SANDBOX / path_str
        if not target.exists():
            return f"REFUSED: file does not exist: {path_str}"

        lines = target.read_text().splitlines()
        total_lines = len(lines)

        start_idx = max(0, start - 1)
        end_idx = min(total_lines, start_idx + count)
        selected = lines[start_idx:end_idx]

        formatted = [f"{idx:4d} | {line}" for idx, line in enumerate(selected, start=start_idx + 1)]
        header = f"[file: {path_str} | lines {start_idx + 1}-{end_idx} of {total_lines}]"
        return header + "\n" + "\n".join(formatted)
    except Refused as e:
        return f"REFUSED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def cmd_write_file(path_str: str, content: str) -> str:
    """Safe built-in tool to write or create a new file inside the sandbox."""
    try:
        _check_path(path_str)
        target = SANDBOX / path_str
        target.parent.mkdir(parents=True, exist_ok=True)
        # Unescape literal newlines if passed in string format
        decoded_content = content.replace("\\n", "\n")
        target.write_text(decoded_content)
        log_to_index(path_str, "created")
        return f"[exit 0]\nSuccessfully wrote {path_str}"
    except Refused as e:
        return f"REFUSED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def cmd_patch_file(path_str: str, search_text: str, replace_text: str) -> str:
    """Safe built-in tool to patch an existing file via unique search/replace blocks."""
    try:
        _check_path(path_str)
        target = SANDBOX / path_str
        if not target.exists():
            return f"REFUSED: file does not exist: {path_str}"
        content = target.read_text()

        decoded_search = search_text.replace("\\n", "\n")
        decoded_replace = replace_text.replace("\\n", "\n")

        if decoded_search not in content:
            return f"REFUSED: search text not found in {path_str}"
        if content.count(decoded_search) > 1:
            return f"REFUSED: search text is not unique in {path_str}"

        new_content = content.replace(decoded_search, decoded_replace)
        target.write_text(new_content)
        log_to_index(path_str, "patched")
        return f"[exit 0]\nSuccessfully patched {path_str}"
    except Refused as e:
        return f"REFUSED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def _expand_paths(a: str) -> list[str]:
    if any(c in a for c in "*?["):
        matches = sorted(glob.glob(a, root_dir=SANDBOX))[:MAX_GLOB]
        if matches:
            for m in matches:
                _check_path(m)
            return matches
    _check_path(a)
    return [a]


def _resolve_long(name: str, table: dict) -> str:
    if name in table:
        return name
    hits = [k for k in table if name and k.startswith(name)]
    if len(hits) == 1:
        return hits[0]
    raise Refused(f"unsupported or ambiguous flag: --{name}")


def validate(argv: list[str]) -> list[str]:
    if not argv:
        raise Refused("empty command")
    cmd, args = argv[0], argv[1:]
    if cmd not in POLICY:
        raise Refused(f"command not allowed: {cmd} (allowed: {', '.join(POLICY)}, read_file, write_file, patch_file)")
    pol = POLICY[cmd]
    for a in args:
        if a in SHELL_TOKENS:
            raise Refused("no pipes/redirects/chaining; run one command at a time")

    need_pattern = pol["pattern"]
    out, i, dashdash = [], 0, False
    while i < len(args):
        a = args[i]
        i += 1
        if not dashdash and a == "--":
            dashdash = True
            out.append(a)
            continue
        if not dashdash and a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            key = _resolve_long(name, pol["long"])
            kind = pol["long"][key]
            if kind == _I and not ALLOW_SED_INPLACE:
                raise Refused("sed in-place editing is disabled")
            if kind in (_F, _I):
                out.append(f"--{key}{eq}{val}")
            else:
                if not eq:
                    if i >= len(args):
                        raise Refused(f"--{key} needs a value")
                    val = args[i]
                    i += 1
                out.append(f"--{key}={val}")
                if kind == _P:
                    need_pattern = False
            continue
        if not dashdash and a.startswith("-") and a != "-":
            chars, extra = a[1:], []
            for idx, ch in enumerate(chars):
                if ch in pol["short_deny"]:
                    raise Refused(f"flag not allowed: -{ch}")
                if cmd == "sed" and ch == "i":
                    if not ALLOW_SED_INPLACE:
                        raise Refused("sed in-place editing is disabled")
                    break
                if ch in pol["short_val"]:
                    if ch in pol["pattern_short"]:
                        need_pattern = False
                    if idx == len(chars) - 1:
                        if i >= len(args):
                            raise Refused(f"-{ch} needs a value")
                        extra.append(args[i])
                        i += 1
                    break
            out.append(a)
            out.extend(extra)
            continue
        if need_pattern:
            need_pattern = False
            out.append(a)
            continue
        out.extend(_expand_paths(a))

    if cmd == "sed":
        out.insert(0, "--sandbox")
    return [cmd] + out


def run(command: str) -> str:
    """Tool entry point. Intercepts custom built-ins or runs whitelisted CLI commands."""
    try:
        parts = shlex.split(command)
        if not parts:
            return "REFUSED: empty command"

        cmd = parts[0]

        # Intercept custom built-in file reading/writing/patching tools
        if cmd == "read_file":
            parts_len = len(parts)
            path = parts[1] if parts_len > 1 else ""
            try:
                start = int(parts[2]) if parts_len > 2 else 1
            except ValueError:
                start = 1
            try:
                count = int(parts[3]) if parts_len > 3 else 150
            except ValueError:
                count = 150
            return cmd_read_file(path, start, count)
        elif cmd == "write_file":
            if len(parts) < 3:
                return "REFUSED: write_file requires <path> and <content>"
            return cmd_write_file(parts[1], " ".join(parts[2:]))
        elif cmd == "patch_file":
            if len(parts) < 4:
                return "REFUSED: patch_file requires <path> <search> <replace>"
            return cmd_patch_file(parts[1], parts[2], parts[3])

        # Otherwise validate and run standard whitelisted CLI tool
        argv = validate(parts)
    except (Refused, ValueError) as e:
        return f"REFUSED: {e}"

    try:
        r = subprocess.run(
            argv, cwd=SANDBOX, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=TIMEOUT_S,
            env={"PATH": "/data/data/com.termux/files/usr/bin:/usr/bin:/bin",
                 "HOME": str(SANDBOX), "LC_ALL": "C.UTF-8"},
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: timed out after {TIMEOUT_S}s"
    except FileNotFoundError:
        return f"ERROR: {argv[0]} not installed"
    text = (r.stdout + r.stderr) or "(no output)"
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n...[truncated at {MAX_OUTPUT} chars]"
    return f"[exit {r.returncode}]\n{text}"


# ---------------------------------------------------------------- agent loop
SYSTEM = """You are a coding assistant with restricted terminal and file tools.
To use them, reply with exactly one line: CMD: <command>
Allowed commands & tools:
- read_file <path> [start_line] [count] (reads a file with line numbers)
- write_file <path> <content> (creates/overwrites a file, use \\n for newlines)
- patch_file <path> <search_string> <replace_string> (modifies existing files)
  IMPORTANT: search_string must include 2-3 surrounding lines to guarantee uniqueness!
- cat, grep, sed, ls, head, tail, wc (standard CLI tools)
One command per turn. No pipes or redirects. Paths are relative to sandbox root.
When done, reply with: DONE: <answer>"""

MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF"


def ask_model(msgs) -> str:
    # Context Pruning: Keep only the latest tool output at full size,
    # and truncate older tool outputs to save precious context tokens.
    trimmed_msgs = []
    total_msgs = len(msgs)

    for idx, (role, content) in enumerate(msgs):
        # Check if this is an older user message containing tool output
        if role == "user" and "Here is the output from running" in content and idx < total_msgs - 2:
            # Grab just the first line (e.g., the file header) as a mini summary
            first_line = content.splitlines()[0] if content.splitlines() else "tool output"
            trimmed_msgs.append((role, f"{first_line}\n[older tool output truncated for context efficiency]"))
        else:
            trimmed_msgs.append((role, content))

    formatted_messages = [
        {"role": role, "content": content} for role, content in trimmed_msgs
    ]

    payload = {
        "model": MODEL,
        "messages": formatted_messages,
        "temperature": 0.2,
        "max_tokens": 1024
    }

    req = urllib.request.Request(
        "http://localhost:8080/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content = res_data["choices"][0]["message"]["content"]
            return content.strip()
    except Exception as e:
        return f"ERROR: Failed to connect to local llama-server: {e}"

def agent(task: str, max_steps: int = 6) -> str:
    msgs = [("system", SYSTEM), ("user", task)]
    consecutive_failures = 0
    last_command = None

    for step in range(max_steps):
        reply = ask_model(msgs)
        msgs.append(("assistant", reply))
        print(f"model> {reply}")

        line = next((l for l in reply.splitlines()
                     if l.startswith(("CMD:", "DONE:"))), "")
        if line.startswith("DONE:"):
            return line[5:].strip()

        if not line.startswith("CMD:"):
            msgs.append(("user", "Reply with 'CMD: <command>' or 'DONE: <answer>'."))
            continue

        cmd = line[4:].strip()

        if cmd == last_command:
            consecutive_failures += 1
        else:
            consecutive_failures = 0
            last_command = cmd

        result = run(cmd)
        print(f"tool>  {result[:300]}")

        if result.startswith(("REFUSED:", "ERROR:")):
            consecutive_failures += 1

        if consecutive_failures >= 3:
            return "(stopped: aborted due to consecutive failures)"

        msgs.append(("user", f"Here is the output from running '{cmd}':\n{result}"))

    return "(stopped: step limit reached)"


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--agent":
        print("final>", agent(" ".join(sys.argv[2:])))
    elif len(sys.argv) >= 2:
        print(run(" ".join(sys.argv[1:])))
    else:
        print(__doc__)

