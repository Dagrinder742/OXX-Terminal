#!/usr/bin/env python3
"""Checks for bench.py itself, using a fake model server (no real model needed).
Run:  python test_bench.py      -> must end with ALL OK
It copies the kit to a temp folder first, so your real runs/ and reports/ are never touched."""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = Path(os.environ.get("TOOLS") or HERE.parent / "src")
if not (TOOLS / "sandbox_tool.py").is_file():
    sys.exit(f"STOP: sandbox_tool.py not found (set TOOLS=<folder>), looked in {TOOLS}")

bad = 0


def check(ok, what, detail=""):
    global bad
    bad += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {what}" + (f"  -> {detail}"[:200] if (detail and not ok) else ""))


def sel(name):
    return (HERE / "tasks" / name / "selftest" / "good.py").read_text()


# ---- fake llama-server: scripted replies, chosen by the task text in the first user message --------
BAD_STACK = (HERE / "tasks" / "stack" / "selftest" / "bad_no_error.py").read_text()


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        b = json.dumps({"data": [{"id": "stub-model"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = req["messages"]
        first = next(m["content"] for m in msgs if m["role"] == "user")
        step = sum(m["role"] == "assistant" for m in msgs)
        P = lambda fn, code: [f"NOTE: write it\nCMD: write_file {fn}\n```python\n{code}```",
                              f"NOTE: run it\nCMD: run_python {fn}", "NOTE: finished\nDONE: it works"]
        if "wc.py" in first:
            plan = P("wc.py", sel("wordcount"))
        elif "stack.py" in first:
            plan = P("stack.py", BAD_STACK)          # will FAIL verification but the model will say DONE
        elif "total.py" in first:
            plan = P("total.py", sel("csv_total"))
        elif "average.py" in first:
            plan = ["NOTE: look\nCMD: read_file average.py",
                    "NOTE: fix empty\nCMD: patch_file average.py\n<<<<<<< SEARCH\ndef average(numbers):\n    total = 0\n=======\n"
                    "def average(numbers):\n    if not numbers:\n        return 0.0\n    total = 0\n>>>>>>> REPLACE",
                    "NOTE: fix median\nCMD: patch_file average.py\n<<<<<<< SEARCH\n    s = numbers\n    s.sort()\n    mid = len(s) // 2\n"
                    "    if len(s) % 2 == 0:\n        return s[mid]\n=======\n    s = sorted(numbers)\n    mid = len(s) // 2\n"
                    "    if len(s) % 2 == 0:\n        return (s[mid - 1] + s[mid]) / 2\n>>>>>>> REPLACE",
                    "NOTE: run\nCMD: run_python average.py", "NOTE: finished\nDONE: fixed"]
        else:
            plan = P("nothing.py", "print('x')\n")
        reply = plan[min(step, len(plan) - 1)]
        body = json.dumps({"choices": [{"message": {"role": "assistant", "content": reply}}],
                           "timings": {"prompt_n": 10, "prompt_per_second": 5.0, "predicted_n": 20,
                                       "predicted_per_second": 2.5}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/v1/chat/completions"

tmp = Path(tempfile.mkdtemp(prefix="bench_test_"))
kit = tmp / "kit"
shutil.copytree(HERE, kit, ignore=shutil.ignore_patterns("runs", "work", "reports", "exports", "logs", "__pycache__", "misc"))
tools = tmp / "tools"
tools.mkdir()
shutil.copy(TOOLS / "sandbox_tool.py", tools)
env = dict(os.environ, LLAMA_URL=URL, BACKEND="local", LLAMA_STREAM="0", TOOLS=str(tools))
env.pop("RUN_PYTHON", None)


def bench(*args, **kw):
    return subprocess.run([sys.executable, str(kit / "bench.py"), *args], capture_output=True, text=True, env=env,
                          timeout=300, **kw)


# ---- 1. verifiers ------------------------------------------------------------------------------------
r = bench("selftest")
check(r.returncode == 0 and "ALL VERIFIERS BEHAVE" in r.stdout, "selftest: every verifier passes its good file and fails its bad ones", r.stdout[-300:] + r.stderr[-200:])
r = bench("list")
check(all(t in r.stdout for t in ("wordcount", "stack", "bugfix", "csv_total", "skill_v4", "skill_v42")), "list shows all 6 tasks")

# ---- 2. a full run against the fake server ------------------------------------------------------------
r = bench("run", "-t", "wordcount", "stack", "-n", "2", "--label", "Stub Test", "--note", "first note")
check(r.returncode == 0, "run exits 0", r.stdout[-400:] + r.stderr[-400:])
sess = sorted((kit / "runs").glob("*stub-test*"))[0]
check(sess is not None and "stub-test" in sess.name, "session folder is named from the label", str(sess))
meta = json.loads((sess / "meta.json").read_text())
check(meta["model"] == "stub-model" and meta["runs_per_task"] == 2 and len(meta["tool_sha"]) == 10 and len(meta["system_sha"]) == 10
      and set(meta["tasks"]) == {"wordcount", "stack"}, "meta records model, hashes, tasks", str(meta)[:200])
res = {(p.parts[-3], p.parts[-2]): json.loads(p.read_text()) for p in sess.glob("*/run_*/result.json")}
check(len(res) == 4, "4 runs captured", str(list(res)))
w1, s1 = res[("wordcount", "run_1")], res[("stack", "run_1")]
check(w1["verify"] == "PASS" and w1["passed"] == w1["total"] == 13 and w1["ended"] == "done" and w1["steps"] == 3, "wordcount run is verified PASS", str(w1))
check(w1["cmds"] == {"write_file": 1, "run_python": 1, "DONE": 1}, "commands counted from the transcript", str(w1["cmds"]))
check(w1["gen_tok_s"] is not None, "speed parsed from the [llm] lines", str(w1["gen_tok_s"]))
check(s1["verify"] == "FAIL" and s1["ended"] == "done" and s1["claimed_false"] is True, "false DONE is detected (model said DONE, verifier said FAIL)", str(s1))
check(any("raises IndexError" in c for c in s1["failed_checks"]), "failed check names are recorded", str(s1["failed_checks"]))
rd = sess / "wordcount" / "run_1"
check((rd / "wc.py").is_file() and (rd / "run.log").is_file() and (rd / "verify.log").is_file() and (rd / "transcript.json").is_file(),
      "run folder has the output file, run.log, verify.log, transcript.json")
tr = json.loads((rd / "transcript.json").read_text())
check(tr["messages"][0]["role"] == "system" and tr["messages"][1]["role"] == "user" and tr["result"] and not tr["stopped"],
      "transcript has system, user, replies and the result")
check(not list((kit / "work").glob("*")), "per-run sandbox folders are cleaned up")
rep = (kit / "reports" / f"{sess.name}.txt").read_text()
for what, needle in (("setup block", "SETUP"), ("summary row", "wordcount"), ("false-DONE flagged", "CLAIMED DONE BUT FAILED"),
                     ("your notes section", "first note"), ("run log embedded", "model> NOTE: write it"),
                     ("model's file embedded", "def count_words"), ("verify log embedded", "VERIFY: PASS (13/13)")):
    check(needle in rep, f"report contains: {what}")
import re as _re
check(_re.search(r"wordcount\s+2/2\s+0", rep) and _re.search(r"stack\s+0/2\s+2", rep), "report summary shows pass counts and false-DONE counts")

# ---- 2b. tasks that need fixture files: csv_total (reads sales.csv) and bugfix (patch_file workflow) --------
r = bench("run", "-t", "csv_total", "bugfix", "-n", "1", "--label", "fixtures")
fx = sorted((kit / "runs").glob("*fixtures*"))[-1]
for t in ("csv_total", "bugfix"):
    rr = json.loads((fx / t / "run_1" / "result.json").read_text())
    check(rr["verify"] == "PASS" and rr["ended"] == "done", f"{t}: fixtures were in the sandbox and the run verified PASS", str(rr)[:300] + (fx / t / "run_1" / "run.log").read_text()[-600:])
rr = json.loads((fx / "bugfix" / "run_1" / "result.json").read_text())
check(rr["cmds"].get("patch_file") == 2 and rr["cmds"].get("read_file") == 1, "bugfix run used read_file and patch_file as scripted", str(rr["cmds"]))

# ---- 3. notes, report rebuild, show, stats, export ---------------------------------------------------
r = bench("note", "model keeps forgetting the import")
check(r.returncode == 0, "note (session)", r.stderr)
r = bench("note", "this one looked odd", "--run", "stack/1")
check(r.returncode == 0, "note (one run)", r.stderr)
r = bench("note", "x", "--run", "stack/99")
check(r.returncode != 0 and "no run" in r.stderr, "note on a missing run is refused")
r = bench("report", "--detail", "fail")
rep2 = (kit / "reports" / f"{sess.name}.txt").read_text()
check("model keeps forgetting the import" in rep2 and "this one looked odd" in rep2, "rebuilt report picks up new notes")
check("def count_words" not in rep2 and "def pop" in rep2, "--detail fail leaves out passing runs' bodies and keeps failing ones")
r = bench("show", "wordcount/1")
check("model> NOTE: write it" in r.stdout and "def count_words" in r.stdout and "VERIFY: PASS" in r.stdout, "show prints log + file + verify like your cat chain")
r = bench("stats")
check("stub-test" in r.stdout and "wordcount 2/2" in r.stdout and "stack 0/2" in r.stdout, "stats shows pass rates", r.stdout)
r = bench("export", "-o", str(tmp / "out.jsonl"))
rows = [json.loads(l) for l in (tmp / "out.jsonl").read_text().splitlines()]
check(sorted(r["task"] for r in rows) == ["bugfix", "csv_total", "wordcount"] and rows[0]["messages"][-1]["role"] == "assistant",
      "export keeps verified passes only (2 identical wordcount runs de-duplicated to 1, stack FAILs excluded)", str([r["task"] for r in rows]))
check("WARNING" in r.stdout, "export prints the not-a-training-set warning")
r = bench("export", "-o", str(tmp / "out2.jsonl"), "--no-system")
rows2 = [json.loads(l) for l in (tmp / "out2.jsonl").read_text().splitlines()]
check(rows2 and rows2[0]["messages"][0]["role"] == "user", "--no-system drops the system prompt")

# ---- 4. honesty and safety -------------------------------------------------------------------------
r = bench("run", "-t", "nosuchtask")
check(r.returncode != 0 and "no task called" in r.stderr, "unknown task stops with a clear message")
shutil.copy(kit / "tasks" / "wordcount" / "prompt.txt", tmp / "keep_prompt.txt")
(kit / "tasks" / "wordcount" / "prompt.txt").write_text("")
before = len(list((kit / "runs").glob("*")))
r = bench("run", "-t", "wordcount", "-n", "1")
check(r.returncode != 0 and "Nothing was run" in r.stderr and len(list((kit / "runs").glob("*"))) == before,
      "an empty prompt stops BEFORE any run (no fake FAILs)", r.stderr)
shutil.copy(tmp / "keep_prompt.txt", kit / "tasks" / "wordcount" / "prompt.txt")
# server down: runs are recorded as failures with the reason, never as passes
env_dead = dict(env, LLAMA_URL="http://127.0.0.1:9/v1/chat/completions")
r = subprocess.run([sys.executable, str(kit / "bench.py"), "run", "-t", "wordcount", "-n", "1", "--label", "dead"],
                   capture_output=True, text=True, env=env_dead, timeout=120)
dead = sorted((kit / "runs").glob("*dead*"))[-1]
rr = json.loads(next(dead.glob("wordcount/run_1/result.json")).read_text())
check(rr["verify"] == "FAIL" and "stopped" in rr["ended"] and not rr["claimed_false"] and "no output file" in (dead / "wordcount/run_1/verify.log").read_text(),
      "server down: recorded as FAIL / stopped, not as a false DONE", str(rr)[:200])
# a model-written file with blocked constructs is NOT executed by the verifier
import importlib.util
spec = importlib.util.spec_from_file_location("bench_mod", kit / "bench.py")
bm = importlib.util.module_from_spec(spec); spec.loader.exec_module(bm)
evil = tmp / "evil.py"
marker = tmp / "pwned.txt"
evil.write_text(f"import os\nos.system('echo hi > {marker}')\n")
tool = bm.load_tool(tools)
v, text, p, n = bm.judge(bm.all_tasks()["wordcount"], evil, tool)
check(v == "FAIL" and "did NOT run" in text and not marker.exists(), "verifier refuses to execute files with blocked constructs", text[:150])
# a model-written file that hangs is stopped by the verifier's timeout
bm.VERIFY_TIMEOUT = 3
hang = tmp / "hang.py"
hang.write_text("while True:\n    pass\n")
v, text, p, n = bm.judge(bm.all_tasks()["wordcount"], hang, None)
check(v == "FAIL", "a hanging file cannot hang the verifier", text[:150])

if os.environ.get("KEEP"):
    print("kept:", tmp)
else:
    shutil.rmtree(tmp, ignore_errors=True)
print("\nALL OK" if not bad else f"\n{bad} CHECK(S) FAILED")
sys.exit(1 if bad else 0)
