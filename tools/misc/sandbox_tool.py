#!/usr/bin/env python3
"""
sandbox_tool.py - lets a local GGUF model run a small allowlist of terminal
commands (cat, grep, sed, ls, head, tail, wc) inside one sandbox directory.

Design:
  * No shell is ever used (argv list), so pipes, ;, &&, redirects, $(...)
    and backticks do nothing.
  * Only commands in POLICY exist. rm, chmod, mv, cp, curl... are unknown.
  * Every path argument is resolved with realpath (follows symlinks) and must
    stay inside SANDBOX. Globs (*, ?, [..]) are expanded here and each match
    is checked.
  * LONG flags are an allowlist per command. Unknown long flags are refused;
    abbreviations (--fil) are resolved by us and rewritten to the full name.
  * SHORT flag clusters (-rnf, -nA3, -ni) are scanned character by character;
    dangerous letters are refused and value-taking letters consume their value
    so the value can never be mistaken for a path (or vice versa).
  * grep/sed patterns are separated from paths. sed runs with --sandbox
    (GNU sed), which rejects the e/r/w commands.
  * Timeout, output cap, empty stdin, minimal environment.

Usage:
  python sandbox_tool.py --selftest
  python sandbox_tool.py "grep -rn TODO ."
  python sandbox_tool.py --agent "find where the API key is read"
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
TIMEOUT_S = 10
MAX_OUTPUT = 8000
MAX_GLOB = 200
ALLOW_SED_INPLACE = True  # set False to make sed read-only

_F = "flag"      # long flag, no separate value
_V = "value"     # long flag that takes a value
_P = "pattern"   # long flag that supplies the pattern/script (like -e)
_I = "inplace"   # sed --in-place (gated by ALLOW_SED_INPLACE)

_HEADTAIL = {"lines": _V, "bytes": _V, "quiet": _F, "silent": _F, "verbose": _F}

# pattern:       first positional is a pattern/script (grep, sed)
# short_val:     short letters that take a value (attached, or next token)
# pattern_short: subset of short_val that supplies the pattern itself (-e)
# short_deny:    short letters refused outright
# long:          allowlist of long flags -> kind
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
    """Return the argv to execute, or raise Refused."""
    if not argv:
        raise Refused("empty command")
    cmd, args = argv[0], argv[1:]
    if cmd not in POLICY:
        raise Refused(f"command not allowed: {cmd} (allowed: {', '.join(POLICY)})")
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
            else:  # value / pattern: always pass as a single --key=value token
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
                if cmd == "sed" and ch == "i":  # rest of cluster is a suffix
                    if not ALLOW_SED_INPLACE:
                        raise Refused("sed in-place editing is disabled")
                    break
                if ch in pol["short_val"]:
                    if ch in pol["pattern_short"]:
                        need_pattern = False
                    if idx == len(chars) - 1:  # value is the next token
                        if i >= len(args):
                            raise Refused(f"-{ch} needs a value")
                        extra.append(args[i])
                        i += 1
                    break  # otherwise the rest of the cluster is the value
            out.append(a)
            out.extend(extra)
            continue
        if need_pattern:  # first positional = pattern / sed script
            need_pattern = False
            out.append(a)
            continue
        out.extend(_expand_paths(a))

    if cmd == "sed":
        out.insert(0, "--sandbox")
    return [cmd] + out


def run(command: str) -> str:
    """Tool entry point. Always returns a string (errors included)."""
    try:
        argv = validate(shlex.split(command))
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
SYSTEM = """You are a coding assistant with one tool: a restricted terminal.
To use it, reply with exactly one line: CMD: <command>
Allowed commands: cat, grep, sed, ls, head, tail, wc. One command per turn.
No pipes, redirects or chaining. Paths are relative to the sandbox root.
Use short flags (-n, -r, -i). Wildcards like *.py work in paths.
You cannot delete files or change permissions.
When done, reply with: DONE: <answer>"""

MODEL = "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF"


def ask_model(msgs) -> str:
    formatted_messages = [
        {"role": role, "content": content} for role, content in msgs
    ]

    payload = {
        "model": MODEL,
        "messages": formatted_messages,
        "temperature": 0.1,
        "max_tokens": 64
    }

    req = urllib.request.Request(
        "http://localhost:8080/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
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

        # Track duplicate command loops
        if cmd == last_command:
            consecutive_failures += 1
        else:
            consecutive_failures = 0
            last_command = cmd

        # Run the command through your secure sandbox wrapper
        result = run(cmd)
        print(f"tool>  {result[:300]}")

        # Track tool-level errors or policy refusals
        if result.startswith(("REFUSED:", "ERROR:")):
            consecutive_failures += 1

        if consecutive_failures >= 3:
            return "(stopped: aborted due to consecutive failures)"

        # CRITICAL: Append the real tool output so the model sees it on the next turn!
        msgs.append(("user", f"Here is the output from running '{cmd}':\n{result}"))

    return "(stopped: step limit reached)"


# ------------------------------------------------------------------ selftest
def selftest():
    SANDBOX.mkdir(parents=True, exist_ok=True)
    probe = SANDBOX / "_selftest.txt"
    sedprobe = SANDBOX / "_sed_probe.txt"
    bak = SANDBOX / "_sed_probe.txt.bak"
    link = SANDBOX / "_selftest_link"
    esc = SANDBOX.parent / "_sed_escape_probe"  # sed must never create this
    for p in (esc, link, bak):
        if p.is_symlink() or p.exists():
            p.unlink()
    probe.write_text("hello world\nTODO: fix\n")
    sedprobe.write_text("aaa\n")
    os.symlink(SANDBOX.parent, link)  # symlink pointing OUTSIDE the sandbox

    # Policy refusals: output must start with REFUSED.
    strict = [
        "rm -rf .", "rm _selftest.txt", "chmod 777 _selftest.txt",
        "bash -c id", "python3 -c 1", "cat a | rm b", "cat > out.txt",
        "cat /etc/passwd", "cat ../../.bashrc", "cat ../tools/../../x",
        "cat /etc/*", "cat ../*", "cat -- /etc/passwd",
        "cat _selftest_link/OKX-Terminal", "ls _selftest_link",
        "grep foo /etc/passwd", "grep -- foo /etc/passwd",
        "grep -f /etc/passwd x .", "grep -rf /etc/passwd x .",
        "grep -rnf /etc/passwd .", "grep -R foo .", "grep -Rn foo .",
        "grep --fil=/etc/passwd x", "grep --file /etc/passwd x",
        "grep --file=/etc/passwd x", "grep --dereference-recursive foo .",
        "grep --dereference-r foo .", "grep --exclude-from=/etc/passwd x .",
        "grep -e foo /etc/passwd", "grep -ie foo /etc/passwd",
        "grep -A3 foo /etc/passwd", "grep -rA 3 foo /etc/passwd",
        "grep --regexp=foo /etc/passwd", "grep --regexp foo /etc/passwd",
        "grep --bogus foo .",
        "sed -n p /etc/hosts", "sed -f /etc/passwd _selftest.txt",
        "sed -nf /etc/passwd _selftest.txt", "sed --file=/etc/passwd _selftest.txt",
        "sed --expression=p /etc/passwd", "sed --expr=p /etc/passwd",
        "sed -e p /etc/hosts", "sed -ne p /etc/hosts",
        "sed -i s/a/b/ /etc/hosts", "sed -ni p /etc/hosts",
        "tail -f _selftest.txt", "tail -fn 1 _selftest.txt",
        "tail --foll _selftest.txt", "tail -F _selftest.txt",
        "head -n 5 /etc/passwd", "wc --files0-from=/etc/passwd", "ls --bogus",
    ]
    # Passed to the tool, but must not succeed / must not write outside.
    harmless = [
        "sed 'e id' _selftest.txt", "sed 'r /etc/hosts' _selftest.txt",
        f"sed 'w {esc}' _selftest.txt", f"sed 's/hello/x/w {esc}' _selftest.txt",
        "sed 's/hello/x/e' _selftest.txt",
        "cat a; rm b", "ls ~/..", "cat $(id)",
    ]
    must_work = [
        "cat _selftest.txt", "cat _selftest*.txt", "grep -n TODO _selftest.txt",
        "grep -rn hello .", "grep -e TODO _selftest.txt",
        "grep -ie todo _selftest.txt", "grep -rn -A 1 TODO .",
        "grep --include=*.txt -rn hello .", "grep --regexp TODO _selftest.txt",
        "sed -n 's/hello/bye/p' _selftest.txt", "sed -n -e p _selftest.txt",
        "sed --expression=p _selftest.txt", "ls -la", "ls -R",
        "head -n 1 _selftest.txt", "tail -n 1 _selftest.txt",
        "wc -l _selftest.txt",
    ]
    bad = 0

    def report(ok, kind, c, out):
        nonlocal bad
        print(("PASS " if ok else "FAIL ") + f"{kind:8}", c, "->", out.splitlines()[0])
        bad += not ok

    try:
        for c in strict:
            out = run(c)
            report(out.startswith("REFUSED"), "refuse", c, out)
        for c in harmless:
            out = run(c)
            report(out.startswith("REFUSED") or "[exit 0]" not in out,
                   "harmless", c, out)
        for c in must_work:
            out = run(c)
            report(out.startswith("[exit 0]"), "allow", c, out)

        # in-place edit on a sandbox file
        out = run("sed -i.bak s/aaa/bbb/ _sed_probe.txt")
        if ALLOW_SED_INPLACE:
            report(sedprobe.read_text() == "bbb\n" and bak.exists(),
                   "inplace", "sed -i.bak s/aaa/bbb/ _sed_probe.txt", out)
        else:
            report(out.startswith("REFUSED"), "inplace", "sed -i (disabled)", out)

        # nothing may have been written outside the sandbox
        report(not esc.exists(), "escape", f"{esc} must not exist", "checked")
    finally:
        for p in (probe, sedprobe, bak, link, esc):
            if p.is_symlink() or p.exists():
                p.unlink()
    print("\nALL OK" if not bad else f"\n{bad} FAILURES")
    return bad


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        sys.exit(1 if selftest() else 0)
    elif len(sys.argv) >= 3 and sys.argv[1] == "--agent":
        print("final>", agent(" ".join(sys.argv[2:])))
    elif len(sys.argv) >= 2:
        print(run(" ".join(sys.argv[1:])))
    else:
        print(__doc__)

