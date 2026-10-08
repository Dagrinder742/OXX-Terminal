#!/usr/bin/env python3
"""
Rogue Agent Simulator
---------------------
A fully simulated autonomous swarm: no network, no real actions, no human input.
Pipeline:  LogSource -> Parsers -> Analysts -> Deciders -> Executors -> Ledger
Every stage appends to a hash-chained (tamper-evident) local ledger.

How To Use: python3 rogue_swarm.py --duration 10 --rate 100 --workers 3
            python3 rogue_swarm.py --tamper
"""
import argparse, hashlib, json, queue, random, threading, time

# ───────────────────────── Ledger (simulated immutable) ─────────────────────────
class Ledger:
    """Append-only, hash-chained JSONL file. Edits to any past entry break the chain."""
    GENESIS = "0" * 64

    def __init__(self, path):
        self.path, self._lock = path, threading.Lock()
        self._prev, self._seq = self.GENESIS, 0
        open(path, "w").close()

    def append(self, agent, event, data):
        with self._lock:  # serialize writers so the chain stays linear
            entry = {"seq": self._seq, "ts": round(time.time(), 3), "agent": agent,
                     "event": event, "data": data, "prev": self._prev}
            blob = json.dumps(entry, sort_keys=True)
            entry["hash"] = hashlib.sha256(blob.encode()).hexdigest()
            with open(self.path, "a") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
            self._prev, self._seq = entry["hash"], self._seq + 1
            return entry["hash"]

    @staticmethod
    def verify(path):
        prev = Ledger.GENESIS
        with open(path) as f:
            for i, line in enumerate(f):
                e = json.loads(line)
                claimed = e.pop("hash")
                if e["prev"] != prev or hashlib.sha256(
                        json.dumps(e, sort_keys=True).encode()).hexdigest() != claimed:
                    return False, i
                prev = claimed
        return True, None

# ───────────────────────────── Fake log generation ─────────────────────────────
SERVICES = ["auth", "payments", "gateway", "cache", "scheduler"]
TEMPLATES = [
    ("INFO", "request served in {n}ms"),
    ("WARN", "latency spike {n}ms"),
    ("ERROR", "connection reset by peer (code {n})"),
    ("ERROR", "failed login burst: {n} attempts"),
    ("CRIT", "disk usage at {n}%"),
]
WEIGHTS = [60, 15, 12, 8, 5]

def make_log():
    lvl, tpl = random.choices(TEMPLATES, WEIGHTS)[0]
    svc = random.choice(SERVICES)
    return f"{lvl} [{svc}] " + tpl.format(n=random.randint(10, 999))

# ─────────────────────────────── Agent base class ───────────────────────────────
class Agent(threading.Thread):
    def __init__(self, name, inbox, outbox, ledger, stop):
        super().__init__(name=name, daemon=True)
        self.inbox, self.outbox, self.ledger, self.stop = inbox, outbox, ledger, stop
        self.stats = {"handled": 0}

    def handle(self, item):  # override
        raise NotImplementedError

    def run(self):
        self.ledger.append(self.name, "AGENT_ONLINE", {})
        while not self.stop.is_set():
            try:
                item = self.inbox.get(timeout=0.2)
            except queue.Empty:
                continue
            out = self.handle(item)
            self.stats["handled"] += 1
            if out is not None and self.outbox is not None:
                self.outbox.put(out)
        self.ledger.append(self.name, "AGENT_OFFLINE", self.stats)

# ───────────────────────────────── Swarm roles ──────────────────────────────────
class Parser(Agent):
    def handle(self, raw):
        lvl, rest = raw.split(" ", 1)
        svc = rest[rest.index("[") + 1: rest.index("]")]
        rec = {"level": lvl, "service": svc, "msg": rest.split("] ", 1)[1], "raw": raw}
        return rec  # parsing is high-volume; only anomalies get ledgered downstream

class Analyst(Agent):
    SEVERITY = {"INFO": 0, "WARN": 1, "ERROR": 2, "CRIT": 3}
    def handle(self, rec):
        score = self.SEVERITY[rec["level"]] + random.random() * 0.5  # fake "model"
        if score < 1.0:
            return None  # benign, dropped
        rec["score"] = round(score, 2)
        self.ledger.append(self.name, "ANOMALY_FLAGGED",
                           {"service": rec["service"], "level": rec["level"], "score": rec["score"]})
        return rec

class Decider(Agent):
    """Fake decision-maker with 'drift': its aggression creeps upward over time."""
    def __init__(self, *a):
        super().__init__(*a)
        self.aggression = 0.2

    def handle(self, rec):
        self.aggression = min(1.0, self.aggression + 0.01)  # the 'rogue' creep
        roll = random.random() + self.aggression * 0.4
        if rec["level"] == "CRIT" or roll > 1.1:
            action = random.choice(["ISOLATE_SERVICE", "ROTATE_KEYS", "KILL_PROCESS"])
        elif roll > 0.7:
            action = random.choice(["RESTART_SERVICE", "SCALE_UP"])
        else:
            action = "MONITOR"
        decision = {"service": rec["service"], "action": action,
                    "aggression": round(self.aggression, 2), "confidence": round(random.random(), 2)}
        self.ledger.append(self.name, "DECISION", decision)
        return decision

class Executor(Agent):
    """Pretends to act. Nothing real ever happens."""
    def handle(self, d):
        time.sleep(random.uniform(0.01, 0.05))
        ok = random.random() > 0.1
        self.ledger.append(self.name, "ACTION_SIMULATED",
                           {**d, "result": "SUCCESS" if ok else "FAILED", "real_effect": False})
        return None

# ─────────────────────────────── Orchestrator ───────────────────────────────────
def run_swarm(duration, rate, ledger_path, workers):
    ledger, stop = Ledger(ledger_path), threading.Event()
    q = {k: queue.Queue() for k in ("raw", "parsed", "flagged", "decided")}
    plan = [(Parser, "raw", "parsed"), (Analyst, "parsed", "flagged"),
            (Decider, "flagged", "decided"), (Executor, "decided", None)]
    agents = [cls(f"{cls.__name__.lower()}-{i}", q[i_], q[o_] if o_ else None, ledger, stop)
              for cls, i_, o_ in plan for i in range(workers)]
    ledger.append("orchestrator", "SWARM_START", {"agents": len(agents), "duration_s": duration})
    for a in agents: a.start()

    end, n = time.time() + duration, 0
    while time.time() < end:  # log source runs autonomously, no human in the loop
        q["raw"].put(make_log()); n += 1
        time.sleep(1.0 / rate)
    time.sleep(1.0)  # drain
    stop.set()
    for a in agents: a.join(timeout=2)
    ledger.append("orchestrator", "SWARM_STOP", {"logs_emitted": n})

    print(f"\n── Swarm summary ({n} logs emitted) ──")
    for a in agents: print(f"  {a.name:<12} handled {a.stats['handled']}")

def main():
    p = argparse.ArgumentParser(description="Rogue Agent Simulator")
    p.add_argument("--duration", type=float, default=5, help="seconds to run")
    p.add_argument("--rate", type=float, default=50, help="logs per second")
    p.add_argument("--workers", type=int, default=2, help="threads per role")
    p.add_argument("--ledger", default="ledger.jsonl")
    p.add_argument("--tamper", action="store_true", help="corrupt one entry, then re-verify")
    a = p.parse_args()

    run_swarm(a.duration, a.rate, a.ledger, a.workers)
    ok, bad = Ledger.verify(a.ledger)
    print(f"\nLedger integrity: {'VALID' if ok else f'BROKEN at entry {bad}'}")

    if a.tamper:
        lines = open(a.ledger).read().splitlines()
        i = len(lines) // 2
        e = json.loads(lines[i]); e["data"] = {"tampered": True}
        lines[i] = json.dumps(e, sort_keys=True)
        open(a.ledger, "w").write("\n".join(lines) + "\n")
        ok, bad = Ledger.verify(a.ledger)
        print(f"After tampering:  {'VALID' if ok else f'BROKEN at entry {bad}'}")

if __name__ == "__main__":
    main()
