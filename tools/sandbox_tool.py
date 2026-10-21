#!/usr/bin/env python3
"""
sandbox_tool.py - lets a local GGUF model run a small allowlist of terminal
commands and secure file modification tools inside one sandbox directory.

SECURITY CONTRACT (what is enforced, and where):
1. SANDBOX CONTAINMENT. Allowlisted commands and the built-ins (read_file, write_file,
   patch_file, check_file) resolve every path with realpath and refuse anything outside
   SANDBOX. run_python enforces the same thing at RUNTIME with an audit hook inside the
   child process (reads, writes, deletes, listings, renames, chmod, links, subprocesses,
   network, ctypes). A script cannot reach outside no matter how it is written, because
   the hook watches what it DOES, not what it looks like. Obfuscation (base64, getattr,
   aliases like e = exec) does not get around it.
2. FILE PROTECTION. This script and refused.log are in PROTECTED: no tool and no
   run_python script may modify them. chmod 444 / attrib +r is a second layer only; it
   does NOT stop a rename-over or a chmod-back, so PROTECTED is the real defence.
3. AUTHORIZED OVERRIDES. A human architect (or an external agent working for one) edits
   this file with the permission bit toggled (chmod u+w / attrib -r), then re-locks it.
   After ANY edit, run:  python test_sandbox_tool.py   It must print ALL OK. A change
   that makes it fail has weakened the guard; do not ship it.
4. EXECUTION SAFETY. Only run_python runs code. It is POSIX-only (Linux, Termux, WSL).
   On Windows it is switched off, because the limits it relies on do not exist there.
   There is no shell: pipes, redirects, chaining, python -c and base64 tricks do nothing.
5. STATE VERIFICATION. The agent loop refuses DONE while a .py file was changed and not
   run since, while its last run failed, or while a write/patch was refused and never
   redone (REQUIRE_VERIFY=0 turns this off). exit 0 proves it ran, not that it is right.
KNOWN GAPS: os.mkfifo / os.mknod / os.chroot have no audit event; a determined attacker
using interpreter internals could still get out. This is a guard against a model's
mistakes and tricks, not a container.
"""
import os
import sys

# Defense in depth: when run as a script, don't let a file sitting next to it
# (e.g. a model-written json.py) shadow the stdlib modules imported below.
if (__name__ == "__main__" and sys.path
        and os.path.realpath(sys.path[0] or ".") == os.path.dirname(os.path.realpath(__file__))):
    sys.path.pop(0)

import ast
import builtins
import glob
import io
import json
import re
import tokenize
import shlex
import shutil
import signal
import site
import subprocess
import sysconfig
import tempfile
import time
import urllib.request
from pathlib import Path

_TERMUX_SANDBOX = Path("/data/data/com.termux/files/home/OKX-Terminal/tools")
SANDBOX = Path(os.environ.get(
    "SANDBOX_DIR", _TERMUX_SANDBOX if _TERMUX_SANDBOX.is_dir() else Path(__file__).resolve().parent)).resolve()
TIMEOUT_S = 300
MAX_OUTPUT = 8000
MAX_GLOB = 200
ALLOW_SED_INPLACE = True
PREVIEW_LINES = int(os.environ.get("PREVIEW_LINES", "15"))  # 0 = show everything
# Files the model may read but never modify (this script, if it lives in the sandbox).
AUDIT_LOG = Path(os.environ.get("AUDIT_LOG", str(Path(__file__).resolve().with_name("refused.log"))))
PROTECTED = {Path(__file__).resolve(), AUDIT_LOG.resolve()}
# run_python limits (see the notes above cmd_run_python)
RUN_PYTHON = os.environ.get("RUN_PYTHON", "1") != "0" and os.name != "nt"  # needs POSIX limits
RUN_TIMEOUT_S = int(os.environ.get("RUN_TIMEOUT_S", "10"))
REQUIRE_VERIFY = os.environ.get("REQUIRE_VERIFY", "1") != "0"                 # block DONE until code was run
REQUIRE_RUN_BEFORE_PATCH = os.environ.get("REQUIRE_RUN_BEFORE_PATCH", "0") == "1"  # strict mode for small models
RUN_MEM_MB = int(os.environ.get("RUN_MEM_MB", "1024"))  # watched from outside; 0 = no limit
RUN_MAX_FILE_MB = 20

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

    The block ends at the first closing fence that is followed by nothing, or by a
    protocol line (NOTE:/CMD:/DONE:). That keeps file content free to contain its own
    fences (markdown), but stops at the model's real closing fence when the model keeps
    writing and invents the next steps (fake tool output, more CMD lines) after it.
    If no closing fence qualifies, the LAST bare fence ends the block (older behaviour).
    An unclosed block means the reply was probably cut off by the token limit; refuse
    rather than write a truncated file."""
    lines = (body or "").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().startswith("```")), None)
    if start is None:
        return None
    closers = [i for i in range(start + 1, len(lines)) if lines[i].strip() == "```"]
    if not closers:
        raise Refused("code block is not closed (reply may have been cut off); "
                      "write a shorter file or split it into parts")

    def _ends_reply(i):
        nxt = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
        return not nxt or nxt.startswith(("NOTE:", "CMD:", "DONE:"))
    end = next((i for i in closers if _ends_reply(i)), closers[-1])
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


_STDLIB = getattr(sys, "stdlib_module_names", frozenset(
    "abc argparse ast asyncio base64 collections copy csv datetime decimal enum functools "
    "glob hashlib heapq io itertools json logging math operator os pathlib pickle queue random "
    "re shutil sqlite3 statistics string struct subprocess sys tempfile textwrap threading time "
    "typing unittest uuid warnings".split()))


def _missing_imports(tree, source: str) -> list:
    """(line, message) for stdlib modules used as `name.attr` that are never bound in the file."""
    bound = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            bound.update(n.names)
    first = next((l.rstrip() for l in source.splitlines() if l.strip()), "")
    firstuse = {}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id in _STDLIB and not n.value.id.startswith("_")
                and n.value.id not in bound):
            firstuse[n.value.id] = min(firstuse.get(n.value.id, n.lineno), n.lineno)
    out = []
    for name, line in sorted(firstuse.items(), key=lambda kv: kv[1]):
        fix = (f"Add `import {name}` as the very FIRST line of the file (line 1), above everything else, "
               f"never inside a class, function or dict.")
        if first and not first.startswith((" ", "\t")):
            fix += (f" With patch_file: SEARCH = `{first[:70]}`, REPLACE = `import {name}`, "
                    f"an empty line, then `{first[:70]}`.")
        out.append((line, f"`{name}` is used but never imported, so this will fail with NameError. {fix}"))
    return out


def check_python(source: str) -> list[str]:
    """Static check only: the code is parsed, never executed. Returns problem lines.

    Catches syntax errors, stub bodies, placeholder comments, methods shadowed by
    self.<name> assignments, wrong argument counts on self.method() calls, and demo
    code that runs on import. It does NOT prove the program works."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        text = (e.text or "").strip()
        msg = e.msg
        if isinstance(e, IndentationError) or "indent" in msg.lower():
            msg += ". Every line of a REPLACE block needs the file's exact leading spaces (4 per level)."
        return [f"SYNTAX ERROR line {e.lineno}: {msg}" + (f"  -> {text}" if text else "")]

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

    # A standard-library module used as name.attr but never imported or assigned anywhere
    # (the classic NameError a small model forgets: random.randint with no `import random`).
    problems += _missing_imports(tree, source)

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


# ------------------------------------------------------------ run_python (Phase 2)
# Runs a model-written .py file in a child process. READ THIS FIRST:
#  * The real enforcement is the runtime audit hook in _RUNNER. It sees the actual
#    operation (open, remove, subprocess, connect...), so obfuscation such as
#    getattr(__import__("o"+"s"), "sys"+"tem") does not get past it.
#  * scan_python() is only a friendly pre-flight: it refuses obvious calls before
#    anything runs, so the model gets a clear message. It is NOT a security check.
#  * This guards against a literal-minded 3B model making accidents. It is not a
#    sandbox against someone deliberately attacking it (no container exists on Termux).
#  * Known gaps (found by testing, not fixable with an audit hook): os.mkfifo, os.mknod,
#    os.chroot and os.sethostname raise no audit event, so a script can create an empty
#    FIFO outside the sandbox. Anyone willing to dig into interpreter internals can also
#    get around it. Deleting is allowed only in the run's own temp folder.
#  * Memory is limited by watching the child's resident size from /proc (RUN_MEM_MB),
#    not with RLIMIT_AS: on Android that made Python abort at startup (found on Termux).
#  * Reads are limited to the sandbox plus Python's own library folders. (An earlier
#    version allowed all of sys.prefix; on Termux that includes usr/tmp, usr/etc and
#    usr/var, and the test suite caught a script reading a file there.)
#  * Verified on Termux: the /proc memory watch and RLIMIT_CPU/RLIMIT_FSIZE work.
#    Still untested there: start_new_session / killpg on timeout. If a normal script fails with "reading outside the sandbox",
#    note the path it names; that folder probably belongs in _read_roots().
_SCAN_CALLS = {
    "os.system", "os.popen", "os.fork", "os.forkpty", "os.kill", "os.killpg",
    "os.chmod", "os.chown", "os.lchown", "os.symlink", "os.link", "shutil.chown", "pty.spawn",
}  # deleting is not listed: the runtime hook decides (it allows the run's own temp folder)
_SCAN_PREFIX = ("subprocess.", "os.exec", "os.spawn", "os.posix_spawn", "ctypes.")
_SCAN_ATTRS = {"chmod", "symlink_to", "hardlink_to"}
_SCAN_IMPORTS = {"subprocess", "ctypes", "pty"}


def scan_python(source: str) -> list[str]:
    """Pre-flight list of clearly blocked calls/imports (line-numbered). [] if none
    or if the file does not parse (the run then reports the SyntaxError itself)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    alias = {}
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                alias[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
                if a.name.split(".")[0] in _SCAN_IMPORTS:
                    out.append((n.lineno, f"import {a.name} is blocked"))
        elif isinstance(n, ast.ImportFrom) and n.module:
            if n.module.split(".")[0] in _SCAN_IMPORTS:
                out.append((n.lineno, f"import from {n.module} is blocked"))
            for a in n.names:
                alias[a.asname or a.name] = f"{n.module}.{a.name}"
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        parts, f = [], n.func
        while isinstance(f, ast.Attribute):
            parts.append(f.attr)
            f = f.value
        if isinstance(f, ast.Name):
            parts.append(alias.get(f.id, f.id))
            name = ".".join(reversed(parts))
            if name in _SCAN_CALLS or name.startswith(_SCAN_PREFIX):
                out.append((n.lineno, f"{name}() is blocked (other programs, chmod and links are not allowed)"))
                continue
        if isinstance(n.func, ast.Attribute) and n.func.attr in _SCAN_ATTRS:
            out.append((n.lineno, f".{n.func.attr}() is blocked (chmod and links are not allowed)"))
    return [f"line {ln}: {msg}" for ln, msg in sorted(set(out))]


# Child-process program. It installs the audit hook, then runs the target file.
# Everything the hook needs is bound inside _install() so the target script cannot
# swap it out by editing builtins or module globals. It must not use backslashes.
_RUNNER = r'''
import sys, os, json, runpy, traceback, resource
cfg = json.loads(sys.argv[1])
target = sys.argv[2]
sys.dont_write_bytecode = True
sys.path.append(cfg["sandbox"])  # appended, so a model-written json.py cannot shadow the stdlib
for _n, _v in (("RLIMIT_CPU", cfg["cpu"]), ("RLIMIT_FSIZE", cfg["fsize"])):
    if _v:
        try:
            resource.setrlimit(getattr(resource, _n), (_v, _v))
        except (ValueError, OSError, AttributeError):
            pass


class SandboxBlocked(PermissionError):
    pass


def _no_exec(*a, **k):
    raise SandboxBlocked("sandbox: starting other programs is not allowed")


# multiprocessing (spawn/forkserver) starts new interpreters through this low-level
# function, which raises no audit event, so replace it before the hook goes in.
import subprocess, _posixsubprocess
_posixsubprocess.fork_exec = _no_exec
subprocess._fork_exec = _no_exec


def _install(cfg):
    SB = cfg["sandbox"]
    TMP = cfg["tmp"]
    PROT = frozenset(cfg["protected"])
    READ = tuple(cfg["read_roots"]) + (SB,)
    DEVS = frozenset(("/dev/null", "/dev/zero", "/dev/urandom", "/dev/random"))
    realpath, fsdecode, sep = os.path.realpath, os.fsdecode, os.sep
    O_W = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    PROC = frozenset(("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
                      "os.fork", "os.forkpty", "os.kill", "os.killpg", "pty.spawn"))
    PERM = frozenset(("os.chmod", "os.chown", "os.lchown", "os.lchmod", "os.chflags",
                      "os.setxattr", "os.removexattr", "os.symlink", "os.link"))
    NET = frozenset(("socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg",
                     "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr",
                     "socket.getnameinfo"))
    NATIVE = frozenset(("ctypes.dlopen", "ctypes.dlsym", "ctypes.call_function"))
    GC = frozenset(("gc.get_objects", "gc.get_referrers", "gc.get_referents"))

    def hook(event, args, isinstance=isinstance, any=any, str=str, int=int, bool=bool,
             Blocked=SandboxBlocked):
        def real(p):
            try:
                s = fsdecode(p)
            except Exception:
                return None
            # With dir_fd the kernel resolves a relative path from another folder than
            # the one checked here, and '..' lets that escape. Refuse such paths.
            if not s.startswith(sep) and ".." in s.split(sep):
                raise Blocked("sandbox: relative paths containing '..' are not allowed; "
                              "use a path inside the sandbox without '..'")
            try:
                return realpath(s)
            except Exception:
                return None

        def under(p, roots):
            if p is None:
                return False
            for r in roots:
                if p == r or p.startswith(r + sep):
                    return True
            return False

        def write_ok(p):
            return under(p, (SB,)) and p not in PROT and "__pycache__" not in p.split(sep)

        def deny(msg):
            raise Blocked("sandbox: " + msg)

        if event == "import":
            if args[0] == "multiprocessing" or args[0].startswith("multiprocessing."):
                deny("multiprocessing is not allowed (it starts other programs); use threads or plain loops")
        elif event == "open":
            path, mode, flags = args
            if isinstance(path, int):
                return
            p = real(path)
            wr = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                 (isinstance(flags, int) and bool(flags & O_W))
            if wr:
                if not write_ok(p):
                    deny("writing outside the sandbox, or to a protected file, is not allowed: %s" % (path,))
            elif not (under(p, READ) or p in DEVS):
                deny("reading outside the sandbox is not allowed: %s" % (path,))
        elif event in ("os.listdir", "os.scandir"):
            path = args[0]
            if not isinstance(path, int) and not under(real("." if path is None else path), READ):
                deny("listing a folder outside the sandbox is not allowed: %s" % (path,))
        elif event == "os.chdir":
            if not isinstance(args[0], int) and not under(real(args[0]), (SB,)):
                deny("changing to a folder outside the sandbox is not allowed")
        elif event in ("os.mkdir", "os.truncate"):
            if not isinstance(args[0], int) and not write_ok(real(args[0])):
                deny("creating or changing files outside the sandbox, or protected ones, is not allowed")
        elif event == "os.rename":
            for q in args[:2]:
                if not write_ok(real(q)):
                    deny("moving files outside the sandbox, or touching a protected file, is not allowed")
        elif event in ("os.remove", "os.rmdir", "shutil.rmtree"):
            if isinstance(args[0], int) or not under(real(args[0]), (TMP,)):
                deny("deleting files is switched off (only this run's temp folder can be cleaned)")
        elif event in PERM:
            deny("chmod/chown and links are not allowed (%s)" % event)
        elif event in PROC:
            deny("starting or killing other processes is not allowed (%s)" % event)
        elif event in NATIVE:
            deny("ctypes / native code is not allowed")
        elif event in NET:
            deny("network access is not allowed")
        elif event in GC:
            deny("gc introspection is not allowed")
        elif event == "sqlite3.connect":
            db = args[0]
            if isinstance(db, (str, bytes)) and db not in (":memory:", "", b":memory:", b"") \
                    and not write_ok(real(db)):
                deny("databases outside the sandbox are not allowed")

    sys.addaudithook(hook)


_install(cfg)
del _install, cfg
try:
    runpy.run_path(target, run_name="__main__")
except SystemExit:
    raise
except BaseException:
    _et, _ev, _tb = sys.exc_info()
    while _tb is not None and _tb.tb_frame.f_code.co_filename != target:
        _tb = _tb.tb_next
    _t = _tb
    while _t is not None and _t.tb_next is not None:  # drop this runner's own hook frames
        if _t.tb_next.tb_frame.f_code.co_filename == "<string>":
            _t.tb_next = None
            break
        _t = _t.tb_next
    traceback.print_exception(_et, _ev, _tb)
    sys.exit(1)
'''


def _read_roots() -> list[str]:
    """Folders a script may READ besides the sandbox: only Python's own code and
    libraries. Never a whole prefix such as /usr or Termux's usr: that also holds tmp/,
    etc/ (ssh host keys, configs) and var/, which a script has no business reading."""
    paths = sysconfig.get_paths()
    roots = {paths.get(k) for k in ("stdlib", "platstdlib", "purelib", "platlib")}
    roots.add(os.path.dirname(os.__file__))
    try:
        roots.update(site.getsitepackages())
    except Exception:
        pass
    roots.add("/usr/share/zoneinfo")
    roots.add(os.path.join(sys.prefix, "share", "zoneinfo"))
    return sorted({os.path.realpath(r) for r in roots if r and os.path.isabs(r)} - {"/"})


def _head_tail(f, head=2000, tail=6000) -> str:
    size = f.seek(0, 2)
    f.seek(0)
    if size <= head + tail:
        return f.read().decode("utf-8", "replace")
    first = f.read(head).decode("utf-8", "replace")
    f.seek(size - tail)
    last = f.read(tail).decode("utf-8", "replace")
    return f"{first}\n...[{size - head - tail} bytes of output omitted]...\n{last}"


def _rss_mb(pid):
    """Resident memory of a process in MB from /proc, or None if it cannot be read."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def cmd_run_python(path_str: str) -> str:
    """Run a .py file inside the sandbox under the audit-hook policy. Output and
    tracebacks come back to the model so it can fix its own code."""
    if not RUN_PYTHON:
        return ("REFUSED: run_python is switched off (RUN_PYTHON=0, or this is Windows, "
                "where its limits do not exist). Run it on Linux, Termux or WSL.")
    try:
        _check_path(path_str)
        target = Path(os.path.realpath(SANDBOX / path_str))
        if target.suffix != ".py":
            return "REFUSED: run_python only runs .py files"
        if not target.is_file():
            return f"ERROR: no such file: {path_str}"
        if target in PROTECTED:
            return f"REFUSED: protected file, cannot run: {path_str}"
        problems = scan_python(target.read_text(errors="replace"))
    except Refused as e:
        return f"REFUSED: {e}"
    except OSError as e:
        return f"ERROR: {e}"
    if problems:
        return ("REFUSED: not run. These are blocked in the sandbox:\n"
                + "\n".join("  " + p for p in problems[:15]))

    tmp = tempfile.mkdtemp(prefix=".run_", dir=SANDBOX)
    out = tempfile.TemporaryFile()
    cfg = {
        "sandbox": str(SANDBOX), "tmp": os.path.realpath(tmp),
        "protected": [str(p) for p in PROTECTED], "read_roots": _read_roots(),
        "cpu": RUN_TIMEOUT_S + 2, "fsize": RUN_MAX_FILE_MB * 1024 * 1024,
    }
    env = {"PATH": "/data/data/com.termux/files/usr/bin:/usr/bin:/bin", "HOME": str(SANDBOX),
           "LC_ALL": "C.UTF-8", "TMPDIR": tmp}
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", _RUNNER, json.dumps(cfg), str(target)],
            cwd=SANDBOX, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
            env=env, start_new_session=True)
        timed_out = over_mem = False
        deadline = time.monotonic() + RUN_TIMEOUT_S
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            if RUN_MEM_MB and (_rss_mb(proc.pid) or 0) > RUN_MEM_MB:
                over_mem = True
                break
            time.sleep(0.05)
        if timed_out or over_mem:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait()
        full = out.seek(0, 2) >= cfg["fsize"]
        text = _head_tail(out)
    except OSError as e:
        return f"ERROR: could not start python: {e}"
    finally:
        out.close()
        shutil.rmtree(tmp, ignore_errors=True)
    if over_mem:
        return f"[exit 137]\nKILLED: the script used more than {RUN_MEM_MB} MB of memory.\n{text}".rstrip()
    if timed_out:
        return (f"[exit 124]\nTIMED OUT after {RUN_TIMEOUT_S}s and was killed (infinite loop, "
                f"sleep, or waiting for input?).\n{text}".rstrip())
    head = f"[exit {proc.returncode}]"
    if full:
        head += f" (output reached the {RUN_MAX_FILE_MB}MB limit: the script printed far too much)"
    if proc.returncode < 0:
        try:
            name = signal.Signals(-proc.returncode).name
        except ValueError:
            name = f"signal {-proc.returncode}"
        head += f" (killed by {name}: a resource limit was hit, or the interpreter itself crashed)"
        if not text.strip():
            text = "(no output: python died before it could print anything; this is a device/tool problem, not your script)"
    return head + "\n" + (text or "(no output)")


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


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _reindent_tail(content, idx, search_text, replace_text):
    """A one-line SEARCH matched after the line's leading spaces, and REPLACE has several
    lines written without that indent: add the file's indent to REPLACE lines 2+."""
    if "\n" in search_text or "\n" not in replace_text:
        return replace_text
    line_start = content.rfind("\n", 0, idx) + 1
    prefix = content[line_start:idx]
    if not prefix or prefix.strip():
        return replace_text
    first, *rest = replace_text.split("\n")
    body = [l for l in rest if l.strip()]
    if not body or min(_indent(l) for l in body) >= len(prefix):
        return replace_text  # already written with the file's indentation
    return "\n".join([first] + [(prefix + l) if l.strip() else l for l in rest])


def _fuzzy_replace(content, search_text, replace_text):
    """Match SEARCH ignoring leading/trailing spaces on each line. Returns new content,
    'AMBIGUOUS', or None. REPLACE is shifted by the difference in indentation."""
    s_lines = search_text.split("\n")
    if not any(l.strip() for l in s_lines):
        return None
    f_lines = content.split("\n")
    n = len(s_lines)
    hits = [i for i in range(len(f_lines) - n + 1)
            if all(f_lines[i + k].strip() == s_lines[k].strip() for k in range(n))]
    if not hits:
        return None
    if len(hits) > 1:
        return "AMBIGUOUS"
    i = hits[0]
    f_ind, s_ind = _indent(f_lines[i]), _indent(s_lines[0])
    pad = f_lines[i][:f_ind]
    if f_ind >= s_ind:
        base = pad[:f_ind - s_ind]
        new = [(base + l) if l.strip() else l for l in replace_text.split("\n")]
    else:  # model indented more than the file: strip the excess where present
        cut = s_ind - f_ind
        new = [(l[cut:] if l[:cut].strip() == "" else l) for l in replace_text.split("\n")]
    return "\n".join(f_lines[:i] + new + f_lines[i + n:])


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
        if search_text == replace_text:
            return ("REFUSED: SEARCH and REPLACE are identical, so nothing would change. "
                    "Write the corrected lines in REPLACE (keep the file's leading spaces).")
        note = ""
        if search_text in content:
            if content.count(search_text) > 1:
                return f"REFUSED: search text is not unique in {path_str}; include more surrounding lines"
            idx = content.index(search_text)
            fixed = _reindent_tail(content, idx, search_text, replace_text)
            if fixed != replace_text:
                note = " (indentation of the new lines adjusted to match the file)"
            new_content = content[:idx] + fixed + content[idx + len(search_text):]
        else:
            hit = _fuzzy_replace(content, search_text, replace_text)
            if hit is None:
                return (f"REFUSED: search text not found in {path_str} (it must match exactly, "
                        f"including indentation). Use read_file {path_str} to copy the exact lines.")
            if hit == "AMBIGUOUS":
                return f"REFUSED: search text matches more than one place in {path_str}; include more surrounding lines"
            new_content, note = hit, " (leading spaces adjusted to match the file)"
        if new_content == content:
            return "REFUSED: that edit would not change the file"
        if path_str.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError:
                pass  # the file was already broken: let the model repair it step by step
            else:
                try:
                    ast.parse(new_content)
                except SyntaxError as e:
                    bad = (e.text or "").strip()
                    return (f"REFUSED: this patch would leave {path_str} with a syntax error "
                            f"(line {e.lineno}: {e.msg}{'  -> ' + bad if bad else ''}), so it was NOT applied and the file "
                            f"is unchanged. A REPLACE must keep the brackets, quotes and indentation balanced: if SEARCH "
                            f"opens a '{{' or '(' then REPLACE must close it too. Use read_file {path_str} to copy the "
                            f"exact lines, then send a corrected patch.")
        target.write_text(new_content)
        log_to_index(path_str, "patched")
        return f"[exit 0]\nSuccessfully patched {path_str}{note}"
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
        raise Refused(f"command not allowed: {cmd} (allowed: {', '.join(POLICY)}, read_file, write_file, patch_file, check_file, run_python)")
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


_NO_WRITE_WORKAROUND = ("To create or change a file use write_file / patch_file with a ``` block "
                        "after the CMD line. To run Python use: run_python <file.py>.")


def _hint(command: str, msg: str) -> str:
    """Tell the model what to do instead, so a refusal is not a dead end."""
    low = (command or "").lower()
    first = low.split(None, 1)[0] if low.split() else ""
    if ("no pipes" in msg or "No closing quotation" in msg or "No escaped" in msg
            or first in ("python", "python3", "bash", "sh", "node", "perl", "ruby", "base64",
                         "echo", "printf", "tee", "cp", "mv", "touch", "dd", "xxd", "openssl")
            or "base64" in low or "<<" in low):
        return msg + "\n" + _NO_WRITE_WORKAROUND
    return msg


def _audit(command: str, msg: str):
    """Append a refused command to AUDIT_LOG (protected, outside the model's reach)."""
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{msg[:120]!r}\t{command[:300]!r}\n")
    except OSError:
        pass


def run(command: str, body: str = "") -> str:
    out = _run(command, body)
    if out.startswith("REFUSED:"):
        _audit(command, out)
        out = _hint(command, out)
    return out


def _run(command: str, body: str = "") -> str:
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
        elif cmd == "run_python":
            if len(parts) != 2:
                return "REFUSED: usage: run_python <path.py>"
            return cmd_run_python(parts[1])
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
- run_python <path.py>   runs a .py file in the sandbox and returns its output or its
  traceback. Limits: 10 seconds, no keyboard input, no network, cannot delete files, cannot
  start other programs (no subprocess, os.system, multiprocessing), cannot use paths
  containing '..', reads and writes only inside the sandbox.

WORKFLOW for code: write_file, then run_python, then fix any traceback with patch_file and
run_python again. Only say the code works if run_python showed [exit 0] and the output
matches the task. If it still fails, say so and quote the error.

FILES: never create or edit files with cat, echo, printf, heredocs, redirects, python -c,
base64 or any other trick. Those are refused. Only write_file and patch_file write files, and
only run_python runs code.

RULE OF OBSERVATION: you cannot know your code works until run_python has run it and you
have read the output. Never declare success, and never patch, on a guess. After any
write_file or patch_file of a .py file, run_python it before you reply DONE.

When you see a NameError for a standard library module, always place the import statement
at the very top of the file (module scope), not inline.

A patch only counts when the tool answers "Successfully patched". If a patch or write was
REFUSED, fix the problem and send it again before you say DONE. Every line you put in a
REPLACE block needs the same leading spaces the file has.

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
BACKEND = os.environ.get("BACKEND", "local").lower()      # local | gemini
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
LLAMA_TIMEOUT = int(os.environ.get("LLAMA_TIMEOUT", "900"))  # longest SILENCE from the server (prompt reading counts)
LLAMA_TOTAL_TIMEOUT = int(os.environ.get("LLAMA_TOTAL_TIMEOUT", "1800"))  # cap for one whole reply
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

    if BACKEND == "gemini":
        return _ask_gemini(trimmed_msgs)
    return _ask_local(trimmed_msgs)


def _ask_gemini(msgs) -> str:
    """Gemini via google-genai. The SYSTEM prompt goes in system_instruction, and
    assistant turns are sent with role 'model', so the model sees real roles."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return "ERROR: Failed to connect: GEMINI_API_KEY environment variable is not set."
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return "ERROR: Failed to connect: run  pip install google-genai"
    system = "\n\n".join(c for r, c in msgs if r == "system")
    contents = [types.Content(role="model" if r == "assistant" else "user",
                              parts=[types.Part(text=c)])
                for r, c in msgs if r != "system"]
    config = types.GenerateContentConfig(system_instruction=system, temperature=0.2)
    client = genai.Client(api_key=api_key)
    for attempt in range(5):
        try:
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
            return (resp.text or "").strip()
        except Exception as e:
            if attempt == 4:
                return f"ERROR: Failed to connect to Gemini API: {e}"
            wait = 5 * (attempt + 1)
            print(f"[info] Gemini busy, retrying in {wait}s (attempt {attempt + 1}/5)...")
            time.sleep(wait)


LAST_STATS = ""   # one line about the last local model call (speed), shown after each reply
LLAMA_STREAM = os.environ.get("LLAMA_STREAM", "1") != "0"   # 0 = plain request, like curl


class _BadReply(Exception):
    """The server answered, but not in a form we can read."""


def _read_sse(lines, show_progress=True):
    """Parse server-sent-event lines. Tolerates blank 'data:' lines, comments, CRLF and
    chunks that are not JSON. Returns (text, n_pieces, t_first, timings, skipped)."""
    parts, n, t_first, timings, skipped = [], 0, None, None, []
    t0 = time.time()
    for raw in lines:
        line = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw).strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk:
            continue
        if chunk == "[DONE]":
            break
        try:
            d = json.loads(chunk)
        except ValueError:
            skipped.append(chunk[:120])
            continue
        if not isinstance(d, dict):
            continue
        if "error" in d and not d.get("choices"):
            raise _BadReply(f"server error: {str(d['error'])[:200]}")
        timings = d.get("timings") or timings
        for c in d.get("choices") or []:
            piece = (c.get("delta") or {}).get("content") or (c.get("message") or {}).get("content")
            if piece:
                if t_first is None:
                    t_first = time.time()
                parts.append(piece)
                n += 1
                if show_progress and n % 5 == 0 and sys.stderr.isatty():
                    rate = n / max(time.time() - t_first, 1e-6)
                    sys.stderr.write(f"\r[llm] generating: {n} tokens ({rate:.2f} tok/s)  ")
                    sys.stderr.flush()
        if time.time() - t0 > LLAMA_TOTAL_TIMEOUT:
            raise TimeoutError(
                f"too slow: {n} tokens in {int(time.time() - t0)}s (limit "
                f"LLAMA_TOTAL_TIMEOUT={LLAMA_TOTAL_TIMEOUT}s). Run: python sandbox_tool.py --ping")
    return "".join(parts), n, t_first, timings, skipped


def _ask_local(trimmed_msgs, max_tokens=1024, stream=None) -> str:
    """Local llama-server. Streamed by default: LLAMA_TIMEOUT is the longest the server may
    stay SILENT (a slow phone can need minutes to read the prompt before the first token),
    and LLAMA_TOTAL_TIMEOUT caps one whole reply. If the streamed reply cannot be read, it
    asks again once without streaming (the plain request curl uses)."""
    global LAST_STATS
    LAST_STATS = ""
    stream = LLAMA_STREAM if stream is None else stream
    payload = {
        "model": MODEL,
        "messages": [{"role": role, "content": content} for role, content in trimmed_msgs],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if stream:
        payload["stream"] = True
    req = urllib.request.Request(
        SERVER_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0, t_first, n, timings, text = time.time(), None, 0, None, ""
    try:
        with urllib.request.urlopen(req, timeout=LLAMA_TIMEOUT) as r:
            if stream:
                text, n, t_first, timings, skipped = _read_sse(r)
                if not text:  # the body may be a plain JSON reply, or an SSE body sent as JSON
                    raise _BadReply("empty streamed reply" + (f" (unreadable chunk: {skipped[0]!r})" if skipped else ""))
            else:
                body = r.read().decode("utf-8", "replace")
                if not body.strip():
                    raise _BadReply("the server sent an empty reply")
                if body.lstrip().startswith("data:"):
                    text, n, t_first, timings, _ = _read_sse(body.splitlines())
                else:
                    try:
                        data = json.loads(body)
                        text = data["choices"][0]["message"]["content"] or ""
                        timings = data.get("timings")
                    except (ValueError, KeyError, IndexError, TypeError):
                        raise _BadReply(f"unreadable reply from the server: {body[:200]!r}")
    except _BadReply as e:
        if stream:   # one more try the plain way, before giving up
            sys.stderr.write(f"[llm] streamed reply unreadable ({e}); retrying without streaming\n")
            return _ask_local(trimmed_msgs, max_tokens, stream=False)
        return f"ERROR: Failed to connect to local llama-server: {e}"
    except Exception as e:
        hint = ""
        if "timed out" in str(e) or isinstance(e, TimeoutError):
            hint = "  (the server is too slow or stuck; run: python sandbox_tool.py --ping)"
        return f"ERROR: Failed to connect to local llama-server: {e}{hint}"
    finally:
        if sys.stderr.isatty():
            sys.stderr.write("\r" + " " * 60 + "\r")
    total = time.time() - t0
    bits = [f"{total:.0f}s total"]
    if timings:
        pn = timings.get("prompt_n") or 0
        if 0 < pn < 20 and timings.get("cache_n"):   # almost all of the prompt came from the server's cache
            bits.append(f"prompt cached ({timings['cache_n']} tok reused, {pn} new; read speed not measured)")
        elif pn:
            bits.append(f"prompt {pn} tok @ {timings.get('prompt_per_second', 0):.1f} tok/s")
        if timings.get("predicted_n"):
            bits.append(f"generated {timings['predicted_n']} tok @ {timings.get('predicted_per_second', 0):.2f} tok/s")
    elif t_first and n > 1:
        bits.append(f"generated ~{n} tok @ {(n - 1) / max(time.time() - t_first, 1e-6):.2f} tok/s")
    LAST_STATS = ", ".join(bits)
    return text.strip()


def ping() -> str:
    """Time one real-sized request so you can see how fast the local server is."""
    msgs = [("system", SYSTEM), ("user", "Reply with exactly: CMD: ls")]
    t0 = time.time()
    out = _ask_local(msgs, max_tokens=24)
    if out.startswith("ERROR:"):
        return out
    est = LAST_STATS
    return (f"server replied in {time.time() - t0:.0f}s: {out!r}\n[llm] {est}\n"
            "If it says 'prompt cached', the server already had this prompt, so only generation speed was measured.\n"
            "Rule of thumb: the first agent step reads the whole system prompt "
            f"(~{len(SYSTEM) // 4} tokens) once; later steps reuse the server's cache. "
            "Below ~1 tok/s generation, check CPU throttling, free RAM, leftover llama processes, "
            "and the -t (threads) / -np (slots) server flags.")


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


def _local_imports(path_str: str, seen=None) -> set:
    """Names of sandbox .py files that `path_str` imports (directly or through each other)."""
    seen = seen if seen is not None else set()
    try:
        tree = ast.parse((SANDBOX / path_str).read_text(errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return seen
    for n in ast.walk(tree):
        mods = ([a.name for a in n.names] if isinstance(n, ast.Import)
                else [n.module] if isinstance(n, ast.ImportFrom) and n.module and not n.level else [])
        for m in mods:
            f = m.split(".")[0] + ".py"
            if f not in seen and (SANDBOX / f).is_file():
                seen.add(f)
                _local_imports(f, seen)
    return seen


def _clean_reply(reply: str, kind: str, text: str, notes: list) -> str:
    """What goes into history. For an ordinary command keep only NOTE + CMD, so text the
    model invented after the command (fake tool output, a fake DONE) is not remembered."""
    if kind == "cmd" and text.split(" ", 1)[0] not in BLOCK_CMDS:
        return (f"NOTE: {notes[0]}\n" if notes else "") + f"CMD: {text}"
    return reply


def _norm(path_str: str) -> str:
    return os.path.normpath(path_str)


def agent(task: str, max_steps: int = 10) -> str:
    msgs = [("system", SYSTEM), ("user", task)]
    consecutive_failures = 0
    last_key = None
    done_ok = set()      # write/patch commands that already succeeded
    # Verification state (the DONE gate). A claim of success needs evidence from run_python.
    unverified = set()   # .py files changed since they were last run
    last_exit = {}       # .py file -> exit code of its most recent run
    refused_edit = {}    # file -> command that was REFUSED and not yet redone successfully
    problems = set()     # .py files whose last static check listed problems
    done_blocked = 0

    for step in range(max_steps):
        global LAST_STATS
        LAST_STATS = ""
        reply = ask_model(msgs)
        if reply.startswith("ERROR: Failed to connect"):
            return f"(stopped: {reply})"
        if LAST_STATS:
            print(f"[llm] {LAST_STATS}")
        kind, text, body, notes = parse_reply(reply)
        msgs.append(("assistant", _clean_reply(reply, kind, text, notes)))
        print(f"model> {reply}")

        if kind == "done":
            why = []
            if REQUIRE_VERIFY and RUN_PYTHON:
                if unverified:
                    why.append("you changed " + ", ".join(sorted(unverified)) +
                               " and have not run it since: use run_python on it first")
                bad = sorted(f for f, c in last_exit.items() if c != 0 and f not in unverified)
                if bad:
                    why.append("the last run of " + ", ".join(bad) + " failed; fix it with patch_file "
                               "and run_python again")
            if refused_edit:
                why.append("these were REFUSED and never applied: " +
                           "; ".join(f"{c}" for c in refused_edit.values()) +
                           " (send them again, corrected)")
            if why:
                done_blocked += 1
                msg = "REFUSED: cannot accept DONE yet: " + "; ".join(why) + "."
                print(f"tool>  {msg}")
                if done_blocked >= 3:
                    return "(stopped: DONE was blocked 3 times; " + "; ".join(why) + ")"
                msgs.append(("user", msg))
                continue
            return text  # already shown above as the model> line

        if kind != "cmd":
            hint = "Reply with 'CMD: <command>' or 'DONE: <answer>'."
            if "```" in reply:
                hint += (" Code in a chat reply is not saved. To save it, reply with the line "
                         "'CMD: write_file <name.py>' and put the code in a ``` block on the lines after it.")
            msgs.append(("user", hint))
            continue

        cmd = text
        key = (cmd, body)  # same file rewritten with new content is not a repeat
        if key == last_key:
            consecutive_failures += 1
        else:
            consecutive_failures = 0
            last_key = key

        words = cmd.split()
        name = words[0] if words else ""
        target = _norm(words[1]) if len(words) > 1 else ""
        is_block = name in BLOCK_CMDS
        is_py = target.endswith(".py")

        if (REQUIRE_RUN_BEFORE_PATCH and RUN_PYTHON and name == "patch_file" and is_py
                and target in unverified and target not in problems):
            result = (f"REFUSED: run_python {target} first and read what it prints, then patch it. "
                      f"(A patch has to answer a real error or check problem.)")
        elif is_block and key in done_ok:  # don't redo a finished write/patch
            result = ("REFUSED: you already ran this exact command successfully. "
                      "If the task is finished, reply: DONE: <answer>")
        else:
            result = run(cmd, body)
            if is_block and result.startswith("[exit 0]") and "problem(s) found" not in result:
                done_ok.add(key)
        print(f"tool>  {_preview(result)}")

        ok = result.startswith("[exit 0]")
        if is_block and target:
            if ok:
                refused_edit.pop(target, None)
                if is_py:
                    unverified.add(target)
                    last_exit.pop(target, None)
                    (problems.add if "problem(s) found" in result else problems.discard)(target)
            elif result.startswith(("REFUSED:", "ERROR:")):
                refused_edit[target] = f"{name} {target}"
        elif name == "run_python" and is_py and result.startswith("[exit"):
            code = int(result.split("]", 1)[0].split()[1]) if result.split("]", 1)[0].split()[1:] else 1
            seen = {target} | _local_imports(target)
            unverified -= seen
            last_exit[target] = code
            if code == 0:
                for f in seen:  # a clean run of main.py also exercised the helpers it imports
                    last_exit[f] = 0 if f in last_exit or f != target else last_exit.get(f, 0)

        if result.startswith(("REFUSED:", "ERROR:")):
            consecutive_failures += 1

        if consecutive_failures >= 3:
            return "(stopped: aborted due to consecutive failures)"

        # Nudge once per missed note; notes are what survives context pruning.
        nudge = "" if notes else "\n(Reminder: start your next reply with a one-line 'NOTE: <finding>'.)"
        if is_block and ok:
            if "problem(s) found" in result:
                nudge += "\n(Saved, but the check found problems. Fix them with patch_file, then run_python it.)"
            elif RUN_PYTHON and is_py:
                nudge += f"\n(Saved. Verify it now: run_python {words[1]}. Do not repeat this command.)"
            else:
                nudge += "\n(Saved. If the task is finished, reply: DONE: <answer>. Do not repeat this command.)"
        elif is_block and result.startswith("REFUSED:"):
            nudge += "\n(Nothing was changed. Fix the problem named above and send the command again.)"
        elif name == "run_python":
            if ok:
                nudge += "\n(It ran OK. If the output matches the task, reply DONE and say what you saw.)"
            elif result.startswith("[exit"):
                nudge += "\n(It failed. Read the error, fix the file with patch_file, then run_python again.)"
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
    elif len(sys.argv) == 2 and sys.argv[1] == "--ping":
        print(ping())
    elif len(sys.argv) >= 2:
        print(run(" ".join(sys.argv[1:])))
    else:
        print(__doc__)

