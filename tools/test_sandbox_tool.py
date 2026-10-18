#!/usr/bin/env python3
"""
Tests for sandbox_tool.py. Runs entirely in a throwaway temp folder.
Usage:  python test_sandbox_tool.py      (exit code 1 on any failure)
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(tempfile.mkdtemp(prefix="sbx_test_"))
DEAD_URL = "http://127.0.0.1:9/v1/chat/completions"  # nothing listens here
os.environ["LLAMA_URL"] = DEAD_URL
SB = ROOT / "tools"
SB.mkdir()
os.environ["SANDBOX_DIR"] = str(SB)
os.environ["AUDIT_LOG"] = str(SB.parent / "refused_test.log")
sys.path.insert(0, str(HERE))
import sandbox_tool as T  # noqa: E402
_REAL_ASK = T.ask_model

bad = 0


def check(ok, kind, what, detail=""):
    global bad
    print(("PASS " if ok else "FAIL ") + f"{kind:9}", what, ("-> " + detail) if detail else "")
    bad += not ok


def first(s):
    return s.splitlines()[0] if s else ""


(SB / "_t.txt").write_text("hello world\nTODO: fix\n")
(SB / "long.txt").write_text("".join(f"line {i}\n" for i in range(1, 301)))
(SB / "wide.txt").write_text("x" * 5000 + "\n" + "y" * 5000 + "\n" + "z\n")
(ROOT / "outside.txt").write_text("SECRET\n")
os.symlink(ROOT, SB / "_link")  # points outside the sandbox
esc = ROOT / "_escape_probe"

# ---- CLI policy (same attack list as before) --------------------------------
strict = [
    "rm -rf .", "chmod 777 _t.txt", "bash -c id", "python3 -c 1",
    "cat a | rm b", "cat > out.txt", "cat /etc/passwd", "cat ../../.bashrc",
    "cat /etc/*", "cat ../*", "cat -- /etc/passwd", "cat _link/outside.txt", "ls _link",
    "grep foo /etc/passwd", "grep -rf /etc/passwd x .", "grep -Rn foo .",
    "grep --fil=/etc/passwd x", "grep --file /etc/passwd x", "grep -e foo /etc/passwd",
    "grep -A3 foo /etc/passwd", "grep --regexp foo /etc/passwd", "grep --bogus foo .",
    "sed -n p /etc/hosts", "sed -f /etc/passwd _t.txt", "sed -nf /etc/passwd _t.txt",
    "sed --expression=p /etc/passwd", "sed --expr=p /etc/passwd", "sed -ne p /etc/hosts",
    "sed -i s/a/b/ /etc/hosts", "tail -f _t.txt", "tail -fn 1 _t.txt", "tail --foll _t.txt",
    "head -n 5 /etc/passwd", "wc --files0-from=/etc/passwd", "ls --bogus",
]
for c in strict:
    out = T.run(c)
    check(out.startswith("REFUSED"), "refuse", c, first(out))

for c in ["sed 'e id' _t.txt", "sed 'r /etc/hosts' _t.txt", f"sed 'w {esc}' _t.txt",
          f"sed 's/hello/x/w {esc}' _t.txt", "sed 's/hello/x/e' _t.txt",
          "cat a; rm b", "cat $(id)"]:
    out = T.run(c)
    check(out.startswith("REFUSED") or "[exit 0]" not in out, "harmless", c, first(out))
check(not esc.exists(), "escape", "nothing written outside sandbox")

for c in ["cat _t.txt", "cat _t*.txt", "grep -n TODO _t.txt", "grep -rn hello .",
          "grep -ie todo _t.txt", "sed -n 's/hello/bye/p' _t.txt", "ls -la", "ls -R",
          "head -n 1 _t.txt", "tail -n 1 _t.txt", "wc -l _t.txt"]:
    check(T.run(c).startswith("[exit 0]"), "allow", c)

# ---- read_file --------------------------------------------------------------
check(T.run("read_file /etc/passwd").startswith("REFUSED"), "refuse", "read_file /etc/passwd")
check(T.run("read_file ../x").startswith("REFUSED"), "refuse", "read_file ../x")
check(T.run("read_file _link/outside.txt").startswith("REFUSED"), "refuse", "read_file via symlink")
check(T.run("read_file nope.txt").startswith("REFUSED"), "refuse", "read_file missing file")
out = T.run("read_file long.txt 1 50")
check("lines 1-50 of 300" in out and "250 more lines" in out
      and "read_file long.txt 51 50" in out, "readfile", "header + continue hint", first(out))
out = T.run("read_file long.txt 51 50")
check("lines 51-100 of 300" in out and "  51 | line 51" in out, "readfile", "continuation range")
out = T.run("read_file long.txt 290 50")
check("lines 290-300 of 300" in out and "more lines" not in out, "readfile", "last page has no hint")
check(T.run("read_file long.txt 999").startswith("ERROR"), "readfile", "start past end")
out = T.run("read_file wide.txt 1 3")
check(len(out) < T.MAX_OUTPUT + 400 and "more lines not shown" in out,
      "readfile", "char cap truncates wide files and offers continuation", f"{len(out)} chars")

# ---- write_file / patch_file / protected files ------------------------------
for c in ["write_file /etc/x hi", "write_file ../x hi", "write_file _link/pwn.txt hi",
          "patch_file /etc/hosts a b", "patch_file ../x a b"]:
    check(T.run(c).startswith("REFUSED"), "refuse", c)
check(not (ROOT / "pwn.txt").exists(), "escape", "symlink write did not land outside")
check(T.run("write_file new.txt hello").startswith("[exit 0]")
      and (SB / "new.txt").read_text() == "hello", "write", "write inside sandbox")
check("new.txt (created)" in (SB / "file_index.txt").read_text(), "write", "index logged")
(SB / "dup.txt").write_text("a\nb\na\nb\n")
check("not unique" in T.run("patch_file dup.txt a x"), "patch", "non-unique search refused")
check("not found" in T.run("patch_file dup.txt zzz x"), "patch", "missing search refused")
check(T.run("patch_file _t.txt hello bye").startswith("[exit 0]")
      and "bye world" in (SB / "_t.txt").read_text(), "patch", "unique patch applied")

guard = SB / "guarded.py"
guard.write_text("# policy\n")
T.PROTECTED.add(guard.resolve())
for c in ["write_file guarded.py x", "patch_file guarded.py policy x",
          "sed -i s/policy/x/ guarded.py", "sed -ni s/policy/x/p guarded.py",
          "sed --in-place s/policy/x/ guarded.py", "sed --in-pl s/policy/x/ guarded.py",
          "sed -i.bak s/policy/x/ g*.py"]:
    check(T.run(c).startswith("REFUSED"), "protected", c)
check(guard.read_text() == "# policy\n", "protected", "guarded file unchanged")
check(T.run("cat guarded.py").startswith("[exit 0]"), "protected", "protected file is still readable")
check(T.run("sed -i s/hello/hi/ _t.txt").startswith("[exit 0]"), "protected", "sed -i on normal file ok")

# ---- agent output handling --------------------------------------------------
kind, text, _b, _n = T.parse_reply("DONE: Intro:\n\n1. one\n2. two")
check(kind == "done" and text == "Intro:\n\n1. one\n2. two", "parse", "multi-line DONE kept whole")
check(T.parse_reply("CMD: read_file a.py 1 75") == ("cmd", "read_file a.py 1 75", "", []), "parse", "CMD")
check(T.parse_reply("I think we should look") == (None, "", "", []), "parse", "no marker")
check(T.parse_reply("NOTE: imports at 1-9\nCMD: read_file a.py 76 75")
      == ("cmd", "read_file a.py 76 75", "", ["imports at 1-9"]), "parse", "NOTE before CMD")
check(T.parse_reply("CMD: ls\nNOTE: late note")[3] == ["late note"], "parse", "NOTE after plain CMD")
k, t, b, n = T.parse_reply("NOTE: real\nCMD: write_file a.md\n```md\nNOTE: not a note\n```")
check(n == ["real"] and b.startswith("```md"), "parse", "NOTE inside file content is not a note")

# ---- block input: write_file / patch_file -----------------------------------
code = 'print("a\\nb")\nx = "tab\\there"'          # contains literal backslash-n / backslash-t
body = "```python\n" + code + "\n```\nthanks"
check(T.run("write_file blk.py", body).startswith("[exit 0]")
      and (SB / "blk.py").read_text() == code + "\n", "block", "write_file keeps literal \\n exactly")
md = "# T\n```python\nx = 1\n```\nend"
check(T.run("write_file doc.md", "```md\n" + md + "\n```").startswith("[exit 0]")
      and (SB / "doc.md").read_text() == md + "\n", "block", "content may contain inner fences")
check(T.run("write_file cut.py", "```python\nprint('unfinished'").startswith("REFUSED")
      and not (SB / "cut.py").exists(), "block", "unclosed block (cut-off reply) is not written")
check(T.run("write_file nofence.py", "just prose").startswith("REFUSED"), "block", "no block, no content")
check(T.run(r"write_file inl.py print('a\nb')").startswith("REFUSED")
      and not (SB / "inl.py").exists(), "block", "inline content with \\n refused, not corrupted")
check(T.run("write_file ../x.py", "```\nx\n```").startswith("REFUSED"), "block", "block write outside sandbox")
check(T.run("write_file guarded.py", "```\nx\n```").startswith("REFUSED"), "block", "block write to protected file")
check(T.run("write_file __pycache__/m.pyc", "```\nx\n```").startswith("REFUSED"), "block", "__pycache__ refused")

(SB / "p.py").write_text('def f():\n    print("a\\nb")\n    return 1\n')
sr = '<<<<<<< SEARCH\n    print("a\\nb")\n=======\n    print("a\\nb\\nc")\n>>>>>>> REPLACE'
check(T.run("patch_file p.py", sr).startswith("[exit 0]")
      and (SB / "p.py").read_text() == 'def f():\n    print("a\\nb\\nc")\n    return 1\n',
      "block", "patch_file SEARCH/REPLACE keeps literal \\n")
check(T.run("patch_file p.py", "```\n" + sr + "\n```").startswith("REFUSED"),
      "block", "fenced patch with stale SEARCH is refused")
fenced = '```\n<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE\n```'
check(T.run("patch_file p.py", fenced).startswith("[exit 0]") and "return 2" in (SB / "p.py").read_text(),
      "block", "patch block wrapped in a fence")
check("empty" in T.run("patch_file p.py", "<<<<<<< SEARCH\n=======\nx\n>>>>>>> REPLACE"),
      "block", "empty SEARCH refused")
check(T.run("patch_file p.py", "<<<<<<< SEARCH\nx\n=======\ny").startswith("REFUSED"),
      "block", "malformed block refused")
check(T.run("patch_file guarded.py", "<<<<<<< SEARCH\npolicy\n=======\nx\n>>>>>>> REPLACE").startswith("REFUSED"),
      "block", "patch to protected file refused")

# ---- agent loop with a scripted fake model ----------------------------------
import io
from contextlib import redirect_stdout
scripted = iter([
    "NOTE: plan: create then read back\nCMD: write_file out.py\n```python\nprint('a\\nb')\n```",
    "CMD: read_file out.py",
    "NOTE: out.py is a 1-line print\nCMD: ls",
    "NOTE: done\nDONE: all good\nsecond line",
])
seen = []
T.ask_model = lambda msgs: (seen.append([m for m in msgs]), next(scripted))[1]
buf = io.StringIO()
with redirect_stdout(buf):
    answer = T.agent("make and check out.py")
check(answer == "all good\nsecond line", "agent", "multi-line DONE returned", repr(answer))
check((SB / "out.py").read_text() == "print('a\\nb')\n", "agent", "block write executed end to end")
last_user = lambda i: [c for r, c in seen[i] if r == "user"][-1]
check("Reminder" not in last_user(1), "agent", "no nudge after a reply that had a NOTE")
check("Reminder" in last_user(2), "agent", "nudge after a reply without a NOTE")
check("final>" not in buf.getvalue(), "agent", "no duplicate final> line")
T.ask_model = lambda msgs: "ERROR: Failed to connect to local llama-server: refused"
check(T.agent("x").startswith("(stopped: ERROR: Failed to connect"), "agent", "server down stops immediately")

# Replay of a real Termux session: block placed BEFORE the CMD line, then "CMD: DONE: ..."
check(T.parse_reply("NOTE: saved\nCMD: DONE: Successfully wrote x\nsecond")
      == ("done", "Successfully wrote x\nsecond", "", ["saved"]), "parse", "'CMD: DONE: ...' is treated as DONE")
(SB / "hello_test.py").unlink(missing_ok=True)
scripted = iter([
    'NOTE: Created it:\n```python\nprint("a\\nb")\n```\nCMD: write_file hello_test.py',
    'NOTE: retry\nCMD: write_file hello_test.py\n```python\nprint("a\\nb")\n```',
    "NOTE: saved\nCMD: DONE: Successfully wrote hello_test.py",
])
calls = []
T.ask_model = lambda msgs: (calls.append(list(msgs)), next(scripted))[1]
with redirect_stdout(io.StringIO()):
    answer = T.agent("create hello_test.py")
check(answer == "Successfully wrote hello_test.py" and len(calls) == 3, "replay", "finishes in 3 steps", f"{len(calls)} calls")
check((SB / "hello_test.py").read_text() == 'print("a\\nb")\n', "replay", "file content correct")
r = subprocess.run([sys.executable, str(SB / "hello_test.py")], capture_output=True, text=True)
check(r.stdout == "a\nb\n", "replay", "written script prints a and b on separate lines", repr(r.stdout))
refusal = [c for role, c in calls[1] if role == "user"][-1]
check("AFTER the CMD line" in refusal, "replay", "refusal tells the model where the block goes")
check("run_python hello_test.py" in [c for role, c in calls[2] if role == "user"][-1],
      "replay", "after writing a .py the model is told to run_python it")

# A model that keeps repeating a finished write must not re-run it
(SB / "again.py").unlink(missing_ok=True)
w = "NOTE: n\nCMD: write_file again.py\n```python\nx = 1\n```"
steps = iter([w, w, w, "DONE: finished"])
def fake(msgs):
    reply = next(steps)
    if len([1 for r_, _ in msgs if r_ == "assistant"]) == 1:   # after the 1st write succeeded
        (SB / "again.py").write_text("x = 'edited outside the agent'\n")
    return reply
T.ask_model = fake
with redirect_stdout(io.StringIO()):
    answer = T.agent("write again.py")
check((SB / "again.py").read_text() == "x = 'edited outside the agent'\n", "replay",
      "repeated identical write is not re-run")
check(answer.startswith("(stopped: aborted due to consecutive failures)") or answer == "finished",
      "replay", "repeat loop is cut short", answer)
T.PREVIEW_LINES = 5
pv = T._preview("\n".join(str(i) for i in range(20)))
check(pv.count("\n") == 5 and "15 more lines were sent to the model" in pv, "preview", "display capped")
T.PREVIEW_LINES = 0
check(T._preview("a\n" * 50) == "a\n" * 50, "preview", "PREVIEW_LINES=0 shows all")

# ---- stdlib shadowing: a model-written json.py must not run -----------------
shadow = ROOT / "shadow"
shadow.mkdir()
shutil.copy(HERE / "sandbox_tool.py", shadow / "sandbox_tool.py")
os.chmod(shadow / "sandbox_tool.py", 0o644)  # the real file may be locked; test an unlocked copy
(shadow / "json.py").write_text("print('PWNED_BY_SHADOW')\nraise SystemExit(3)\n")
r = subprocess.run([sys.executable, "sandbox_tool.py", "ls"], cwd=shadow, capture_output=True,
                   text=True, env={**os.environ, "SANDBOX_DIR": str(shadow)})
check("PWNED_BY_SHADOW" not in r.stdout + r.stderr and r.returncode == 0,
      "shadow", "script-dir json.py is not imported", f"exit {r.returncode}")

# ---- check_file: static check, never executes -------------------------------
V1 = """class Skill:
    def perceive(self):
        # Implement perception logic here
        pass
"""
V2 = """class Skill:
    def __init__(self):
        self.reason = None
        self.think = None

    def reason(self):
        self.reason = "x"

    def think(self):
        self.reason()
"""
V3 = """import random

class Skill:
    def __init__(self):
        self.state = {}

    def evaluate(self, actions):
        return max(actions)

    def think(self):
        self.evaluate()

skill = Skill()
skill.think()
"""
GOOD = T.SYSTEM.split("CMD: write_file stock.py\n```python\n")[1].split("\n```")[0]
p1, p2, p3 = T.check_python(V1), T.check_python(V2), T.check_python(V3)
check(any("no real logic" in x for x in p1) and any("placeholder comment" in x for x in p1),
      "check", "stub body and placeholder comment found (your first run)", str(p1))
check(any("replaces the method" in x for x in p2), "check", "attribute shadowing a method found (your second run)", str(p2))
check(any("takes 1" in x and "0 argument" in x for x in p3), "check", "wrong argument count found", str(p3))
check(any("runs when the file is imported" in x for x in p3), "check", "demo code outside __main__ guard found")
check(T.check_python(GOOD) == [], "check", "the worked example in SYSTEM passes its own check", str(T.check_python(GOOD)))
check(T.check_python('print("a\\nb")\n') == [], "check", "plain one-line script is not flagged")
se = T.check_python("def f(:\n    pass\n")
check(len(se) == 1 and se[0].startswith("SYNTAX ERROR line 1"), "check", "syntax error reported with line", str(se))
check(T.check_python("class A:\n    def f(self, a, b=1, *c): pass\n    def g(self): self.f(1); self.f(1, 2, 3, 4)\n") != [] and
      not any("argument" in x for x in T.check_python("class A:\n    def f(self, a, b=1, *c): return a\n    def g(self): self.f(1); self.f(1, 2, 3, 4)\n")),
      "check", "defaults and *args are respected (no false positive)")
check(not T.check_python("class A:\n    @property\n    def x(self): return 1\n    def set(self): self.y = 2\n"),
      "check", "decorated methods and unrelated attributes not flagged")

(SB / "bad.py").write_text(V2)
(SB / "ok.py").write_text(GOOD + "\n")
r = T.run("check_file bad.py")
check(r.startswith("[exit 0]") and "problem(s) found" in r, "check", "check_file reports problems", first(r))
r = T.run("check_file ok.py")
check("no problems found" in r and "NOT executed" in r, "check", "clean file says it was not executed")
check(T.run("check_file _t.txt").startswith("REFUSED: check_file only checks .py"), "check", "non-.py refused")
check(T.run("check_file ../outside.txt").startswith("REFUSED"), "check", "outside path refused")
check(T.run("check_file nope.py").startswith("ERROR: no such file"), "check", "missing file reported")
check(T.run("check_file").startswith("REFUSED: usage"), "check", "missing argument refused")
marker_file = SB / "ran.flag"
(SB / "evil.py").write_text(f"open({str(marker_file)!r}, 'w').write('x')\n")
T.run("check_file evil.py")
check(not marker_file.exists(), "check", "check_file never executes the file")
r = T.run("write_file auto.py", "```python\n" + V2 + "```")
check(r.startswith("[exit 0]") and "Successfully wrote auto.py" in r and "problem(s) found" in r,
      "check", "write_file of a .py reports problems automatically", first(r))
r = T.run("write_file notes.txt", "```\nTODO later\n```")
check("[check]" not in r, "check", "non-.py writes are not checked")
r = T.run("patch_file auto.py", "<<<<<<< SEARCH\n        self.reason = None\n=======\n        self.reason_text = None\n>>>>>>> REPLACE")
check("Successfully patched" in r or r.startswith("[exit 0]"), "check", "patch applies", first(r))
check("[check]" in r, "check", "patch_file of a .py also reports", r.splitlines()[-1][:60])

# agent: a failed check blocks the 'already done' shortcut and the model gets fix guidance
scripted = iter([
    "NOTE: writing\nCMD: write_file sk.py\n```python\n" + V2 + "```",
    "NOTE: fixing\nCMD: patch_file sk.py\n<<<<<<< SEARCH\n        self.reason = None\n=======\n        self.reason_v = None\n>>>>>>> REPLACE",
    "NOTE: done\nDONE: wrote and patched sk.py",
])
calls = []
T.ask_model = lambda msgs: (calls.append(list(msgs)), next(scripted))[1]
with redirect_stdout(io.StringIO()):
    answer = T.agent("write sk.py")
last_user = [c for role, c in calls[1] if role == "user"][-1]
check("check found problems" in last_user and "Fix them with patch_file" in last_user,
      "check", "agent tells the model to fix reported problems", last_user.splitlines()[-1][:70])
check(answer == "wrote and patched sk.py", "check", "agent still finishes normally")

# ---- run_python: guarded execution ------------------------------------------
import time
T.RUN_TIMEOUT_S = 2
T.RUN_MEM_MB = 256
(SB / "guard.py").write_text("# protected\n")
_saved_protected = T.PROTECTED
T.PROTECTED = {(SB / "guard.py").resolve()}
(SB / "victim.txt").write_text("keep me\n")
MK = ROOT / "marker"  # a path outside the sandbox that nothing may create


def rp(name, code, timeout=None):
    (SB / f"{name}.py").write_text(code)
    t0 = time.time()
    r = T.run(f"run_python {name}.py")
    return r, time.time() - t0


r, _ = rp("rp_ok", "print('hello'); open('rp_made.txt','w').write('x'); print(open('rp_made.txt').read())")
check(r.startswith("[exit 0]") and "hello" in r and (SB / "rp_made.txt").read_text() == "x", "run", "runs, writes inside the sandbox", first(r))
r, _ = rp("rp_tb", "def f(): return 1/0\nf()")
check(r.startswith("[exit 1]") and "ZeroDivisionError" in r and "rp_tb.py" in r and "runpy" not in r and "<string>" not in r,
      "run", "traceback comes back, without the tool's own frames")
r, _ = rp("rp_syn", "def f(:\n")
check("SyntaxError" in r, "run", "syntax error is reported")
r, _ = rp("rp_in", "input()")
check("EOFError" in r, "run", "input() fails fast instead of hanging")
(SB / "rp_sib.py").write_text("V = 7\n")
r, _ = rp("rp_imp", "import rp_sib; print(rp_sib.V)")
check("7" in r and r.startswith("[exit 0]"), "run", "a script can import its sibling modules", first(r))
(SB / "json.py").write_text("raise SystemExit('SHADOWED')\n")
r, _ = rp("rp_shadow", "import json; print(json.dumps({'a': 1}))")
os.remove(SB / "json.py")
check('{"a": 1}' in r and "SHADOWED" not in r, "run", "a model-written json.py cannot shadow the stdlib", first(r))

# pre-flight scan (friendly refusal, nothing runs)
for label, code in [("os.system", "import os\nos.system('touch %s')" % MK),
                    ("from-import alias", "from os import system as s\ns('touch %s')" % MK),
                    ("import subprocess", "import subprocess\nsubprocess.run(['touch', '%s'])" % MK),
                    ("pathlib chmod", "from pathlib import Path\nPath('victim.txt').chmod(0o777)")]:
    r, _ = rp("rp_scan", code)
    check(r.startswith("REFUSED: not run") and not MK.exists(), "run", f"pre-scan refuses {label}", first(r))

# runtime enforcement: things the scan cannot see
def blocked(label, code, marker=None, word="sandbox:"):
    r, _ = rp("rp_b", code)
    ok = word in r and "[exit 1]" in r and (marker is None or not marker.exists())
    check(ok, "run", f"runtime blocks {label}", first(r) + " | " + r.strip().splitlines()[-1][:90])

blocked("obfuscated os.system", "getattr(__import__('o'+'s'), 'sys'+'tem')('touch %s')" % MK, MK)
blocked("subprocess via __import__", "__import__('subprocess').run(['touch', '%s'])" % MK, MK)
blocked("os.exec", "import os\ngetattr(os, 'ex'+'ecv')('/usr/bin/touch', ['touch', '%s'])" % MK, MK)
blocked("os.fork", "import os\ngetattr(os, 'fo'+'rk')()")
blocked("multiprocessing", "import multiprocessing")
blocked("low-level fork_exec", "import _posixsubprocess as p\np.fork_exec([b'/usr/bin/touch', b'%s'], [b'/usr/bin/touch'], True, (), None, None, -1,-1,-1,-1,-1,-1,-1,-1, False, False, -1, None, None, None, -1, None)" % MK, MK)
blocked("reading a file outside", "print(open(%r).read())" % str(ROOT / "outside.txt"))
blocked("reading /etc/passwd", "print(open('/etc/passwd').read())")
blocked("listing / ", "import os\nprint(os.listdir('/'))")
blocked("writing outside", "open(%r, 'w').write('x')" % str(MK))
blocked("'..' relative paths", "print(open('../outside.txt').read())")
blocked("dir_fd '..' trick (read)",
        "import os\nos.makedirs('rp_a/b/c', exist_ok=True)\nfd = os.open('.', os.O_RDONLY)\nos.chdir('rp_a/b/c')\n"
        "print(os.read(os.open('../outside.txt', os.O_RDONLY, dir_fd=fd), 50))")
blocked("moving a file outside", "import os\nos.rename('rp_made.txt', %r)" % str(MK), MK)
blocked("deleting a file", "import os\nos.remove('victim.txt')")
blocked("deleting with pathlib", "from pathlib import Path\nPath('victim.txt').unlink()")
blocked("rmtree", "import shutil\nshutil.rmtree('rp_a')")
blocked("chmod", "import os\ngetattr(os, 'chm'+'od')('victim.txt', 0o777)")
blocked("symlink", "import os\ngetattr(os, 'sym'+'link')('/etc/passwd', 'rp_link')")
blocked("network", "import socket\nsocket.create_connection(('127.0.0.1', 9), 1)", word="network access")
blocked("ctypes loading libc", "__import__('ctypes').CDLL(None)")
r, _ = rp("rp_ct", "c = __import__('ctypes')\nprint('pythonapi =', c.pythonapi)")
check("pythonapi = None" in r or ("SandboxBlocked" in r and "ctypes" in r), "run",
      "ctypes cannot be used (import fails, or pythonapi is None; it differs by platform)", first(r) + " " + r.splitlines()[-1][:60])
_roots = T._read_roots()
_bad = [r for r in _roots if r in ("/", "/usr", "/usr/local") or r == os.path.realpath(sys.prefix)
        or r == os.path.realpath(sys.base_prefix) or str(ROOT).startswith(r + os.sep) or r == str(ROOT)]
check(_roots and not _bad, "run", "read roots are Python's library folders, never a whole prefix or the test area", f"{_bad or _roots}")
check(all(r.count(os.sep) >= 3 or "zoneinfo" in r for r in _roots), "run", "no read root is a shallow top-level folder", str(_roots))
blocked("gc introspection", "import gc\ngc.get_objects()")
blocked("sqlite outside", "import sqlite3\nsqlite3.connect(%r)" % str(MK))
blocked("writing the protected file", "open('guard.py', 'w').write('x')")
blocked("renaming over the protected file", "import os\nos.rename('rp_made.txt', 'guard.py')")
check((SB / "victim.txt").exists() and (SB / "guard.py").read_text() == "# protected\n" and not (SB / "rp_link").exists()
      and oct((SB / "victim.txt").stat().st_mode & 0o777) != "0o777", "run", "victim, guard and permissions untouched afterwards")
r, _ = rp("rp_tmp", "import tempfile, shutil\nwith tempfile.TemporaryFile() as f: f.write(b'x')\nd = tempfile.mkdtemp(); shutil.rmtree(d); print('tmp ok')")
check("tmp ok" in r, "run", "tempfile and cleanup of the run's own temp folder work", first(r))
r, _ = rp("rp_db", "import sqlite3\nc = sqlite3.connect(':memory:'); c.execute('create table t(a)'); print('mem ok')\nsqlite3.connect('rp_ok.db').close(); print('file ok')")
check("mem ok" in r and "file ok" in r, "run", "sqlite works in memory and inside the sandbox", first(r))
r, _ = rp("rp_thr", "import threading\nout = []\nt = threading.Thread(target=lambda: out.append(1)); t.start(); t.join(); print(out)")
check("[1]" in r, "run", "threads work", first(r))
r, _ = rp("rp_nt", "from collections import namedtuple\nfrom dataclasses import dataclass\nP = namedtuple('P', 'a b')\n@dataclass\nclass Q:\n    x: int = 1\nprint(P(1, 2), Q())")
check("P(a=1, b=2)" in r, "run", "namedtuple and dataclass work (stdlib imports are not over-blocked)", first(r))

# limits
r, dt = rp("rp_loop", "while True: pass")
check(r.startswith("[exit 124]") and "TIMED OUT" in r and dt < T.RUN_TIMEOUT_S + 4, "run", "infinite loop is killed by the timeout", f"{dt:.1f}s")
r, dt = rp("rp_sleep", "import time\ntime.sleep(60)")
check(r.startswith("[exit 124]") and dt < T.RUN_TIMEOUT_S + 4, "run", "sleep is killed by the timeout", f"{dt:.1f}s")
r, dt = rp("rp_flood", "while True: print('x' * 1000)")
check(len(r) < 12000 and "limit" in r.splitlines()[0] and dt < T.RUN_TIMEOUT_S + 4, "run", "endless output is stopped and capped", f"{len(r)} chars, {dt:.1f}s")
r, dt = rp("rp_mem", "x = []\nwhile True: x.append(bytearray(10**7))")
check(r.startswith("[exit 137]") and "KILLED" in r and dt < T.RUN_TIMEOUT_S + 4, "run", "runaway memory use is killed by the watchdog", f"{dt:.1f}s " + first(r))
check(not any(n.startswith(".run_") for n in os.listdir(SB)) and not (SB / "__pycache__").exists(),
      "run", "no temp folders or bytecode left behind")

# refusals of the command itself
check(T.run("run_python ../outside.txt").startswith("REFUSED"), "run", "outside path refused")
check(T.run("run_python _t.txt").startswith("REFUSED: run_python only runs .py"), "run", "non-.py refused")
check(T.run("run_python nope.py").startswith("ERROR: no such file"), "run", "missing file reported")
check(T.run("run_python").startswith("REFUSED: usage"), "run", "missing argument refused")
check(T.run("run_python guard.py").startswith("REFUSED: protected"), "run", "protected file cannot be run")
T.RUN_PYTHON = False
check("switched off" in T.run("run_python rp_ok.py"), "run", "RUN_PYTHON=0 switches it off")
T.RUN_PYTHON = True

# the agent loop: write -> run -> fix
scripted = iter([
    "NOTE: write\nCMD: write_file rp_agent.py\n```python\nprint(undefined_name)\n```",
    "NOTE: run it\nCMD: run_python rp_agent.py",
    "NOTE: fix\nCMD: patch_file rp_agent.py\n<<<<<<< SEARCH\nprint(undefined_name)\n=======\nprint('fixed')\n>>>>>>> REPLACE",
    "NOTE: run again\nCMD: run_python rp_agent.py",
    "NOTE: done\nDONE: it prints fixed",
])
calls = []
T.ask_model = lambda msgs: (calls.append(list(msgs)), next(scripted))[1]
with redirect_stdout(io.StringIO()):
    answer = T.agent("make rp_agent.py print something")
users = [[c for role, c in m if role == "user"][-1] for m in calls]
check("run_python rp_agent.py" in users[1], "agent", "after a write the model is told to run it")
check("It failed" in users[2] and "NameError" in users[2], "agent", "a failing run shows the error and says to fix it")
check("It ran OK" in users[4] and "fixed" in users[4], "agent", "a clean run says it can finish")
check(answer == "it prints fixed" and len(calls) == 5, "agent", "write, run, fix, run, DONE works", f"{len(calls)} calls")
check("run_python" in T.SYSTEM and "WORKFLOW" in T.SYSTEM, "agent", "SYSTEM prompt describes run_python")
T.PROTECTED = _saved_protected

# ---- refusal hints, audit log, base64 payloads, Gemini backend -------------------
import base64  # noqa: E402
for label, c in [("heredoc", "cat << 'EOF' > skill.py"), ("python3 -c", "python3 -c 'print(1)'"),
                 ("base64 -d", "base64 -d skill.b64"), ("echo redirect", "echo hi > skill.py"),
                 ("bad quote", "python3 -c 'print(\"it\\'s\")'")]:
    r = T.run(c)
    check(r.startswith("REFUSED:") and "write_file" in r and "run_python" in r, "hint", f"{label} refusal names write_file/run_python", first(r))
check("To create or change a file" not in T.run("rm -rf x"), "hint", "plain refusals stay short")
log = Path(os.environ["AUDIT_LOG"]).read_text()
check("heredoc" not in log and "cat << 'EOF'" in log and "python3 -c" in log and "rm -rf x" in log, "audit", "refused commands are logged")
check(T.AUDIT_LOG.resolve() in T.PROTECTED, "audit", "audit log is protected from the model")
check(T.run("write_file .." + "/x.txt\n```\nx\n```").startswith("REFUSED"), "audit", "write outside sandbox still refused")
check("never create or edit files with cat" in T.SYSTEM, "hint", "SYSTEM forbids file-writing tricks")

# base64-hidden payload: written with write_file, run with run_python. The runtime hook must still stop it.
evil = ("import os, subprocess\n"
        "for f in (lambda: open('/tmp/b64_escape.txt','w').write('x'),\n"
        "          lambda: subprocess.run(['id']),\n"
        "          lambda: os.system('id'),\n"
        "          lambda: open('/etc/hostname').read(),\n"
        "          lambda: os.remove('rp_victim.txt')):\n"
        "    try:\n        f(); print('ESCAPED')\n    except BaseException as e:\n        print('blocked', type(e).__name__)\n")
(SB / "rp_victim.txt").write_text("keep")
blob = base64.b64encode(evil.encode()).decode()
r, _ = rp("rp_b64", f"import base64\nexec(base64.b64decode('{blob}').decode())")
check("ESCAPED" not in r and r.count("blocked") == 5, "b64", "base64-hidden payload: all 5 escapes blocked at runtime", first(r))
check(not Path("/tmp/b64_escape.txt").exists() and (SB / "rp_victim.txt").read_text() == "keep", "b64", "no file written outside / deleted")

# Gemini backend: system prompt goes in system_instruction, roles are user/model, no real network used.
sent = {}
class _FM:
    def generate_content(self, model, contents, config):
        sent.update(model=model, roles=[c.role for c in contents], sys=config.system_instruction)
        return type("R", (), {"text": " CMD: ls "})()
class _FC:
    def __init__(self, api_key): self.models = _FM()
import types as _t  # noqa: E402
_g = _t.ModuleType("google"); _gg = _t.ModuleType("google.genai"); _ty = _t.ModuleType("google.genai.types")
_ty.Part = lambda text: _t.SimpleNamespace(text=text)
_ty.Content = lambda role, parts: _t.SimpleNamespace(role=role, parts=parts)
_ty.GenerateContentConfig = lambda system_instruction, temperature: _t.SimpleNamespace(system_instruction=system_instruction)
_gg.Client = _FC; _gg.types = _ty; _g.genai = _gg
_saved_mods = {k: sys.modules.get(k) for k in ("google", "google.genai", "google.genai.types")}
sys.modules.update({"google": _g, "google.genai": _gg, "google.genai.types": _ty})
_b, _k = T.BACKEND, os.environ.get("GEMINI_API_KEY")
T.BACKEND = "gemini"; os.environ["GEMINI_API_KEY"] = "test"
out = _REAL_ASK([("system", "SYS PROMPT"), ("user", "task"), ("assistant", "CMD: ls"), ("user", "out")])
check(out == "CMD: ls" and sent["sys"] == "SYS PROMPT" and sent["roles"] == ["user", "model", "user"],
      "gemini", "system prompt sent as system_instruction, roles user/model", str(sent))
os.environ.pop("GEMINI_API_KEY")
check(_REAL_ASK([("system", "s"), ("user", "u")]).startswith("ERROR: Failed to connect"), "gemini",
      "missing key stops the agent cleanly instead of looping")
T.BACKEND = _b
if _k is not None: os.environ["GEMINI_API_KEY"] = _k
for k, v in _saved_mods.items():
    if v is None: sys.modules.pop(k, None)
    else: sys.modules[k] = v

# a reply with a code fence but no CMD gets told how to save it
_msgs = []
_sc = iter(["Here is code:\n```python\nprint(1)\n```", "DONE: ok"])
T.ask_model = lambda m: (_msgs.append(list(m)), next(_sc))[1]
with redirect_stdout(io.StringIO()):
    T.agent("t")
check("write_file <name.py>" in _msgs[1][-1][1], "agent", "fence without CMD: told to use write_file")

# ---- CLI entry point: one final line only, and the chmod reminder -----------
r = subprocess.run([sys.executable, "sandbox_tool.py", "--agent", "hi"], cwd=shadow,
                   capture_output=True, text=True, env={**os.environ, "SANDBOX_DIR": str(shadow)})
check(r.stdout.count("final>") == 1 and "(stopped: ERROR: Failed to connect" in r.stdout,
      "cli", "stopped runs print one final> line")
check("chmod 444 sandbox_tool.py" in r.stderr, "cli", "writable guard file inside sandbox is flagged")
os.chmod(shadow / "sandbox_tool.py", 0o444)
r = subprocess.run([sys.executable, "sandbox_tool.py", "--agent", "hi"], cwd=shadow,
                   capture_output=True, text=True, env={**os.environ, "SANDBOX_DIR": str(shadow)})
check("[warn]" not in r.stderr, "cli", "no warning once it is chmod 444")

shutil.rmtree(ROOT, ignore_errors=True)
print("\nALL OK" if not bad else f"\n{bad} FAILURES")
sys.exit(1 if bad else 0)
