"""Tests for order_tracker.py -- no network, no Textual.   Run:  python test_order_tracker.py

These check OUR logic against OKX-shaped answers that I wrote from the docs as I remember them
(accFillSz / avgPx / fee are cumulative; fee is negative; states live|partially_filled|filled|canceled).
They do NOT prove OKX answers exactly like this -- see the live checklist in the notes.
"""
import asyncio
import re
import sys

from order_tracker import OrderTracker, TrackedOrder, SimExchange, new_cl_ord_id

PASSED, FAILED = 0, []
def check(name, cond, detail=""):
    global PASSED
    if cond: PASSED += 1; print(f"  ok    {name}")
    else: FAILED.append(name); print(f"  FAIL  {name}  {detail}")

def run(coro): return asyncio.run(coro)


class FakeExchange:
    """Scripted answers.  rows: list of order rows returned by successive get_order calls
    (the last one repeats).  cancel: the answer to cancel_order."""
    def __init__(self, rows=None, cancel=None, get_error=None):
        self.rows = list(rows or [])
        self.cancel_answer = cancel
        self.get_error = get_error
        self.get_calls = 0
        self.cancel_calls = 0
    def get_order(self, inst_id, ord_id=None, cl_ord_id=None):
        self.get_calls += 1
        if self.get_error is not None:
            if isinstance(self.get_error, Exception): raise self.get_error
            return self.get_error
        row = self.rows[min(self.get_calls - 1, len(self.rows) - 1)]
        return {"code": "0", "msg": "", "data": [row]}
    def cancel_order(self, inst_id, ord_id=None, cl_ord_id=None):
        self.cancel_calls += 1
        return self.cancel_answer or {"code": "0", "data": [{"sCode": "0", "sMsg": ""}]}

def row(state, acc="0", avg="0", fee="0", ccy="", ord_id="123"):
    return {"ordId": ord_id, "state": state, "accFillSz": acc, "avgPx": avg, "fee": fee, "feeCcy": ccy}

class Recorder:
    def __init__(self): self.fills, self.closed, self.notes = [], [], []
    def on_fill(self, order, sz, px, fee): self.fills.append((sz, px, fee))
    def on_closed(self, order, state, unfilled): self.closed.append((state, unfilled))
    def on_note(self, msg): self.notes.append(msg)

def make(exchange, **kw):
    rec = Recorder()
    tr = OrderTracker(lambda: exchange, rec.on_fill, rec.on_closed, rec.on_note, **kw)
    return tr, rec

def order(side="buy", sz=0.001, px=100.0, **kw):
    return TrackedOrder(cl_ord_id=new_cl_ord_id(), inst_id="BTC-USDT", side=side, ord_type="limit", sz=sz, px=px, ord_id="123", **kw)


print("accepted is not filled")
ex = FakeExchange([row("live")])
tr, rec = make(ex); o = order(); tr.register(o)
run(tr.poll()); run(tr.poll())
check("a resting order books NOTHING, however often it is polled", rec.fills == [] and rec.closed == [] and o.cl_ord_id in tr.orders, (rec.fills, rec.closed))

print("fills are booked once")
ex = FakeExchange([row("filled", "0.001", "100", "-0.000001", "BTC")])
tr, rec = make(ex); o = order(); tr.register(o)
run(tr.poll()); run(tr.poll()); run(tr.poll())
check("a full fill is booked exactly once", len(rec.fills) == 1 and abs(rec.fills[0][0] - 0.001) < 1e-12 and rec.fills[0][1] == 100.0, rec.fills)
check("... and the order is closed as filled with nothing unfilled", rec.closed == [("filled", 0.0)] and not tr.orders, rec.closed)
check("BUY fee charged in the BASE coin is converted to quote (0.000001 BTC x 100)", abs(rec.fills[0][2] - 0.0001) < 1e-12, rec.fills[0][2])

ex = FakeExchange([row("filled", "0.001", "100", "-0.35", "USDT")])
tr, rec = make(ex); tr.register(order("sell"))
run(tr.poll())
check("SELL fee already in the quote currency is used as is", rec.fills[0][2] == 0.35, rec.fills)
ex = FakeExchange([row("filled", "0.001", "100", "-5", "OKB")])
tr, rec = make(ex); tr.register(order())
run(tr.poll())
check("a fee in some other coin is reported as UNKNOWN (None), never guessed", rec.fills[0][2] is None, rec.fills)

print("partial fills")
ex = FakeExchange([row("partially_filled", "0.0004", "100", "0", "BTC"),
                   row("partially_filled", "0.0004", "100", "0", "BTC"),
                   row("filled", "0.001", "101", "0", "BTC")])
tr, rec = make(ex); tr.register(order())
run(tr.poll()); run(tr.poll()); run(tr.poll())
check("two pieces are booked, no more", len(rec.fills) == 2, rec.fills)
check("piece 1 = 0.0004 @ 100", abs(rec.fills[0][0] - 0.0004) < 1e-12 and rec.fills[0][1] == 100.0, rec.fills[0])
expected_px = (0.001 * 101 - 0.0004 * 100) / 0.0006
check("piece 2 price is derived from the CUMULATIVE average (not the average itself)", abs(rec.fills[1][1] - expected_px) < 1e-9, (rec.fills[1], expected_px))
check("pieces add up to the whole order", abs(sum(f[0] for f in rec.fills) - 0.001) < 1e-12)

ex = FakeExchange([row("partially_filled", "0.0004", "100"), row("canceled", "0.0004", "100")])
tr, rec = make(ex); tr.register(order())
run(tr.poll()); run(tr.poll())
check("cancelled after a partial fill: the partial stays booked", len(rec.fills) == 1 and rec.fills[0][0] == 0.0004, rec.fills)
check("... and the unfilled part is reported (0.0006)", rec.closed and rec.closed[0][0] == "canceled" and abs(rec.closed[0][1] - 0.0006) < 1e-12, rec.closed)

print("bad reads never invent fills")
ex = FakeExchange(get_error={"code": "500", "msg": "timed out"})
tr, rec = make(ex); o = order(); tr.register(o)
for _ in range(6): run(tr.poll())
check("repeated failed reads book nothing and keep the order tracked", rec.fills == [] and o.cl_ord_id in tr.orders)
check("... and warn the user exactly once", len([n for n in rec.notes if "Cannot read status" in n]) == 1, rec.notes)
ex = FakeExchange(get_error=RuntimeError("boom"))
tr, rec = make(ex); tr.register(order())
run(tr.poll())
check("an exception inside the exchange client does not escape", True)

print("placement whose answer was lost (uncertain)")
now = [1000.0]
ex = FakeExchange(get_error={"code": "51603", "msg": "Order does not exist", "data": []})
tr, rec = make(ex, clock=lambda: now[0]); o = order(); o.ord_id = None; o.uncertain = True; tr.register(o)
run(tr.poll())
check("'not found' right after a timeout is NOT concluded yet", o.cl_ord_id in tr.orders and rec.closed == [])
now[0] += 10; run(tr.poll())
check("... still waiting inside the grace period", o.cl_ord_id in tr.orders)
now[0] += 15; run(tr.poll())
check("after the grace period it is declared NOT placed, loudly", rec.closed == [("not_placed", 0.001)] and any("NOT placed" in n for n in rec.notes), (rec.closed, rec.notes))
ex = FakeExchange([row("live", ord_id="777")])
tr, rec = make(ex); o = order(); o.ord_id = None; o.uncertain = True; tr.register(o)
run(tr.poll())
check("if the order turns out to exist it is adopted (ordId learned, no longer uncertain)", o.ord_id == "777" and not o.uncertain and o.cl_ord_id in tr.orders)

print("cancelling")
ex = FakeExchange([row("canceled", "0", "0")])
tr, rec = make(ex); o = order(); tr.register(o)
s = run(tr.cancel([o]))
check("cancel accepted and confirmed -> counted as cancelled", s["cancelled"] == 1 and not s["failed"] and not tr.orders, s)

ex = FakeExchange([row("filled", "0.001", "100", "-0.0001", "USDT")],
                  cancel={"code": "1", "msg": "All operations failed", "data": [{"sCode": "51400", "sMsg": "already filled"}]})
tr, rec = make(ex); o = order(); tr.register(o)
s = run(tr.cancel([o]))
check("a fill that beat the cancel is BOOKED and reported as already done", len(rec.fills) == 1 and s["already_done"] == 1 and not s["failed"], (rec.fills, s))

ex = FakeExchange([row("live")], cancel={"code": "1", "msg": "All operations failed", "data": [{"sCode": "50011", "sMsg": "rate limit"}]})
tr, rec = make(ex); o = order(); tr.register(o)
s = run(tr.cancel([o]))
check("a cancel that fails while the order is still live is reported as FAILED and still tracked", len(s["failed"]) == 1 and "rate limit" in s["failed"][0][1] and o.cl_ord_id in tr.orders, s)

ex = FakeExchange([row("live")])
tr, rec = make(ex); o = order(); tr.register(o)
s = run(tr.cancel([o]))
check("cancel accepted but order still looks live -> 'unconfirmed', not 'cancelled'", len(s["unconfirmed"]) == 1 and s["cancelled"] == 0, s)

a, b = order(bot_id="botA"), order(bot_id="botB"); m = order()
tr, rec = make(FakeExchange([row("live")])); [tr.register(x) for x in (a, b, m)]
check("open_orders can be filtered by bot", tr.open_orders({"botA"}) == [a] and len(tr.open_orders()) == 3)

print("client order ids")
ids = [new_cl_ord_id() for _ in range(2000)]
check("unique", len(set(ids)) == 2000)
check("OKX format: letters/digits only, at most 32 chars", all(re.fullmatch(r"[A-Za-z0-9]{1,32}", i) for i in ids), ids[:3])

print("simulated exchange")
price = {"BTC-USDT": 100.0}
sim = SimExchange(lambda inst: price.get(inst), lambda: (0.002, 0.0035))
def sim_tracker():
    rec = Recorder()
    return OrderTracker(lambda: sim, rec.on_fill, rec.on_closed, rec.on_note), rec

tr, rec = sim_tracker(); cl = new_cl_ord_id()
sim.place("BTC-USDT", "buy", "market", "0.01", None, cl)
tr.register(TrackedOrder(cl, "BTC-USDT", "buy", "market", 0.01, None))
run(tr.poll())
check("market order fills at the current price as taker", rec.fills and rec.fills[0][1] == 100.0, rec.fills)
check("BUY fee is taken in the base coin (0.01 x 0.35%) and converted to quote", abs(rec.fills[0][2] - 0.01 * 0.0035 * 100) < 1e-9, rec.fills)

tr, rec = sim_tracker(); cl = new_cl_ord_id()
sim.place("BTC-USDT", "buy", "limit", "0.01", "95", cl)
tr.register(TrackedOrder(cl, "BTC-USDT", "buy", "limit", 0.01, 95.0))
run(tr.poll())
check("a limit buy BELOW the market rests (no fill)", rec.fills == [] and len(tr.orders) == 1)
price["BTC-USDT"] = 94.0; run(tr.poll())
check("... and fills at ITS price, as maker, once the market trades through it", rec.fills and rec.fills[0][1] == 95.0 and abs(rec.fills[0][2] - 0.01 * 0.002 * 95) < 1e-9, rec.fills)
price["BTC-USDT"] = 100.0

tr, rec = sim_tracker(); cl = new_cl_ord_id()
sim.place("BTC-USDT", "buy", "limit", "0.01", "105", cl)
tr.register(TrackedOrder(cl, "BTC-USDT", "buy", "limit", 0.01, 105.0))
run(tr.poll())
check("a limit buy ABOVE the market is marketable: fills at the market price, not its limit", rec.fills and rec.fills[0][1] == 100.0, rec.fills)

tr, rec = sim_tracker(); cl = new_cl_ord_id()
sim.place("BTC-USDT", "sell", "limit", "0.01", "110", cl)
o = TrackedOrder(cl, "BTC-USDT", "sell", "limit", 0.01, 110.0); tr.register(o)
s = run(tr.cancel([o]))
check("cancelling a resting simulated order works and is confirmed", s["cancelled"] == 1 and rec.fills == [] and rec.closed[0][0] == "canceled", (s, rec.closed))
check("cancelling an order that is already gone is refused like the real thing",
      sim.cancel_order("BTC-USDT", None, cl)["code"] == "1")
check("an unknown order id answers 'does not exist' (51603)", sim.get_order("BTC-USDT", None, "nope")["code"] == "51603")

tr, rec = sim_tracker(); cl = new_cl_ord_id()
sim.place("BTC-USDT", "sell", "limit", "0.01", "100.5", cl)
o = TrackedOrder(cl, "BTC-USDT", "sell", "limit", 0.01, 100.5); tr.register(o)
price["BTC-USDT"] = 101.0
s = run(tr.cancel([o]))
check("a sell that the market traded through BEFORE the cancel is filled, not cancelled", s["already_done"] == 1 and len(rec.fills) == 1, (s, rec.fills))
check("SELL fee is taken in the quote currency", abs(rec.fills[0][2] - 0.01 * 100.5 * 0.002) < 1e-9, rec.fills)

print(f"\n{PASSED} passed, {len(FAILED)} failed")
if FAILED: print("FAILED:", *FAILED, sep="\n  - "); sys.exit(1)
