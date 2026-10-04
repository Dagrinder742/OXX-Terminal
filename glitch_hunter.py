#!/usr/bin/env python3
"""
The Autonomous Glitch-Hunter
============================
A live terminal dashboard that sabotages itself, notices, and heals.

  * Mock telemetry is streamed to a dashboard.
  * Two chaos engines inject faults:
      - telemetry chaos : NaN / missing keys / strings / spikes / dropped frames
      - renderer chaos  : exceptions, garbled output, stalls, codec errors,
                          and "poisoned" backends that stay broken for a while
  * A sanitizer repairs bad telemetry (replays last known-good value).
  * A supervisor validates every rendered frame (integrity marker, encodability,
    time budget), falls back per-frame on failure, and HOT-SWAPS the rendering
    backend when failures cluster (circuit breaker).
  * It periodically probes better backends and promotes back when they recover.

Backends (best -> worst):  unicode-ansi  ->  ascii-ansi  ->  log-line (fail-safe)

Pure standard library. Ctrl+C to quit.

Try:
  python3 glitch_hunter.py --fault-rate 0.25   # watch it struggle
  python3 glitch_hunter.py --seed 7            # repeatable run
  python3 glitch_hunter.py --duration 0        # run until Ctrl+C
"""
from __future__ import annotations

import argparse
import math
import os
import random
import shutil
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass, field

BOUNDS = {"cpu": (0.0, 100.0), "mem": (0.0, 100.0),
          "latency": (5.0, 2000.0), "throughput": (0.0, 5000.0)}
UNITS = {"cpu": "%", "mem": "%", "latency": "ms", "throughput": "rps"}
RESET = "\x1b[0m"


# --------------------------------------------------------------------------- #
# Shared state
# --------------------------------------------------------------------------- #
class EventLog:
    """Incident feed shown on the dashboard. Messages are kept pure ASCII."""

    def __init__(self, t0: float):
        self.t0, self.items = t0, deque(maxlen=7)

    def add(self, level: str, msg: str) -> None:
        self.items.append((time.monotonic() - self.t0, level, msg))

    def snapshot(self) -> list[tuple[float, str, str]]:
        return list(self.items)


@dataclass
class Frame:
    tick: int
    uptime: float
    metrics: dict
    history: dict
    events: list
    stats: Counter
    backend: str = ""


# --------------------------------------------------------------------------- #
# Telemetry: source, chaos, sanitizer
# --------------------------------------------------------------------------- #
class Telemetry:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.state = {"cpu": 40.0, "mem": 55.0, "latency": 120.0, "throughput": 800.0}
        self.history = {k: deque(maxlen=40) for k in self.state}

    def sample(self) -> dict:
        for k, (lo, hi) in BOUNDS.items():
            mid, span = (lo + hi) / 2, hi - lo
            drift = (mid - self.state[k]) * 0.01          # gentle mean reversion
            step = span * 0.03 * self.rng.gauss(0, 1)
            self.state[k] = min(hi, max(lo, self.state[k] + drift + step))
        return dict(self.state)

    def record(self, clean: dict) -> None:
        for k, v in clean.items():
            self.history[k].append(v)


class TelemetryChaos:
    KINDS = ["nan", "missing", "string", "spike", "none", "drop"]

    def __init__(self, rng, rate, stats):
        self.rng, self.rate, self.stats = rng, rate, stats

    def corrupt(self, sample: dict):
        if self.rng.random() >= self.rate:
            return sample
        self.stats["telemetry_faults"] += 1
        kind = self.rng.choice(self.KINDS)
        if kind == "drop":
            return None
        s, k = dict(sample), self.rng.choice(list(sample))
        if kind == "nan":
            s[k] = float("nan")
        elif kind == "missing":
            del s[k]
        elif kind == "string":
            s[k] = "ERR_0xDEAD"
        elif kind == "spike":
            s[k] = s[k] * 1e6 + 1e9
        elif kind == "none":
            s[k] = None
        return s


class Sanitizer:
    """Detects bad telemetry mid-stream and repairs it with the last good value."""

    def __init__(self, log, stats):
        self.log, self.stats = log, stats
        self.last = {k: (lo + hi) / 2 for k, (lo, hi) in BOUNDS.items()}

    def clean(self, raw) -> dict:
        if not isinstance(raw, dict):
            self.stats["repairs"] += 1
            self.log.add("TELEM", "frame dropped, replaying last good sample")
            return dict(self.last)
        out = {}
        for k, (lo, hi) in BOUNDS.items():
            v = raw.get(k)
            ok = (isinstance(v, (int, float)) and not isinstance(v, bool)
                  and math.isfinite(v) and lo <= v <= hi)
            if ok:
                out[k] = float(v)
            else:
                out[k] = self.last[k]
                self.stats["repairs"] += 1
                self.log.add("TELEM", f"{k}: bad value {repr(v)[:14]} -> last-good")
        self.last = dict(out)
        return out


# --------------------------------------------------------------------------- #
# Rendering backends (compose text only; the supervisor validates + paints)
# --------------------------------------------------------------------------- #
class Backend:
    name, fullscreen, failsafe = "base", True, False

    def setup(self, out) -> None:
        out.write("\x1b[?25l\x1b[2J\x1b[H" if self.fullscreen else "\n")
        out.flush()

    def teardown(self, out) -> None:
        out.write("\x1b[?25h")
        out.flush()

    def render(self, f: Frame) -> str:
        raise NotImplementedError


class PanelBackend(Backend):
    glyphs, color, rule, title = "", False, "-", ""

    def _spark(self, key, width=24):
        lo, hi = BOUNDS[key]
        vals = list(f_hist := self._hist[key])[-width:]
        n = len(self.glyphs)
        return "".join(self.glyphs[min(n - 1, int(max(0.0, min(1.0, (x - lo) / (hi - lo))) * n))]
                       for x in vals)

    def _c(self, code: str) -> str:
        return code if self.color else ""

    def render(self, f: Frame) -> str:
        self._hist = f.history
        cols = max(60, min(shutil.get_terminal_size((80, 24)).columns, 100))
        L = [f"{self._c(chr(27) + '[1;36m')}{self.title}{self._c(RESET)}  "
             f"backend={self.name}  #{f.tick:05d}  up {f.uptime:6.1f}s"]
        for k, (lo, hi) in BOUNDS.items():
            v = f.metrics[k]
            frac = (v - lo) / (hi - lo)
            col = "\x1b[31m" if frac > .85 else "\x1b[33m" if frac > .65 else "\x1b[32m"
            L.append(f" {k:<11}{self._c(col)}{v:8.1f} {UNITS[k]:<4}{self._c(RESET)} {self._spark(k)}")
        s = f.stats
        L.append(f" telemetry faults={s['telemetry_faults']} repaired={s['repairs']} | "
                 f"render faults={s['render_faults']} swaps={s['swaps']} recoveries={s['recoveries']}")
        L.append(self.rule * (cols - 1))
        palette = {"FAULT": "\x1b[31m", "LOOP": "\x1b[31m", "SWAP": "\x1b[35m",
                   "TELEM": "\x1b[33m", "PROBE": "\x1b[36m"}
        for t, lvl, msg in f.events:
            line = f" +{t:6.1f}s {lvl:<5} {msg}"[: cols - 1]
            L.append(f"{self._c(palette.get(lvl, ''))}{line}{self._c(RESET)}")
        return "\x1b[H" + "".join(x + "\x1b[K\n" for x in L) + "\x1b[J"


class UnicodeAnsiBackend(PanelBackend):
    name, glyphs, color, rule, title = "unicode-ansi", "▁▂▃▄▅▆▇█", True, "─", "◢ GLITCH-HUNTER ◣"


class AsciiAnsiBackend(PanelBackend):
    name, glyphs, color, rule, title = "ascii-ansi", "_.:-=+*#", False, "-", "[ GLITCH-HUNTER ]"


class LogLineBackend(Backend):
    """Last-resort: one plain line per frame. No cursor control, can't really break."""
    name, fullscreen, failsafe = "log-line", False, True

    def render(self, f: Frame) -> str:
        m = f.metrics
        return (f"#{f.tick:05d} [log-mode] cpu={m['cpu']:.1f} mem={m['mem']:.1f} "
                f"lat={m['latency']:.0f}ms rps={m['throughput']:.0f}\n")


# --------------------------------------------------------------------------- #
# Renderer chaos
# --------------------------------------------------------------------------- #
class RendererChaos:
    FAULTS = ["exception", "garble", "stall", "codec", "poison"]
    WEIGHTS = [3, 3, 2, 1, 2]

    def __init__(self, rng, rate, stats, stall_s):
        self.rng, self.rate, self.stats, self.stall_s = rng, rate, stats, stall_s
        self.poisoned: dict[str, int] = {}        # backend name -> broken until tick

    def tamper(self, backend: Backend, frame: Frame, text: str) -> str:
        if backend.failsafe:
            return text
        if self.poisoned.get(backend.name, -1) >= frame.tick:
            raise RuntimeError("renderer state corrupted (simulated)")
        if self.rng.random() >= self.rate:
            return text
        self.stats["render_faults_injected"] += 1
        kind = self.rng.choices(self.FAULTS, self.WEIGHTS)[0]
        if kind == "exception":
            raise RuntimeError("render pipeline crashed (simulated)")
        if kind == "garble":
            return "".join(self.rng.choice("@%&*?!~^") for _ in range(len(text)))
        if kind == "stall":
            time.sleep(self.stall_s)
            return text
        if kind == "codec":
            raise UnicodeEncodeError("ascii", "x", 0, 1, "simulated codec failure")
        self.poisoned[backend.name] = frame.tick + self.rng.randint(25, 45)
        raise RuntimeError("renderer poisoned (simulated)")


# --------------------------------------------------------------------------- #
# Supervisor: validation, per-frame fallback, circuit breaker, hot-swap, recovery
# --------------------------------------------------------------------------- #
class Supervisor:
    def __init__(self, backends, chaos, log, stats, out, budget_ms,
                 threshold=3, window=10, probe_every=25, probe_passes=2):
        self.backends, self.chaos, self.log, self.stats, self.out = backends, chaos, log, stats, out
        self.budget, self.threshold, self.probe_every, self.probe_passes = budget_ms, threshold, probe_every, probe_passes
        self.recent = deque(maxlen=window)
        self.i, self.probe_ok = 0, 0
        self.encoding = getattr(out, "encoding", None) or "utf-8"
        self.backends[0].setup(out)

    # -- health check ------------------------------------------------------- #
    def _validate(self, text, frame):
        if not isinstance(text, str) or not text:
            raise ValueError("empty frame")
        if f"#{frame.tick:05d}" not in text:
            raise ValueError("integrity marker missing (garbled output)")
        if "\x00" in text or "\ufffd" in text:
            raise ValueError("corrupt bytes in frame")
        text.encode(self.encoding)                # strict: terminal must be able to show it

    def _attempt(self, idx, frame) -> str:
        b = self.backends[idx]
        frame.backend = b.name
        t = time.perf_counter()
        text = self.chaos.tamper(b, frame, b.render(frame))
        ms = (time.perf_counter() - t) * 1000
        if ms > self.budget:
            raise TimeoutError(f"render took {ms:.0f}ms, budget {self.budget:.0f}ms")
        self._validate(text, frame)
        return text

    # -- hot swap ----------------------------------------------------------- #
    def _swap(self, new_i, reason):
        old, new = self.backends[self.i], self.backends[new_i]
        for fn, be in ((old.teardown, old), (new.setup, new)):
            try:
                fn(self.out)
            except Exception as e:                # even the swap must not crash us
                self.log.add("FAULT", f"{be.name} swap hook: {type(e).__name__}")
        self.log.add("SWAP", f"{old.name} -> {new.name} ({reason})")
        self.i, self.probe_ok = new_i, 0
        self.recent.clear()
        self.stats["swaps"] += 1

    def _probe(self, frame):
        if self.i == 0 or frame.tick % self.probe_every:
            return
        cand = self.i - 1
        try:
            self._attempt(cand, frame)            # canary render, never painted
            self.probe_ok += 1
            if self.probe_ok >= self.probe_passes:
                self.stats["recoveries"] += 1
                self._swap(cand, f"healed, {self.probe_passes} clean probes")
        except Exception as e:
            self.probe_ok = 0
            self.log.add("PROBE", f"{self.backends[cand].name} still sick: {type(e).__name__}")

    # -- main entry --------------------------------------------------------- #
    def render(self, frame: Frame) -> str:
        self._probe(frame)
        idx = self.i
        while idx < len(self.backends):
            try:
                text = self._attempt(idx, frame)
                if idx == self.i:
                    self.recent.append(0)
                return text
            except Exception as e:
                self.stats["render_faults"] += 1
                self.log.add("FAULT", f"{self.backends[idx].name}: {type(e).__name__}: {e}"[:90])
                if idx == self.i:
                    self.recent.append(1)
                    if sum(self.recent) >= self.threshold and self.i < len(self.backends) - 1:
                        self._swap(self.i + 1, f"{sum(self.recent)} faults in {len(self.recent)} frames")
                        idx = self.i
                        continue
                idx += 1                          # one-off fallback for this frame
        return f"#{frame.tick:05d} EMERGENCY: all renderers down\n"

    def shutdown(self):
        try:
            self.backends[self.i].teardown(self.out)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Self-healing terminal dashboard with built-in chaos.")
    ap.add_argument("--duration", type=float, default=60, help="seconds to run (0 = until Ctrl+C)")
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--fault-rate", type=float, default=0.10, help="per-frame renderer fault chance")
    ap.add_argument("--telemetry-fault-rate", type=float, default=0.15)
    ap.add_argument("--budget-ms", type=float, default=50, help="max render time before it counts as a fault")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--force-ansi", action="store_true", help="use fancy backends even if stdout isn't a TTY")
    args = ap.parse_args()

    if os.name == "nt":
        os.system("")                              # enable ANSI escapes on Windows 10+

    out, rng, t0 = sys.stdout, random.Random(args.seed), time.monotonic()
    log, stats = EventLog(t0), Counter()
    tele = Telemetry(rng)
    t_chaos = TelemetryChaos(rng, args.telemetry_fault_rate, stats)
    sanitizer = Sanitizer(log, stats)
    r_chaos = RendererChaos(rng, args.fault_rate, stats, stall_s=args.budget_ms * 1.6 / 1000)

    backends = [UnicodeAnsiBackend(), AsciiAnsiBackend(), LogLineBackend()]
    if not (out.isatty() or args.force_ansi):
        backends = [LogLineBackend()]
    sup = Supervisor(backends, r_chaos, log, stats, out, args.budget_ms)

    interval, tick = 1.0 / args.fps, 0
    try:
        while args.duration <= 0 or time.monotonic() - t0 < args.duration:
            started = time.monotonic()
            try:
                clean = sanitizer.clean(t_chaos.corrupt(tele.sample()))
                tele.record(clean)
                frame = Frame(tick, started - t0, clean, tele.history,
                              log.snapshot(), Counter(stats))
                out.write(sup.render(frame))
                out.flush()
            except BrokenPipeError:
                break
            except Exception as e:                # outer safety net: log it, keep going
                stats["loop_faults"] += 1
                log.add("LOOP", f"{type(e).__name__}: {e}"[:90])
            tick += 1
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        sup.shutdown()
        print(f"\nGlitch-Hunter survived {tick} frames in {time.monotonic() - t0:.1f}s "
              f"(final backend: {backends[sup.i].name})")
        for k in ("telemetry_faults", "repairs", "render_faults_injected",
                  "render_faults", "swaps", "recoveries", "loop_faults"):
            print(f"  {k:<24}{stats[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
