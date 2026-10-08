"""Logic tests for module1_client using a fake transport.

These test backoff math, idle detection, stop latency, cancellation and task
cleanup. They do NOT test the real `websockets` library; harness.py does.
If `websockets` is not installed, a minimal stub is injected so this file
still runs.
"""
import asyncio
import sys
import types

try:
    import websockets  # noqa: F401
except ModuleNotFoundError:
    pkg = types.ModuleType("websockets")
    exc = types.ModuleType("websockets.exceptions")

    class WebSocketException(Exception): ...
    class ConnectionClosed(WebSocketException): ...

    exc.WebSocketException = WebSocketException
    exc.ConnectionClosed = ConnectionClosed
    pkg.exceptions = exc
    pkg.connect = None
    sys.modules["websockets"] = pkg
    sys.modules["websockets.exceptions"] = exc

from websockets.exceptions import ConnectionClosed  # noqa: E402

import module1_client as m  # noqa: E402


class FakeWS:
    def __init__(self, script):
        self.script = list(script)  # items: str | Exception | "HANG"
        self.closed = False

    async def recv(self):
        if not self.script:
            await asyncio.Event().wait()  # hang forever
        item = self.script.pop(0)
        if item == "HANG":
            await asyncio.Event().wait()
        if isinstance(item, Exception):
            raise item
        return item


class FakeConnect:
    """Callable returning async context managers following a per-attempt plan.
    Plan item: OSError instance (connect fails) or list (recv script)."""

    def __init__(self, plan):
        self.plan = list(plan)
        self.calls = 0
        self.sockets = []

    def __call__(self, url, **kw):
        self.calls += 1
        item = self.plan.pop(0) if self.plan else ["HANG"]
        outer = self

        class Ctx:
            async def __aenter__(self_inner):
                if isinstance(item, Exception):
                    raise item
                ws = FakeWS(item)
                outer.sockets.append(ws)
                return ws

            async def __aexit__(self_inner, *a):
                if outer.sockets:
                    outer.sockets[-1].closed = True
                return False

        return Ctx()


class MaxRng:
    """uniform(0, x) -> x, so we can read the ceiling directly."""
    def uniform(self, a, b):
        return b


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


async def noop(_):
    return None


async def t_backoff_ceiling():
    fc = FakeConnect([OSError("x")] * 6)
    c = m.ResilientWSClient("ws://x", noop, base_delay=0.01, max_delay=0.08,
                            rng=MaxRng(), connect=fc)
    task = asyncio.create_task(c.run())
    while fc.calls < 7:
        await asyncio.sleep(0.01)
    c.stop(); await asyncio.wait_for(task, 2)
    d = c.stats.backoff_delays[:6]
    exp = [0.01, 0.02, 0.04, 0.08, 0.08, 0.08]
    check("backoff doubles then caps", all(abs(a - b) < 1e-9 for a, b in zip(d, exp)), str(d))


async def t_jitter_range():
    import random
    fc = FakeConnect([OSError("x")] * 30)
    c = m.ResilientWSClient("ws://x", noop, base_delay=0.001, max_delay=0.004,
                            rng=random.Random(1), connect=fc)
    task = asyncio.create_task(c.run())
    while fc.calls < 30:
        await asyncio.sleep(0.01)
    c.stop(); await asyncio.wait_for(task, 2)
    d = c.stats.backoff_delays
    check("jitter within [0, cap] and not constant",
          all(0 <= x <= 0.004 for x in d) and len(set(d)) > 5)


async def t_no_reset_when_unstable():
    # accepts then closes immediately -> attempt must keep growing
    plan = [[ConnectionClosed(None, None)] for _ in range(5)]
    fc = FakeConnect(plan)
    c = m.ResilientWSClient("ws://x", noop, base_delay=0.01, max_delay=1.0,
                            stable_after=100, rng=MaxRng(), connect=fc)
    task = asyncio.create_task(c.run())
    while fc.calls < 5:
        await asyncio.sleep(0.01)
    c.stop(); await asyncio.wait_for(task, 3)
    d = c.stats.backoff_delays[:4]
    check("no backoff reset on short sessions", d == sorted(d) and d[-1] > d[0], str(d))


async def t_idle_timeout_reconnects():
    fc = FakeConnect([["a", "HANG"], ["b", "HANG"]])
    got = []

    async def h(msg):
        got.append(msg)

    c = m.ResilientWSClient("ws://x", h, base_delay=0.01, max_delay=0.02,
                            idle_timeout=0.1, connect=fc)
    task = asyncio.create_task(c.run())
    await asyncio.sleep(0.6)
    c.stop(); await asyncio.wait_for(task, 2)
    check("idle timeout forces reconnect", got[:2] == ["a", "b"] and fc.calls >= 2, f"{got} calls={fc.calls}")


async def t_stop_latency_and_cleanup():
    before = len(asyncio.all_tasks())
    fc = FakeConnect([["HANG"]])
    c = m.ResilientWSClient("ws://x", noop, idle_timeout=30, connect=fc)
    task = asyncio.create_task(c.run())
    await asyncio.sleep(0.1)
    t0 = asyncio.get_running_loop().time()
    c.stop(); await asyncio.wait_for(task, 2)
    dt = asyncio.get_running_loop().time() - t0
    await asyncio.sleep(0.05)
    after = len(asyncio.all_tasks())
    check("stop is prompt (<0.5s) with 30s idle timeout", dt < 0.5, f"{dt:.3f}s")
    check("socket closed on stop", fc.sockets[-1].closed)
    check("no leaked tasks after stop", after == before, f"{before}->{after}")


async def t_cancel_closes_socket():
    before = len(asyncio.all_tasks())
    fc = FakeConnect([["HANG"]])
    c = m.ResilientWSClient("ws://x", noop, connect=fc)
    task = asyncio.create_task(c.run())
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
        cancelled = False
    except asyncio.CancelledError:
        cancelled = True
    await asyncio.sleep(0.05)
    check("cancel propagates and closes socket", cancelled and fc.sockets[-1].closed)
    check("no leaked tasks after cancel", len(asyncio.all_tasks()) == before)


async def t_handler_error_survives():
    fc = FakeConnect([["bad", "good", "HANG"]])
    got = []

    async def h(msg):
        if msg == "bad":
            raise ValueError("boom")
        got.append(msg)

    c = m.ResilientWSClient("ws://x", h, connect=fc)
    task = asyncio.create_task(c.run())
    await asyncio.sleep(0.1)
    c.stop(); await asyncio.wait_for(task, 2)
    check("handler exception does not drop connection",
          got == ["good"] and c.stats.connects == 1 and c.stats.handler_errors == 1)


async def t_hook_error_reconnects():
    calls = {"n": 0}

    async def bad_hook(ws):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("subscribe failed")

    fc = FakeConnect([["HANG"], ["HANG"]])
    c = m.ResilientWSClient("ws://x", noop, on_connect=bad_hook,
                            base_delay=0.01, max_delay=0.02, connect=fc)
    task = asyncio.create_task(c.run())
    await asyncio.sleep(0.3)
    c.stop(); await asyncio.wait_for(task, 2)
    check("on_connect failure -> reconnect, not crash", calls["n"] >= 2)


async def main():
    for t in (t_backoff_ceiling, t_jitter_range, t_no_reset_when_unstable,
              t_idle_timeout_reconnects, t_stop_latency_and_cleanup,
              t_cancel_closes_socket, t_handler_error_survives,
              t_hook_error_reconnects):
        try:
            await asyncio.wait_for(t(), 10)
        except Exception as e:  # noqa: BLE001
            check(t.__name__, False, f"raised {e!r}")
    w = max(len(n) for n, _, _ in results)
    for n, ok, d in results:
        print(f"{'PASS' if ok else 'FAIL'}  {n:<{w}}  {d}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
