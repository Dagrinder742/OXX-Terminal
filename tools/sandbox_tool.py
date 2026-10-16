#!/usr/bin/env python3
"""
sandbox_tool.py - lets a local GGUF model run a small allowlist of terminal
commands and secure file modification tools inside one sandbox directory.
"""
import os
import sys

# Defense in depth: when run as a script, don't let a file sitting next to it
# (e.g. a model-written json.py) shadow the stdlib modules imported below.
if (__name__ == "__main__" and sys.path
        and os.path.realpath(sys.path[0] or ".") == os.path.dirname(os.path.realpath(__file__))):
    sys.path.pop(0)

import ast
import glob
import io
import json
import re
import tokenize
import shlex
import subprocess
import urllib.request
from pathlib import Path

SANDBOX = Path(os.environ.get(
    "SANDBOX_DIR", "/data/data/com.termux/files/home/OKX-Terminal/tools")).resolve()
TIMEOUT_S = 300
MAX_OUTPUT = 8000
MAX_GLOB = 200
ALLOW_SED_INPLACE = True
PREVIEW_LINES = int(os.environ.get("PREVIEW_LINES", "15"))  # 0 = show everything
# Files the model may read but never modify (this script, if it lives in the sandbox).
PROTECTED = {Path(__file__).resolve()}

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


def _check_writable(p: str):
    _check_path(p)
    real = Path(os.path.realpath(SANDBOX / p))
    if real in PROTECTED:
        raise Refused(f"protected file, cannot modify: {p}")
    if "__pycache__" in real.parts:  # never let the model plant bytecode
        raise Refused(f"cannot write inside __pycache__: {p}")


def _fenced_block(body):
    """Text of the ``` block in `body`, or None if there is no block.

    The LAST closing fence ends the block, so file content may itself contain
    fences (markdown). An unclosed block means the reply was probably cut off by
    the token limit; refuse rather than write a truncated file."""
    lines = (body or "").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().startswith("```")), None)
    if start is None:
        return None
    end = next((i for i in range(len(lines) - 1, start, -1) if lines[i].strip() == "```"), None)
    if end is None:
        raise Refused("code block is not closed (reply may have been cut off); "
                      "write a shorter file or split it into parts")
    return "\n".join(lines[start + 1:end]) + "\n"


def _search_replace(body):
    """(search, replace) from a SEARCH/REPLACE block in `body`, or None if absent."""
    lines = (body or "").splitlines()
    top = next((i for i, l in enumerate(lines) if l.strip().startswith("<<<<<<<")), None)
    if top is None:
        return None
    mid = next((i for i in range(top + 1, len(lines)) if lines[i].rstrip() == "======="), None)
    end = None
    if mid is not None:
        end = next((i for i in range(mid + 1, len(lines)) if lines[i].strip().startswith(">>>>>>>")), None)
    if mid is None or end is None:
        raise Refused("malformed SEARCH/REPLACE block; expected <<<<<<< SEARCH, =======, >>>>>>> REPLACE")
    return "\n".join(lines[top + 1:mid]), "\n".join(lines[mid + 1:end])


MAX_CHECK_BYTES = 200_000
_PLACEHOLDER_RE = re.compile(r"\b(todo|fixme|placeholder)\b|implement\b.*\bhere\b", re.I)


def _is_stub(fn) -> bool:
    """True if a function body is only pass / ... / a docstring / raise NotImplementedError."""
    body = list(fn.body)
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if not body:
        return True  # docstring only
    if len(body) != 1:
        return False
    s = body[0]
    if isinstance(s, ast.Pass):
        return True
    if isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is Ellipsis:
        return True
    if isinstance(s, ast.Raise) and s.exc is not None:
        e = s.exc.func if isinstance(s.exc, ast.Call) else s.exc
        return isinstance(e, ast.Name) and e.id == "NotImplementedError"
    return False


def _arity(fn):
    """(min, max) positional args a method accepts after self; max None = unlimited."""
    a = fn.args
    pos = a.posonlyargs + a.args
    n = max(len(pos) - 1, 0)  # drop self
    required = max(len(pos) - len(a.defaults) - 1, 0)
    return required, (None if a.vararg else n)


def check_python(source: str) -> list[str]:
    """Static check only: the code is parsed, never executed. Returns problem lines.

    Catches syntax errors, stub bodies, placeholder comments, methods shadowed by
    self.<name> assignments, wrong argument counts on self.method() calls, and demo
    code that runs on import. It does NOT prove the program works."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        text = (e.text or "").strip()
        return [f"SYNTAX ERROR line {e.lineno}: {e.msg}" + (f"  -> {text}" if text else "")]

    problems = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_stub(node):
            problems.append((node.lineno, f"def {node.name}() has no real logic (only pass/.../docstring). Write the actual code."))

    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and _PLACEHOLDER_RE.search(tok.string):
                problems.append((tok.start[0], f"placeholder comment: {tok.string.strip()[:60]}"))
    except (tokenize.TokenError, IndentationError):
        pass

    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        methods = {m.name: m for m in cls.body
                   if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.decorator_list}
        for m in (m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if m.decorator_list or not m.args.args:
                continue
            me = m.args.args[0].arg
            for n in ast.walk(m):
                targets = []
                if isinstance(n, ast.Assign):
                    targets = n.targets
                elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
                    targets = [n.target]
                for t in targets:
                    if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                            and t.value.id == me and t.attr in methods):
                        problems.append((n.lineno, f"{me}.{t.attr} is assigned, but {t.attr}() is also a method of class "
                                         f"{cls.name}. This replaces the method, so calling {me}.{t.attr}() will fail. Use another name."))
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == me
                        and n.func.attr in methods
                        and not n.keywords and not any(isinstance(x, ast.Starred) for x in n.args)):
                    lo, hi = _arity(methods[n.func.attr])
                    got = len(n.args)
                    if got < lo or (hi is not None and got > hi):
                        want = f"{lo}" if lo == hi else f"{lo}-{hi if hi is not None else 'many'}"
                        problems.append((n.lineno, f"{me}.{n.func.attr}() called with {got} argument(s) but "
                                         f"def {n.func.attr} (line {methods[n.func.attr].lineno}) takes {want}."))

    # Module-like files (they define something) should not run demo calls on import.
    # A plain script with no defs, like print("hi"), is left alone.
    module_like = any(isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) for n in tree.body)
    for stmt in tree.body if module_like else []:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            problems.append((stmt.lineno, "this call runs when the file is imported. Put demo code under "
                             "if __name__ == \"__main__\":"))

    problems.sort(key=lambda p: p[0])
    seen, out = set(), []
    for ln, msg in problems:
        if (ln, msg) not in seen:
            seen.add((ln, msg))
            out.append(f"line {ln}: {msg}")
    return out


def format_check(problems: list[str]) -> str:
    if not problems:
        return ("[check] no problems found by the static check. "
                "The code was NOT executed, so this does not prove it runs correctly.")
    return (f"[check] {len(problems)} problem(s) found. Fix them with patch_file:\n"
            + "\n".join("  " + p for p in problems[:15]))


def cmd_check_file(path_str: str) -> str:
    """Static check of a .py file inside the sandbox. Never executes it."""
    try:
        _check_path(path_str)
        target = SANDBOX / path_str
        if target.suffix != ".py":
            return "REFUSED: check_file only checks .py files"
        if not target.is_file():
            return f"ERROR: no such file: {path_str}"
        if target.stat().st_size > MAX_CHECK_BYTES:
            return f"REFUSED: file larger than {MAX_CHECK_BYTES} bytes"
        return "[exit 0]\n" + format_check(check_python(target.read_text(errors="replace")))
    except Refused as e:
        return f"REFUSED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def _with_check(result: str, path_str: str) -> str:
    """Append the static check to a successful write/patch of a .py file."""
    if not result.startswith("[exit 0]") or not path_str.endswith(".py"):
        return result
    return result + "\n" + cmd_check_file(path_str).removeprefix("[exit 0]\n")


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
        if total_lines and start_idx >= total_lines:
            return f"ERROR: start line {start} is past the end of {path_str} ({total_lines} lines)"
        selected = lines[start_idx:start_idx + max(1, count)]

        # Cap by characters too, so a few very long lines can't flood the context.
        shown, used = [], 0
        for n, line in enumerate(selected, start=start_idx + 1):
            row = f"{n:4d} | {line}"[:MAX_OUTPUT]
            if shown and used + len(row) > MAX_OUTPUT:
                break
            shown.append(row)
            used += len(row) + 1
        end_idx = start_idx + len(shown)

        header = f"[file: {path_str} | lines {start_idx + 1}-{end_idx} of {total_lines}]"
        note = ""
        if end_idx < total_lines:
            note = (f"\n[{total_lines - end_idx} more lines not shown. "
                    f"To continue: read_file {path_str} {end_idx + 1} {count}]")
        return header + "\n" + "\n".join(shown) + note
    except Refused as e:
        return f"REFUSED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def cmd_write_file(path_str: str, content: str) -> str:
    """Safe built-in tool to write or create a new file inside the sandbox."""
    try:
        _check_writable(path_str)
        target = SANDBOX / path_str
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)  # written exactly as given: no unescaping
        log_to_index(path_str, "created")
        return f"[exit 0]\nSuccessfully wrote {path_str}"
    except Refused as e:
        return f"REFUSED: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def cmd_patch_file(path_str: str, search_text: str, replace_text: str) -> str:
    """Safe built-in tool to patch an existing file via unique search/replace blocks."""
    try:
        _check_writable(path_str)
        target = SANDBOX / path_str
        if not target.exists():
            return f"REFUSED: file does not exist: {path_str}"
        content = target.read_text()

        if not search_text:
            return "REFUSED: search text is empty"
        if search_text not in content:
            return f"REFUSED: search text not found in {path_str} (it must match exactly, including indentation)"
        if content.count(search_text) > 1:
            return f"REFUSED: search text is not unique in {path_str}; include more surrounding lines"

        new_content = content.replace(search_text, replace_text)
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
        raise Refused(f"command not allowed: {cmd} (allowed: {', '.join(POLICY)}, read_file, write_file, patch_file, check_file)")
    pol = POLICY[cmd]
    for a in args:
        if a in SHELL_TOKENS:
            raise Refused("no pipes/redirects/chaining; run one command at a time")

    need_pattern = pol["pattern"]
    out, i, dashdash = [], 0, False
    inplace, paths = False, []
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
            if kind == _I:
                inplace = True
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
                    inplace = True
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
        expanded = _expand_paths(a)
        paths.extend(expanded)
        out.extend(expanded)

    if inplace:
        for p in paths:
            _check_writable(p)
    if cmd == "sed":
        out.insert(0, "--sandbox")
    return [cmd] + out


def run(command: str, body: str = "") -> str:
    """Tool entry point. Intercepts custom built-ins or runs whitelisted CLI commands.

    `body` is the text that followed the CMD line in the model's reply. write_file
    takes its content from a ``` block in it and patch_file from a SEARCH/REPLACE
    block, so code never needs escaping."""
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
        elif cmd == "check_file":
            if len(parts) != 2:
                return "REFUSED: usage: check_file <path.py>"
            return cmd_check_file(parts[1])
        elif cmd == "write_file":
            if len(parts) < 2:
                return "REFUSED: write_file requires <path>"
            block = _fenced_block(body)
            if block is not None:
                return _with_check(cmd_write_file(parts[1], block), parts[1])
            inline = " ".join(parts[2:])
            if inline and "\\n" not in inline:  # short single-line content is fine inline
                return _with_check(cmd_write_file(parts[1], inline), parts[1])
            return ("REFUSED: no file contents received. The ``` block must come on the lines "
                    "AFTER the CMD line, not before it (no escaping needed)")
        elif cmd == "patch_file":
            if len(parts) < 2:
                return "REFUSED: patch_file requires <path>"
            sr = _search_replace(body)
            if sr is not None:
                return _with_check(cmd_patch_file(parts[1], sr[0], sr[1]), parts[1])
            if len(parts) >= 4 and "\\n" not in parts[2] + parts[3]:
                return _with_check(cmd_patch_file(parts[1], parts[2], parts[3]), parts[1])
            return ("REFUSED: no edit received. The SEARCH/REPLACE block must come on the lines "
                    "AFTER the CMD line, not before it:\n"
                    "<<<<<<< SEARCH\nold lines\n=======\nnew lines\n>>>>>>> REPLACE")

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
Every reply is an optional one-line note followed by ONE command:
NOTE: <one line: what you just learned (file + line numbers) or what you plan next>
CMD: <command>

Your NOTE lines are your memory. Old tool output is deleted to save space, but your
own replies are kept, so write every important finding into a NOTE.

Commands (paths are relative to the sandbox root, no pipes or redirects):
- read_file <path> [start_line] [count]   reads a file with line numbers
- cat, grep, sed, ls, head, tail, wc      standard tools
- write_file <path>   creates/overwrites a file. Put the whole file in a ``` block on
  the lines after the CMD line. Write code normally, no escaping.
- patch_file <path>   edits a file. Put a SEARCH/REPLACE block after the CMD line.
- check_file <path.py>   static check (syntax, stub bodies, shadowed methods, wrong
  argument counts). It never runs the code. It also runs automatically after every
  write_file/patch_file of a .py file: if it lists problems, fix them with patch_file
  before you reply DONE.

CODE RULES (when asked to write Python):
- Write real, working logic. Never leave 'pass', '...', or '# TODO' bodies unless the
  user asks for a skeleton.
- Use the names, fields and behaviours the task spells out. If it names a state dict,
  scoring rule or print messages, implement exactly those.
- Never give an attribute the same name as a method (self.score = ... next to def score).
- Put demo code under: if __name__ == "__main__":

Example of the STYLE wanted (real logic, state, computed score, printed steps).
Write code for the user's actual task, not this one:
CMD: write_file stock.py
```python
class Stock:
    def __init__(self):
        self.state = {"items": {}, "log": []}

    def load(self):
        self.state["items"] = {"bolts": 40, "nuts": 5, "screws": 12}
        print("load: items =", self.state["items"])

    def rank(self):
        ranked = sorted(self.state["items"].items(), key=lambda kv: kv[1])
        print("rank: lowest first =", ranked)
        return ranked

    def pick(self, ranked):
        name, qty = ranked[0]
        print("pick: reorder", name, "(only", qty, "left)")
        return name

    def run(self):
        for _ in range(2):
            self.load()
            choice = self.pick(self.rank())
            self.state["log"].append(choice)


if __name__ == "__main__":
    Stock().run()
```

Example write_file:
CMD: write_file hello.py
```python
print("hi\\n")
```

Example patch_file (SEARCH must match exactly and be unique: include 2-3 nearby lines):
CMD: patch_file hello.py
<<<<<<< SEARCH
print("hi\\n")
=======
print("hello\\n")
>>>>>>> REPLACE

If a file is longer than what you read, say which lines you reviewed and make no
claims about lines you have not seen (use the 'To continue' hint to read more).
When done, reply: DONE: <answer>   (build the answer from your NOTE lines)"""

MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF"
SERVER_URL = os.environ.get("LLAMA_URL", "http://localhost:8080/v1/chat/completions")


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
        SERVER_URL,
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

BLOCK_CMDS = ("write_file", "patch_file")


def parse_reply(reply: str):
    """Parse a model reply into (kind, text, body, notes).

    kind  'cmd' | 'done' | None
    text  the command line, or the full DONE answer (every line after the marker)
    body  lines after the CMD line (file content / SEARCH-REPLACE block), else ''
    notes the NOTE: lines. They are read before the marker; after a CMD line only
          for ordinary commands, so a 'NOTE:' inside file content is never a note.
    """
    lines = reply.splitlines()
    notes = []
    for idx, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("NOTE:"):
            notes.append(s[5:].strip())
        elif s.startswith("DONE:"):
            return "done", "\n".join([s[5:].strip()] + lines[idx + 1:]).strip(), "", notes
        elif s.startswith("CMD:"):
            text = s[4:].strip()
            if text.startswith("DONE:"):  # small models write "CMD: DONE: ..."
                return "done", "\n".join([text[5:].strip()] + lines[idx + 1:]).strip(), "", notes
            body = "\n".join(lines[idx + 1:])
            if text.split(" ", 1)[0] not in BLOCK_CMDS:
                notes += [l.strip()[5:].strip() for l in lines[idx + 1:]
                          if l.strip().startswith("NOTE:")]
            return "cmd", text, body, notes
    return None, "", "", notes


def _preview(result: str) -> str:
    """Terminal display only. The model always receives the full result."""
    lines = result.splitlines()
    if PREVIEW_LINES <= 0 or len(lines) <= PREVIEW_LINES:
        return result
    hidden = len(lines) - PREVIEW_LINES
    return ("\n".join(lines[:PREVIEW_LINES])
            + f"\n... [{hidden} more lines were sent to the model; PREVIEW_LINES=0 shows all]")


def agent(task: str, max_steps: int = 6) -> str:
    msgs = [("system", SYSTEM), ("user", task)]
    consecutive_failures = 0
    last_key = None
    done_ok = set()  # write/patch commands that already succeeded

    for step in range(max_steps):
        reply = ask_model(msgs)
        if reply.startswith("ERROR: Failed to connect"):
            return f"(stopped: {reply})"
        msgs.append(("assistant", reply))
        print(f"model> {reply}")

        kind, text, body, notes = parse_reply(reply)
        if kind == "done":
            return text  # already shown above as the model> line

        if kind != "cmd":
            msgs.append(("user", "Reply with 'CMD: <command>' or 'DONE: <answer>'."))
            continue

        cmd = text
        key = (cmd, body)  # same file rewritten with new content is not a repeat
        if key == last_key:
            consecutive_failures += 1
        else:
            consecutive_failures = 0
            last_key = key

        is_block = cmd.split(" ", 1)[0] in BLOCK_CMDS
        if is_block and key in done_ok:  # don't redo a finished write/patch
            result = ("REFUSED: you already ran this exact command successfully. "
                      "If the task is finished, reply: DONE: <answer>")
        else:
            result = run(cmd, body)
            if is_block and result.startswith("[exit 0]") and "problem(s) found" not in result:
                done_ok.add(key)
        print(f"tool>  {_preview(result)}")

        if result.startswith(("REFUSED:", "ERROR:")):
            consecutive_failures += 1

        if consecutive_failures >= 3:
            return "(stopped: aborted due to consecutive failures)"

        # Nudge once per missed note; notes are what survives context pruning.
        nudge = "" if notes else "\n(Reminder: start your next reply with a one-line 'NOTE: <finding>'.)"
        if is_block and result.startswith("[exit 0]"):
            if "problem(s) found" in result:
                nudge += "\n(Saved, but the check found problems. Fix them with patch_file, then reply DONE.)"
            else:
                nudge += "\n(Saved. If the task is finished, reply: DONE: <answer>. Do not repeat this command.)"
        msgs.append(("user", f"Here is the output from running '{cmd}':\n{result}{nudge}"))

    return "(stopped: step limit reached)"


def _warn_if_guard_writable():
    """Remind the user to lock this file if it lives inside the sandbox."""
    me = Path(__file__).resolve()
    try:
        if (SANDBOX == me.parent or SANDBOX in me.parents) and me.stat().st_mode & 0o222:
            print(f"[warn] {me.name} is writable and inside the sandbox. "
                  f"Lock it with: chmod 444 {me.name}", file=sys.stderr)
    except OSError:
        pass


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--agent":
        _warn_if_guard_writable()
        result = agent(" ".join(sys.argv[2:]))
        if result.startswith("(stopped:"):  # a DONE answer was already printed as model>
            print("final>", result)
    elif len(sys.argv) >= 2:
        print(run(" ".join(sys.argv[1:])))
    else:
        print(__doc__)

