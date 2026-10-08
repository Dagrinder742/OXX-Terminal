"""Fault-injection harness for Module 1 clients.

    python harness.py --client module1_client.py

Requires the real `websockets` library (the sole third-party dependency).

Architecture:  client -> FaultProxy (raw TCP) -> mock L2 feed (websockets)

Network faults are injected at the TCP layer so they work the same on any
websockets version and on any model's client:
  reset      abort the socket mid-stream (ECONNRESET / abrupt drop)
  blackhole  keep sockets open but forward nothing (half-open connection)
  refuse     accept the TCP connection, then abort before the WS handshake
  none       healthy

A client under test must expose:
    async def run(url, on_message, stop: asyncio.Event, **timing) -> None
Only the timing kwargs its signature accepts are passed (base_delay,
max_delay, ping_interval, ping_timeout, idle_timeout, close_timeout).
Wrap other models' code in a small adapter with this signature.

Exit code 0 only if every check passes.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
import os
import sys
import time
from dataclasses import dataclass, field

import websockets


@dataclass
class Fault:
    kind: str  # none | reset | blackhole | refuse
    after: float = 0.6  # seconds after accept before the fault fires


@dataclass
class ConnRecord:
    idx: int
    kind: str
    t_open: float
    t_fault: float | None = None
    t_closed: float | None = None


class FaultProxy:
    def __init__(self, upstream_port: int, plan: list[Fault]) -> None:
        self.upstream_port = upstream_port
        self.plan = list(plan)
        self.records: list[ConnRecord] = []

    async def handle(self, cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        idx = len(self.records)
        fault = self.plan[idx] if idx < len(self.plan) else Fault("none")
        rec = ConnRecord(idx, fault.kind, time.monotonic())
        self.records.append(rec)

        if fault.kind == "refuse":
            rec.t_fault = rec.t_closed = time.monotonic()
            cw.transport.abort()
            return
        try:
            ur, uw = await asyncio.open_connection("127.0.0.1", self.upstream_port)
        except OSError:
            cw.transport.abort()
            return

        state = {"hole": False}

        async def pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await r.read(65536)
                    if not data:
                        return
                    if state["hole"]:
                        continue  # swallow: connection looks open but is dead
                    w.write(data)
                    await w.drain()
            except (ConnectionError, OSError):
                return

        async def trigger() -> None:
            if fault.kind not in ("reset", "blackhole"):
                return
            await asyncio.sleep(fault.after)
            rec.t_fault = time.monotonic()
            if fault.kind == "reset":
                cw.transport.abort()
                uw.transport.abort()
            else:
                state["hole"] = True

        tasks = [
            asyncio.ensure_future(pipe(cr, uw)),
            asyncio.ensure_future(pipe(ur, cw)),
        ]
        trig = asyncio.ensure_future(trigger())
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            rec.t_closed = time.monotonic()
            for t in (*tasks, trig):
                t.cancel()
            await asyncio.gather(*tasks, trig, return_exceptions=True)
            for w in (cw, uw):
                w.transport.abort()


def make_feed_handler(interval: float, skip_every: int, stale_every: int):
    """Mock L2 feed. Each connection starts with a snapshot then deltas.
    skip_every / stale_every inject sequence gaps / stale replays (for
    Module 2 work; Module 1 only passes frames through)."""
    state = {"seq": 0}

    async def handler(ws, path=None):  # path kept for legacy websockets
        await ws.send(json.dumps({"type": "snapshot", "product_id": "BTC-USD",
                                  "sequence": state["seq"],
                                  "bids": [["100.00", "1.0"]], "asks": [["101.00", "1.0"]]}))
        n = 0
        try:
            while True:
                await asyncio.sleep(interval)
                n += 1
                state["seq"] += 1
                if skip_every and n % skip_every == 0:
                    state["seq"] += 1  # gap
                seq = state["seq"]
                if stale_every and n % stale_every == 0:
                    seq = max(0, seq - 3)  # stale replay
                await ws.send(json.dumps({"type": "l2update", "product_id": "BTC-USD",
                                          "sequence": seq,
                                          "changes": [["buy", "100.00", "1.0"]]}))
        except websockets.exceptions.ConnectionClosed:
            return

    return handler


def load_client(path: str):
    spec = importlib.util.spec_from_file_location("client_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["client_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod.run


def fd_count() -> int | None:
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


async def main_async(args) -> int:
    run_fn = load_client(args.client)
    timing = dict(base_delay=0.05, max_delay=0.5, ping_interval=0.3,
                  ping_timeout=0.3, idle_timeout=None, close_timeout=1.0)
    accepted = set(inspect.signature(run_fn).parameters)
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD
                     for p in inspect.signature(run_fn).parameters.values())
    timing = {k: v for k, v in timing.items() if has_var_kw or k in accepted}
    hardcoded = [k for k in ("ping_interval", "idle_timeout") if k not in timing]

    plan = [Fault("reset", 0.6), Fault("refuse"), Fault("refuse"),
            Fault("blackhole", 0.6), Fault("reset", 0.3), Fault("refuse")]

    server = await websockets.serve(
        make_feed_handler(0.05, args.skip_every, args.stale_every), "127.0.0.1", 0)
    up_port = server.sockets[0].getsockname()[1]
    proxy = FaultProxy(up_port, plan)
    pserver = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    p_port = pserver.sockets[0].getsockname()[1]

    me = asyncio.current_task()
    tasks_before = len([t for t in asyncio.all_tasks() if t is not me])
    fds_before = fd_count()

    received = {"n": 0, "last": None}

    async def on_message(msg) -> None:
        received["n"] += 1
        received["last"] = time.monotonic()

    stop = asyncio.Event()
    client_task = asyncio.ensure_future(
        run_fn(f"ws://127.0.0.1:{p_port}", on_message, stop, **timing))

    # Wait until the whole fault plan has been consumed, then settle.
    deadline = time.monotonic() + args.timeout
    while len(proxy.records) <= len(plan) and time.monotonic() < deadline:
        if client_task.done():
            break
        await asyncio.sleep(0.05)
    conns_at_plan_end = len(proxy.records)
    msgs_at_plan_end = received["n"]
    await asyncio.sleep(args.settle)
    conns_after_settle = len(proxy.records)
    msgs_after_settle = received["n"]

    t_stop = time.monotonic()
    stop.set()
    crashed = None
    try:
        await asyncio.wait_for(client_task, 5)
        stop_latency = time.monotonic() - t_stop
    except asyncio.TimeoutError:
        stop_latency = float("inf")
        client_task.cancel()
        await asyncio.gather(client_task, return_exceptions=True)
    except Exception as e:  # noqa: BLE001
        stop_latency = time.monotonic() - t_stop
        crashed = e

    await asyncio.sleep(1.5)
    server.close()
    await server.wait_closed()
    pserver.close()
    await pserver.wait_closed()
    await asyncio.sleep(0.3)
    tasks_after = len([t for t in asyncio.all_tasks() if t is not me])
    fds_after = fd_count()

    # ---- checks ----
    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    check("client did not crash", crashed is None, repr(crashed) if crashed else "")
    check("fault plan fully consumed", conns_at_plan_end > len(plan),
          f"{conns_at_plan_end - 1} conns seen vs {len(plan)} planned faults")
    check("recovered: data flows after last fault",
          msgs_after_settle - msgs_at_plan_end >= 10,
          f"{msgs_after_settle - msgs_at_plan_end} msgs in {args.settle}s settle")
    check("no reconnect storm while healthy",
          conns_after_settle == conns_at_plan_end,
          f"{conns_after_settle - conns_at_plan_end} extra connects while healthy")

    holes = [r for r in proxy.records if r.kind == "blackhole" and r.t_fault]
    if holes:
        lat = [(r.t_closed - r.t_fault) if r.t_closed else float("inf") for r in holes]
        bound = ((timing.get("ping_interval", 0) + timing.get("ping_timeout", 0))
                 + timing.get("close_timeout", 0) + 1.5) if not hardcoded else args.timeout
        check("half-open detected and socket closed by client",
              all(x <= bound for x in lat),
              f"detect+close latency {['%.2fs' % x for x in lat]} (bound {bound:.1f}s)")
    check("graceful stop <= 3s", stop_latency <= 3, f"{stop_latency:.2f}s")
    check("no leaked asyncio tasks", tasks_after <= tasks_before,
          f"{tasks_before} -> {tasks_after}")
    if fds_before is not None and fds_after is not None:
        check("no leaked file descriptors", fds_after <= fds_before + 2,
              f"{fds_before} -> {fds_after}")
    else:
        results.append(("fd leak check", True, "SKIPPED (/proc unavailable)"))

    print()
    if hardcoded:
        print(f"NOTE: client does not accept {hardcoded}; timing is hardcoded, "
              f"so the run used real-time defaults and may be slow.")
    w = max(len(n) for n, _, _ in results)
    for n, ok, d in results:
        print(f"{'PASS' if ok else 'FAIL'}  {n:<{w}}  {d}")
    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True, help="path to module exposing run()")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--skip-every", type=int, default=0)
    ap.add_argument("--stale-every", type=int, default=0)
    args = ap.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
