"""UI-flow tests for main.py with Textual / Rich / websockets / the vault REPLACED BY STUBS.

Run from the project folder:   python test_main_flow.py

These exercise main.py's own logic (order flow, fee groups, order book, bot loop, start-up
idempotency) without a terminal, network or credentials.  They do NOT prove that Textual draws
anything correctly, or that OKX accepts a real order -- see the manual checklist.
"""
import asyncio
import json
import logging
import sys
import time
import types

# ------------------------------------------------------------------ stubs (installed before import)
def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m

class _W:  # generic widget stand-in
    def __init__(self, *a, **k): self.value = ""; self.text = ""; self.label = ""; self.id = k.get("id")
    def update(self, text): self.text = str(text)
    def __enter__(self): return self
    def __exit__(self, *a): return False

class _App:
    CSS = ""
    def __init__(self): self.notes = []; self.intervals = []; self.workers = []; self.timers = []; self._w = {}
    def notify(self, msg, **kw): self.notes.append((str(msg), kw))
    def query_one(self, sel, typ=None): return self._w.setdefault(sel, _W())
    def set_interval(self, secs, fn): self.intervals.append((secs, fn))
    def set_timer(self, secs, fn): self.timers.append((secs, fn))
    def run_worker(self, work, **kw):
        self.workers.append(kw)
        if asyncio.iscoroutine(work): work.close()   # recorded, not run
    def push_screen(self, *a, **k): pass

_mod("textual"); _mod("textual.app", App=_App, ComposeResult=object)
_mod("textual.containers", Horizontal=_W, Vertical=_W, VerticalScroll=_W)
class _Input(_W): Submitted = Changed = object
class _Button(_W): Pressed = object
_mod("textual.widgets", Footer=_W, Header=_W, Static=_W, Input=_Input, Button=_Button, Label=_W)
_mod("textual.reactive", reactive=lambda default: default)
_mod("textual.screen", ModalScreen=type("ModalScreen", (), {}))
_mod("rich"); _mod("rich.markup", escape=lambda s: str(s).replace("[", "\\["))
_mod("rich.text", Text=object)
_mod("websockets", exceptions=types.SimpleNamespace(ConnectionClosed=Exception))
_mod("plotext")

import threading
class _Vault:
    creds = {"api_key": "K", "secret_key": "S", "passphrase": "P"}
    loaded_on = []
    @classmethod
    def load_credentials(cls):
        cls.loaded_on.append(threading.get_ident()); return cls.creds
    saved_on = []
    @classmethod
    def save_credentials(cls, *a):
        cls.saved_on.append(threading.get_ident())
        if getattr(cls, "save_delay", 0): time.sleep(cls.save_delay)   # a real encrypt takes seconds
        if getattr(cls, "fail_save", False): raise OSError("disk full")
_mod("secure_vault", EncryptedVault=_Vault)
_mod("chart_renderer", OKXChartEngine=type("OKXChartEngine", (), {}))

import main as M                      # noqa: E402  (after stubs)
import okx_private                    # noqa: E402
_RealPriv = okx_private.OKXPrivateClient   # some tests swap in a fake; they must put this back
import api_client                     # noqa: E402
logging.disable(logging.CRITICAL)

PASSED, FAILED = 0, []
def check(name, cond, detail=""):
    global PASSED
    if cond: PASSED += 1; print(f"  ok    {name}")
    else: FAILED.append(name); print(f"  FAIL  {name}  {detail}")

def run(coro): return asyncio.run(coro)

BTC = {"tickSz": "0.1", "lotSz": "0.00000001", "minSz": "0.00001", "groupId": "1"}
SHIB = {"tickSz": "0.00000001", "lotSz": "1", "minSz": "1", "groupId": "2"}
# Real response shape from the user's account (trimmed): top-level = group 1 rates.
FEE_ROW = {"level": "Lv1", "maker": "-0.0014", "taker": "-0.0023", "feeGroup": [
    {"groupId": "1", "maker": "-0.0014", "taker": "-0.0023"},
    {"groupId": "2", "maker": "-0.002", "taker": "-0.0035"},
    {"groupId": "11", "maker": "0", "taker": "0"},
    {"groupId": "17", "maker": "0", "taker": "-0.0005"}]}

def new_app(sim=True):
    app = M.OXXTerminalApp()
    app.simulation_mode = sim
    app.instrument_specs = {"BTC-USDT": BTC, "SHIB-USDT": SHIB}
    app.current_price = "86306.6"
    return app

print("fee groups")
app = new_app()
app.accountant.load_fee_schedule(FEE_ROW)
app.accountant.apply_fee_group("1")
check("group 1 (e.g. BTC) -> 0.14% / 0.23%", (app.accountant.maker_rate, app.accountant.taker_rate) == (0.0014, 0.0023))
app.accountant.apply_fee_group("2")
check("group 2 -> 0.20% / 0.35%", (app.accountant.maker_rate, app.accountant.taker_rate) == (0.002, 0.0035))
app.accountant.apply_fee_group(None)
check("unknown group -> worst case, not the cheapest", (app.accountant.maker_rate, app.accountant.taker_rate) == (0.002, 0.0035) and "worst" in app.accountant.tier_label)
app.accountant.apply_fee_group("17")
check("group 17 -> maker 0 / taker 0.05%", (app.accountant.maker_rate, app.accountant.taker_rate) == (0.0, 0.0005))

async def fee_flow():
    a = new_app()
    calls = {}
    class FakePriv:
        @staticmethod
        def get_trade_fee(t): return {"code": "0", "data": [FEE_ROW]}
    sys.modules["okx_private"].OKXPrivateClient = FakePriv   # update_accountant_fees imports it lazily
    await a.update_accountant_fees()
    return a
a = run(fee_flow())
sys.modules["okx_private"].OKXPrivateClient = _RealPriv
check("startup: BTC-USDT picks its group's rates", a.accountant.taker_rate == 0.0023 and a.accountant.tier_label.endswith("g1"), a.accountant.tier_label)
async def switch_fees():
    a.instrument_id = "SHIB-USDT"
    await a._apply_instrument_fees("SHIB-USDT")
run(switch_fees())
check("switching to a group-2 pair raises the estimate", a.accountant.taker_rate == 0.0035 and a.accountant.tier_label.endswith("g2"), a.accountant.tier_label)
check("fee line reaches the Execution Log panel", any("Fees LV1" in l for l in a.log_lines), a.log_lines)
okx_private_ref = importlib_reload = None

print("order flow (simulation)")
app = new_app()
app._last_tick = time.monotonic()
run(app._execute_order_task("buy", "limit", "0.00029746633052971317", "86000.123", None, None))
o = app.order_tracker.open_orders()[0]
check("size/price put on the exchange grid", abs(o.sz - 0.00029746) < 1e-12 and o.px == 86000.1, (o.sz, o.px))
check("a resting limit buy is OPEN and books NOTHING (accepted != filled)", app.session_fills == [] and app.accountant.positions.get("BTC-USDT", {}).get("size", 0) == 0 and app.accountant.fills == [])
check("history panel shows it as OPEN", "OPEN" in app._w["#history-content"].text and "SIM-Manual" in app._w["#history-content"].text, app._w["#history-content"].text)
app.current_price = "85900.0"; run(app._poll_orders())
check("when the market trades through it, it fills at ITS price (maker)", len(app.session_fills) == 1 and float(app.session_fills[0]["px"].replace(",", "")) == 86000.1, app.session_fills)
check("... reaches the ledger with an exchange-style fee, and the order closes", app.accountant.positions["BTC-USDT"]["size"] > 0 and app.accountant.total_fees_paid > 0 and not app.order_tracker.orders)
n = len(app.session_fills)
run(app._poll_orders()); run(app._poll_orders())
check("polling again never books it twice", len(app.session_fills) == n and len(app.accountant.fills) == 1)
app = new_app(); app._last_tick = time.monotonic()
run(app._execute_order_task("buy", "market", "0.001", "", None, None))
check("a market order fills immediately at the market price", len(app.session_fills) == 1 and float(app.session_fills[0]["px"].replace(",", "")) == 86306.6 and "SIM-Manual" in app._w["#history-content"].text, app.session_fills)
n = len(app.session_fills)
run(app._execute_order_task("buy", "limit", "0.000001", "86000", None, None))
check("below-minimum order is refused, not sent", len(app.session_fills) == n and not app.order_tracker.open_orders() and any("below the exchange minimum" in m for m, _ in app.notes), app.notes[-1:])
app2 = new_app(); app2.current_price = "Connecting..."
run(app2._execute_order_task("buy", "market", "0.001", "", None, None))
check("market order before a price exists is a notice, not a crash", any("no live price" in m for m, _ in app2.notes), app2.notes)
app3 = new_app(sim=False); app3.instrument_specs = {}
orig = api_client.OKXPublicClient.fetch_instrument
api_client.OKXPublicClient.fetch_instrument = staticmethod(lambda i: None)
run(app3._execute_order_task("buy", "limit", "0.001", "86000", None, None))
api_client.OKXPublicClient.fetch_instrument = orig
check("LIVE mode refuses to send when tick/lot size is unknown", any("refusing to send" in m for m, _ in app3.notes), app3.notes)

print("buttons")
app = new_app()
app._w["#amount-input"] = _W(); app._w["#amount-input"].value = "0.001"
for sel in ("#price-input", "#tp-input", "#sl-input"): app._w[sel] = _W()
ev = types.SimpleNamespace(button=types.SimpleNamespace(id="manual-buy-btn", label="BUY"))
app.on_button_pressed(ev)
check("BUY press schedules an order worker without touching label.text", len(app.workers) == 1 and app.workers[0].get("exit_on_error") is False)
app.on_button_pressed(types.SimpleNamespace(button=types.SimpleNamespace(id="save_btn", label="x")))
app.on_button_pressed(types.SimpleNamespace(button=types.SimpleNamespace(id="something-else", label="x")))
check("other buttons never reach order code", len(app.workers) == 1)

print("log panel")
app = new_app()
for i in range(6): app.log_action(f"[cyan]line {i}[/cyan]")
check("log keeps newest 4, newest first", app._w["#execution-log-content"].text.split("\n")[0].endswith("line 5[/cyan]") and len(app.log_lines) == 4)

print("order book")
app = new_app()
asks = [[f"{86300 + i/10:.1f}", "1", "0", "1"] for i in range(1, 401)]
bids = [[f"{86300 - i/10:.1f}", "1", "0", "1"] for i in range(0, 400)]
run(app.handle_ws_data("books", [{"action": "snapshot", "asks": asks, "bids": bids}]))
check("snapshot shows 5 levels per side", len(app.cached_asks) == 5 and len(app.cached_bids) == 5)
best = app.cached_asks[0][0]
run(app.handle_ws_data("books", [{"action": "update", "asks": [[best, "0", "0", "0"]], "bids": []}]))
check("removing the best ask is replaced by the next level (book doesn't shrink)", len(app.cached_asks) == 5 and best not in [a[0] for a in app.cached_asks], app.cached_asks)

print("tickers")
app = new_app()
run(app.handle_ws_data("tickers", [{"instId": "SHIB-USDT", "last": "0.00001234", "open24h": "0.00001200", "high24h": "0.00001300", "low24h": "0.00001100"}]))
check("SHIB price keeps its digits", "0.00001234" in app.telemetry_data["SHIB-USDT"]["last"], app.telemetry_data)
run(app.handle_ws_data("tickers", [{"instId": "BTC-USDT", "last": ""}]))
check("a malformed ticker doesn't raise", True)

print("start-up")
app = new_app()
app.client = None
async def startup_twice():
    app._start_terminal_services(); first = len(app.intervals)
    app._start_terminal_services(); return first, len(app.intervals)
first, second = run(startup_twice())
check("calling start-up again (Manage API Keys) adds no timers or second feed", first == second and first >= 5, (first, second))

print("bot loop")
app = new_app(); app.accountant.load_fee_schedule(FEE_ROW); app.accountant.apply_fee_group("1")
bot_id = app.strategy_manager.start_grid_bot("BTC-USDT", 85000, 88000, 5, 100)
async def stale_then_stop():
    app._last_tick = float("-inf")           # feed never ticked
    t = asyncio.create_task(app._run_bot_execution_loop(bot_id))
    await asyncio.sleep(1.3); app.strategy_manager.stop_all(); await asyncio.sleep(1.2)
    return t
run(stale_then_stop())
check("bot pauses on a stale feed (no orders, no crash)", not app.session_fills and any("Bot paused" in l for l in app.log_lines), app.log_lines)

print("worker groups")
async def chart_vs_workers():
    app = new_app()
    groups = {}
    def run_worker(work, name="", group="default", exit_on_error=True, exclusive=False, **kw):
        # Emulates Textual's documented rule: exclusive=True cancels every other worker in the group.
        if exclusive:
            for t in groups.pop(group, []): t.cancel()
        coro = work() if (callable(work) and not asyncio.iscoroutine(work)) else work
        t = asyncio.ensure_future(coro)
        groups.setdefault(group, []).append(t)
        return t
    app.run_worker = run_worker
    done = []
    async def slow(tag):
        await asyncio.sleep(0.2); done.append(tag)
    app.run_worker(slow("fees"), exit_on_error=False)   # same call shape as _start_terminal_services
    app.run_worker(slow("order"))                       # same call shape as a manual/bot order
    app.refresh_chart()                                 # what the 30s timer and the timeframe buttons do
    await asyncio.sleep(0.4)
    return sorted(done)
done = run(chart_vs_workers())
check("a chart refresh does not cancel in-flight fee/order workers", done == ["fees", "order"], done)

print("vault unlock")
async def mount_unlock():
    app = new_app(); app.client = None
    okx_private.OKXPrivateClient.clear_credentials_cache(); _Vault.loaded_on.clear()
    loop_thread = threading.get_ident()
    await app.on_mount()
    return loop_thread, list(_Vault.loaded_on), len(app.intervals)
loop_thread, loaded_on, n_int = run(mount_unlock())
check("start-up decrypts the vault OFF the UI thread, exactly once", len(loaded_on) == 1 and loaded_on[0] != loop_thread, (loop_thread, loaded_on))
check("services still start after the unlock", n_int >= 5, n_int)

print("credential dialog")
class _Field:
    def __init__(self, v): self.value = v
def make_modal(key="K", sec="S", ph="P"):
    mdl = M.AuthModal(); mdl._title = _W(); mdl.dismissed = []
    fields = {"#api_key_input": _Field(key), "#secret_key_input": _Field(sec), "#passphrase_input": _Field(ph)}
    mdl.query_one = lambda sel, typ=None: fields[sel] if isinstance(sel, str) else mdl._title
    mdl.dismiss = lambda v: mdl.dismissed.append(v)
    return mdl
async def modal_save(delay):
    _Vault.saved_on.clear(); _Vault.fail_save = False; _Vault.save_delay = delay
    mdl = make_modal(); loop_thread = threading.get_ident()
    await asyncio.gather(mdl._submit_credentials(), mdl._submit_credentials())   # double tap
    await mdl._submit_credentials()                                               # late third tap
    _Vault.save_delay = 0
    return loop_thread, list(_Vault.saved_on), mdl.dismissed
lt, saved_on, dismissed = run(modal_save(0.05))
check("saving keys runs off the UI thread", len(saved_on) == 1 and saved_on[0] != lt, (lt, saved_on))
check("double tap during a SLOW save: saved once, closed once", len(saved_on) == 1 and dismissed == [True], (saved_on, dismissed))
lt, saved_on, dismissed = run(modal_save(0))
check("double tap with an INSTANT save: saved once, closed once", len(saved_on) == 1 and dismissed == [True], (saved_on, dismissed))
async def modal_fail():
    _Vault.saved_on.clear(); _Vault.fail_save = True
    mdl = make_modal(); await mdl._submit_credentials(); _Vault.fail_save = False
    return mdl.dismissed, mdl._title.text
dismissed, text = run(modal_fail())
check("a failed save shows the error and keeps the dialog open", dismissed == [] and "Could not save" in text, (dismissed, text))
async def modal_empty():
    _Vault.saved_on.clear(); mdl = make_modal(ph=""); await mdl._submit_credentials()
    return list(_Vault.saved_on), mdl.dismissed
saved_on, dismissed = run(modal_empty())
check("missing field: nothing saved, dialog stays", saved_on == [] and dismissed == [])

print("order lifecycle: stop bots / cancel / bot state")
def sim_app():
    a = new_app(); a._last_tick = time.monotonic(); a.accountant.load_fee_schedule(FEE_ROW); a.accountant.apply_fee_group("12" if False else "1")
    a.sim_balances = {"USDT": 10000.0, "BTC": 1.0}
    return a
async def stop_cancels_bot_orders():
    a = sim_app()
    bot = a.strategy_manager.start_grid_bot("BTC-USDT", 85000, 88000, 5, 100)
    # a resting bot buy (below market) and a resting MANUAL buy
    await a._execute_order("buy", "limit", "0.0005", "85000", None, None, "GridBot", bot)
    await a._execute_order("buy", "limit", "0.0005", "84000", None, None, "Manual", None)
    before = len(a.order_tracker.open_orders())
    a.workers = []
    a.run_worker = lambda work, **kw: a.workers.append(work)
    a.action_stop_bot()
    for w in a.workers: await w
    return a, before
a, before = run(stop_cancels_bot_orders())
check("two orders were resting before the stop", before == 2, before)
left = a.order_tracker.open_orders()
check("STOP ALL BOTS cancels the bot's resting order but NOT the manual one", len(left) == 1 and left[0].bot_id is None, [(o.tag, o.bot_id) for o in left])
check("... and says what it did, truthfully", any("cancelled" in l.lower() for l in a.log_lines) and not any("NOT cancelled" in l and "resting exchange" in l for l in a.log_lines), a.log_lines)
async def cancel_button():
    a, _ = await stop_cancels_bot_orders()
    a.workers = []
    a.run_worker = lambda work, **kw: a.workers.append(work)
    a.on_button_pressed(types.SimpleNamespace(button=types.SimpleNamespace(id="cancel-orders-btn", label="x")))
    for w in a.workers: await w
    return a
a = run(cancel_button())
check("CANCEL MY OPEN ORDERS clears everything this session has open", not a.order_tracker.open_orders() and a.session_fills == [])
async def cancel_loses_race():
    a = sim_app()
    await a._execute_order("sell", "limit", "0.001", "86400", None, None, "Manual", None)   # resting sell above market
    a.current_price = "86500.0"                                                              # market trades through it before the cancel
    await a._cancel_orders(a.order_tracker.open_orders(), "test")
    return a
a = run(cancel_loses_race())
check("a fill that beats the cancel is booked, and reported as already filled", len(a.session_fills) == 1 and any("already filled" in l for l in a.log_lines), (a.session_fills, a.log_lines))
async def bot_state_follows_fills():
    a = sim_app()
    bot_id = a.strategy_manager.start_grid_bot("BTC-USDT", 85000, 88000, 5, 100)
    bot = a.strategy_manager.active_bots[bot_id]
    await a._execute_order("buy", "limit", "0.0005", "85000", None, None, "GridBot", bot_id)
    pos_resting = bot.current_pos
    a.current_price = "84900.0"; await a._poll_orders()
    return bot, pos_resting
bot, pos_resting = run(bot_state_follows_fills())
check("a bot's position does NOT move while its order only rests", pos_resting == 0.0, pos_resting)
check("... and moves by what it really holds once it fills (size less the fee taken in the coin)", abs(bot.current_pos - 0.0005 * (1 - 0.0014)) < 1e-12, bot.current_pos)
async def sell_reservation():
    a = sim_app()
    bot_id = a.strategy_manager.start_grid_bot("BTC-USDT", 85000, 88000, 5, 100)
    bot = a.strategy_manager.active_bots[bot_id]
    bot.order_filled("buy", 85000.0, 0.001)
    await a._execute_order("sell", "limit", "0.001", "89000", None, None, "GridBot", bot_id)   # resting sell for ALL of it
    reserved = bot.open_sell_qty
    await a._cancel_orders(a.order_tracker.open_orders(), "test")
    return reserved, bot.open_sell_qty
reserved, after = run(sell_reservation())
check("a resting sell reserves the coins, and cancelling releases them", abs(reserved - 0.001) < 1e-9 and after == 0.0, (reserved, after))
async def lost_answer():
    a = sim_app()
    import okx_private as _op
    a.simulation_mode = False
    real = _op.OKXPrivateClient
    class Timeout:
        placed = []
        @staticmethod
        def place_order(**kw): Timeout.placed.append(kw); return {"code": "500", "msg": "timed out"}
        @staticmethod
        def get_order(i, o=None, c=None): return {"code": "51603", "msg": "Order does not exist", "data": []}
    sys.modules["okx_private"].OKXPrivateClient = Timeout
    try:
        await a._execute_order("buy", "limit", "0.001", "85000", None, None, "Manual", None)
    finally:
        sys.modules["okx_private"].OKXPrivateClient = real
    return a, Timeout.placed
a, placed = run(lost_answer())
o = a.order_tracker.open_orders()
check("a timed-out placement is tracked as UNKNOWN, not reported as failed or filled", len(o) == 1 and o[0].uncertain and a.session_fills == [], o)
check("... it carries a client order id so it can be looked up", placed and placed[0].get("cl_ord_id", "").startswith("oxx"), placed)
check("... and the user is told not to resend", any("do NOT resend" in m for m, _ in a.notes), a.notes)
check("history shows it as status unknown", "status unknown" in a._w["#history-content"].text, a._w["#history-content"].text)

print("positions panel (simulation)")
async def sim_panel():
    a = sim_app()
    import okx_private as _op
    real = _op.OKXPrivateClient
    class Real:
        calls = 0
        @staticmethod
        def get_pending_orders(): Real.calls += 1; return {"code": "0", "data": []}
        @staticmethod
        def get_positions(): Real.calls += 1; return {"code": "0", "data": []}
    sys.modules["okx_private"].OKXPrivateClient = Real
    try:
        await a._execute_order("buy", "limit", "0.001", "80000", None, None, "Manual", None)   # rests
        await a._execute_order("buy", "market", "0.001", "", None, None, "Manual", None)       # fills
        await a._update_open_orders_and_positions()
    finally:
        sys.modules["okx_private"].OKXPrivateClient = real
    return a, Real.calls
a, calls = run(sim_panel())
txt = a._w["#positions-content"].text
check("sim panel does NOT ask the real account", calls == 0, calls)
check("sim panel lists the resting simulated order", "80,000" in txt and "BUY" in txt, txt)
check("... and never says 'No open resting orders' next to it", "No open resting orders" not in txt, txt)
check("... shows the simulated position that the market buy created", "Positions" in txt and "No simulated positions" not in txt, txt)
check("... and the [SIM] label survives Rich markup", "[SIM]" in txt.replace("\\[", "["), txt)

print("TP/SL")
async def tpsl():
    a = sim_app()
    await a._execute_order_task("buy", "limit", "0.001", "80000", "90000", None)
    await a._execute_order_task("buy", "limit", "0.001", "80000", None, "70000")
    return a
a = run(tpsl())
check("TP or SL on an order is refused (nothing is sent or tracked)", a.order_tracker.open_orders() == [], a.order_tracker.open_orders())
check("... with a clear reason shown to the user", sum("TP/SL" in m for m, _ in a.notes) == 2, a.notes)

print("simulated wallet")
async def wallet():
    a = sim_app(); a.sim_balances = {"USDT": 1000.0}
    await a._execute_order_task("buy", "limit", "0.1", "86000", None, None)          # ~8,600 USDT: too much
    too_big = list(a.order_tracker.open_orders())
    await a._execute_order_task("sell", "market", "0.001", "", None, None)           # no BTC held
    no_coins = list(a.order_tracker.open_orders())
    return a, too_big, no_coins
a, too_big, no_coins = run(wallet())
check("a buy larger than the wallet is refused like the real exchange would", too_big == [], too_big)
check("selling coins you do not hold is refused", no_coins == [], no_coins)
check("... and the user is told why", any("insufficient simulated" in m for m, _ in a.notes), a.notes)

async def wallet_moves():
    a = sim_app(); a.sim_balances = {"USDT": 10000.0, "BTC": 1.0}
    await a._execute_order_task("buy", "market", "0.01", "", None, None)
    return a
a = run(wallet_moves())
check("a filled buy spends USDT at the fill price", abs(a.sim_balances["USDT"] - (10000 - 0.01 * 86306.6)) < 0.01, a.sim_balances)
check("... and adds the coin, less the fee taken in the coin", abs(a.sim_balances["BTC"] - (1.01 - 0.01 * 0.0023)) < 1e-6, a.sim_balances)
check("the wallet panel shows it, labelled [SIM]", "[SIM]" in a._w["#portfolio-balance"].text.replace("\\[", "["), a._w["#portfolio-balance"].text)

async def reserve():
    a = sim_app(); a.sim_balances = {"USDT": 100.0}
    await a._execute_order_task("buy", "limit", "0.001", "80000", None, None)        # rests, ~80.2 locked
    first = len(a.order_tracker.open_orders()); avail = a._sim_available("USDT")
    await a._execute_order_task("buy", "limit", "0.001", "80000", None, None)        # would need ~80 more
    return a, first, avail
a, first, avail = run(reserve())
check("a resting buy locks its funds (size x price: the fee comes out of the coin)", first == 1 and abs(avail - 20.0) < 1e-6, (first, avail))
check("... so a second order that no longer fits is refused", len(a.order_tracker.open_orders()) == 1, a.order_tracker.open_orders())
check("... while the wallet balance itself is untouched until a fill", a.sim_balances["USDT"] == 100.0, a.sim_balances)

print("percent buttons")
a = sim_app(); a._render_sim_wallet()
a.query_one("#price-input").value = ""
a.action_quick_load_amount(0.5)
buy_amt = a.query_one("#amount-input").value
check("holding both coins, % sizes a BUY by default", abs(float(buy_amt) - 5000 / (1 + M.BUY_HEADROOM) / 86306.6) < 1e-5, buy_amt)
btn = types.SimpleNamespace(id="pct-side", label="")
a.on_button_pressed(types.SimpleNamespace(button=btn))
a.action_quick_load_amount(0.5)
check("the switch makes % size a SELL of the coin held", float(a.query_one("#amount-input").value) == 0.5 and "SELL" in btn.label, (a.query_one("#amount-input").value, btn.label))
a.on_button_pressed(types.SimpleNamespace(button=btn))
check("... and switches back", a.pct_side == "buy" and "BUY" in btn.label, btn.label)

print("estimates follow the market")
a = sim_app(); a.accountant.apply_fee_group("1")
a.query_one("#price-input").value = ""; a.query_one("#amount-input").value = "0.01"
a._refresh_preflight_if_market()
fee1 = a.query_one("#preflight-fee").text
a.current_price = "90000.0"; a._refresh_preflight_if_market()
check("with no price typed (market order) the fee estimate follows the live price", a.query_one("#preflight-fee").text != fee1, (fee1, a.query_one("#preflight-fee").text))
a.query_one("#price-input").value = "80000"; a._refresh_preflight_if_market(); frozen = a.query_one("#preflight-fee").text
a.current_price = "95000.0"; a._refresh_preflight_if_market()
check("with a limit price typed it is left alone", a.query_one("#preflight-fee").text == frozen)

print("orders left from an earlier session (live)")
class FakePriv:
    rows = [{"ordId": "111", "clOrdId": "abc", "instId": "BTC-USDT", "side": "buy", "ordType": "limit",
             "sz": "0.002", "px": "80000", "accFillSz": "0.0005", "avgPx": "80000"}]
    code = "0"
    @staticmethod
    def get_pending_orders(): return {"code": FakePriv.code, "msg": "boom", "data": FakePriv.rows}
async def adopt():
    real = sys.modules["okx_private"].OKXPrivateClient
    sys.modules["okx_private"].OKXPrivateClient = FakePriv
    try:
        a = new_app(sim=False)
        await a._adopt_open_orders(); await a._adopt_open_orders()
        b = new_app(sim=False); FakePriv.code = "50000"; await b._adopt_open_orders(); FakePriv.code = "0"
        c = new_app(sim=True); await c._adopt_open_orders()
        FakePriv.rows = [dict(FakePriv.rows[0], clOrdId="")]          # older orders carry no client id
        d = new_app(sim=False); await d._adopt_open_orders(); await d._adopt_open_orders()
        FakePriv.rows = [dict(FakePriv.rows[0], clOrdId="mine1")]     # one this session placed itself
        e = new_app(sim=False)
        e.order_tracker.register(M.TrackedOrder(cl_ord_id="mine1", inst_id="BTC-USDT", side="buy", ord_type="limit",
                                                sz=0.002, px=80000.0, tag="GridBot", bot_id="g1", ord_id="111"))
        await e._adopt_open_orders()
    finally:
        sys.modules["okx_private"].OKXPrivateClient = real
    return a, b, c, d, e
a, b, c, d, e = run(adopt())
o = a.order_tracker.open_orders()
check("an order already open on OKX is tracked at start-up, once", len(o) == 1 and o[0].ord_id == "111" and o[0].tag == "Adopted", o)
check("... fills from before this session are not booked as new ones", o and o[0].booked_sz == 0.0005 and a.accountant.fills == [], o)
check("a failed lookup is said out loud, not silently ignored", any("NOT tracked" in l for l in b.log_lines), b.log_lines)
check("simulation never asks the real account", c.order_tracker.open_orders() == [])
check("orders without a client id are not adopted twice", len(d.order_tracker.open_orders()) == 1, d.order_tracker.open_orders())
check("an order this session already tracks keeps its bot and tag", [(o.tag, o.bot_id) for o in e.order_tracker.open_orders()] == [("GridBot", "g1")], e.order_tracker.open_orders())

print("quit with open orders")
async def quits():
    out = {}
    a = new_app(sim=False); a.exit = lambda: a.notes.append(("EXIT", {}))
    await a.action_quit(); out["no_orders"] = [m for m, _ in a.notes] == ["EXIT"]
    b = new_app(sim=False); b.exit = lambda: b.notes.append(("EXIT", {}))
    b.order_tracker.register(M.TrackedOrder(cl_ord_id="x1", inst_id="BTC-USDT", side="buy", ord_type="limit", sz=0.001, px=80000.0))
    await b.action_quit(); out["first"] = [m for m, _ in b.notes]
    await b.action_quit(); out["second"] = [m for m, _ in b.notes]
    b._quit_armed_at = time.monotonic() - 1000; b.notes.clear()
    await b.action_quit(); out["stale"] = [m for m, _ in b.notes]
    c = new_app(sim=True); c.exit = lambda: c.notes.append(("EXIT", {}))
    c.order_tracker.register(M.TrackedOrder(cl_ord_id="x2", inst_id="BTC-USDT", side="buy", ord_type="limit", sz=0.001, px=80000.0))
    await c.action_quit(); out["sim"] = [m for m, _ in c.notes]
    return out
q = run(quits())
check("quitting with nothing resting just quits", q["no_orders"])
check("with a LIVE order resting, the first quit warns and does not exit", len(q["first"]) == 1 and "STAY" in q["first"][0], q["first"])
check("... a second quit quits", q["second"][-1] == "EXIT", q["second"])
check("... an old warning does not count as confirmation", len(q["stale"]) == 1 and "STAY" in q["stale"][0], q["stale"])
check("simulated orders never block quitting", q["sim"] == ["EXIT"], q["sim"])

print("websocket host")
async def ws_runs():
    real_sleep, real_connect = asyncio.sleep, getattr(api_client.websockets, "connect", None)
    real_cc = api_client.websockets.exceptions.ConnectionClosed
    class CC(Exception): pass          # the stub makes ConnectionClosed == Exception; real network errors are NOT
    api_client.websockets.exceptions.ConnectionClosed = CC
    tried, stay = [], []
    class Boom:
        def __init__(self, uri): tried.append(uri); raise OSError("no route")
    class Good:
        def __init__(self, uri): stay.append(uri)
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def send(self, m): pass
        def __aiter__(self): return self._gen()
        async def _gen(self):
            yield json.dumps({"arg": {"channel": "tickers"}, "data": [{}]})
            raise CC("closed")
    async def limited(n):
        counter = [0]
        async def fake_sleep(x):
            counter[0] += 1
            if counter[0] >= n: raise asyncio.CancelledError()
        asyncio.sleep = fake_sleep
    try:
        api_client.websockets.connect = Boom
        await limited(3)
        try: await api_client.OKXPublicClient("BTC-USDT").connect_market_streams()
        except asyncio.CancelledError: pass
        api_client.websockets.connect = Good
        await limited(3)
        try: await api_client.OKXPublicClient("BTC-USDT").connect_market_streams()
        except asyncio.CancelledError: pass
    finally:
        asyncio.sleep = real_sleep
        api_client.websockets.exceptions.ConnectionClosed = real_cc
        if real_connect: api_client.websockets.connect = real_connect
    return tried, stay
tried, stay = run(ws_runs())
check("the US host is tried first", tried[0] == "wss://wsus.okx.com/ws/v5/public", tried)
check("a host that never connects is abandoned for the other one", tried[1] == "wss://ws.okx.com:8443/ws/v5/public", tried)
check("a host that delivers data is kept across reconnects", len(set(stay)) == 1 and len(stay) >= 3, stay)

print("what you hold after a buy")
async def hold_and_sell():
    a = sim_app(); a.sim_balances = {"USDT": 10000.0}
    await a._execute_order_task("buy", "market", "0.01", "", None, None)
    held_wallet = a.sim_balances["BTC"]
    held_ledger = a.accountant.positions["BTC-USDT"]["size"]
    bot_id = a.strategy_manager.start_grid_bot("BTC-USDT", 85000, 88000, 5, 100)
    await a._execute_order("buy", "market", "0.01", "", None, None, "GridBot", bot_id)
    bot = a.strategy_manager.active_bots[bot_id]
    sell_sz = format(bot.current_pos, ".8f")
    await a._execute_order_task("sell", "market", sell_sz, "", None, None, tag="Manual")   # sell everything the bot thinks it holds
    return a, held_wallet, held_ledger, bot
a, held_wallet, held_ledger, bot = run(hold_and_sell())
check("the ledger holds what the wallet holds (fee taken from the coin), not the gross size", abs(held_ledger - held_wallet) < 1e-9, (held_ledger, held_wallet))
check("a bot's position is sellable: selling all of it is accepted, never 'insufficient'", not any("insufficient" in m for m, _ in a.notes), a.notes)

print("100% buy button")
async def full_buy():
    a = sim_app(); a.sim_balances = {"USDT": 1000.0}; a._render_sim_wallet()
    a.query_one("#price-input").value = ""
    a.action_quick_load_amount(1.0)
    amt = a.query_one("#amount-input").value
    await a._execute_order_task("buy", "market", amt, "", None, None)
    return a
a = run(full_buy())
check("the 100% button builds an order the wallet accepts", len(a.session_fills) == 1 and not any("insufficient" in m for m, _ in a.notes), a.notes)
check("... and leaves a little USDT back, never a negative balance", 0 <= a.sim_balances["USDT"] < 10, a.sim_balances)

print("100% sell rounding")
async def sell_all(balance, with_spec=True):
    a = sim_app(); a.sim_balances = {"USDT": 1000.0, "BTC": balance}; a._render_sim_wallet()
    if not with_spec: a.instrument_specs = {}
    a.pct_side = "sell"; a.query_one("#price-input").value = ""
    a.action_quick_load_amount(1.0)
    amt = a.query_one("#amount-input").value
    await a._execute_order_task("sell", "market", amt, "", None, None)
    return a, amt
a, amt = run(sell_all(0.0119949))
check("100% SELL of a balance that rounds UP at 6 decimals is accepted (the case seen on the phone)", len(a.session_fills) == 1 and float(amt) <= 0.0119949, (amt, a.notes))
a, amt = run(sell_all(0.0119949, with_spec=False))
check("... also when the lot size is unknown (falls back to rounding down at 6 decimals)", amt == "0.011994" and len(a.session_fills) == 1, (amt, a.notes))
import random
random.seed(7); bad = []
for _ in range(60):
    bal = random.uniform(0.00001, 3.0)
    a, amt = run(sell_all(bal))
    if not (a.session_fills and float(amt) <= bal): bad.append((bal, amt))
check("60 random balances: a 100% SELL is never larger than what is held and is always accepted", not bad, bad[:3])
async def buy_pct(p, usdt):
    a = sim_app(); a.sim_balances = {"USDT": usdt}; a._render_sim_wallet()
    a.query_one("#price-input").value = ""
    a.action_quick_load_amount(p)
    await a._execute_order_task("buy", "market", a.query_one("#amount-input").value, "", None, None)
    return a
bad = []
for _ in range(40):
    a = run(buy_pct(random.choice([0.25, 0.5, 0.75, 1.0]), random.uniform(20, 5000)))
    if not a.session_fills or a.sim_balances["USDT"] < 0: bad.append((a.notes, a.sim_balances))
check("40 random BUYs from the % buttons are always accepted and never overdraw the wallet", not bad, bad[:2])

print("price box: typed price vs market price")
def press_btn(a, bid):
    a.workers = []; a.run_worker = lambda w, **k: a.workers.append(w)
    a.on_button_pressed(types.SimpleNamespace(button=types.SimpleNamespace(id=bid, label="")))
    return a.workers
def type_price(a, text):
    a.query_one("#price-input").value = text
    a.on_input_changed(types.SimpleNamespace(input=types.SimpleNamespace(id="price-input"), value=text))
async def stale_price_flow():
    a = sim_app(); a.sim_balances = {"USDT": 1000.0}; a._render_sim_wallet()
    a.current_price = "82838.8"; a.action_quick_load_amount(1.0)
    first_box = a.query_one("#price-input").value
    for w in press_btn(a, "manual-buy-btn"): await w
    a.current_price = "82798.1"; a._last_tick = time.monotonic()      # the market moved down a while later
    a.pct_side = "sell"; a._render_sim_wallet(); a.action_quick_load_amount(1.0)
    second_box = a.query_one("#price-input").value
    for w in press_btn(a, "manual-sell-btn"): await w
    return a, first_box, second_box
a, first_box, second_box = run(stale_price_flow())
check("the first quick-fill shows the live price", first_box == "82838.8", first_box)
check("a LATER quick-fill shows the price NOW, not the old one", second_box == "82798.1", second_box)
check("... and the SELL went out as a market order: it filled at once, nothing left resting",
      a.order_tracker.open_orders() == [] and [f["side"] for f in a.session_fills] == ["SELL", "BUY"], (a.session_fills, a.order_tracker.open_orders()))
check("... at the live price", a.accountant.fills[-1]["px"] == 82798.1, a.accountant.fills[-1])
check("... leaving no coins locked by a stale resting order", a._sim_available("BTC") < 1e-6, a._sim_available("BTC"))

async def typed_price_flow():
    a = sim_app(); a.sim_balances = {"USDT": 1000.0, "BTC": 0.01}; a._render_sim_wallet()
    a.current_price = "82798.1"; a.pct_side = "sell"
    type_price(a, "90000")
    a.action_quick_load_amount(1.0)
    box = a.query_one("#price-input").value
    for w in press_btn(a, "manual-sell-btn"): await w
    return a, box
a, box = run(typed_price_flow())
o = a.order_tracker.open_orders()
check("a price the USER typed is kept by the quick-fill", box == "90000", box)
check("... and the order is a LIMIT at that price (rests above the market)", len(o) == 1 and o[0].ord_type == "limit" and o[0].px == 90000.0, o)

a = sim_app(); a.sim_balances = {"USDT": 1000.0}; a._render_sim_wallet()
a.current_price = "82838.8"; a.action_quick_load_amount(0.5)
a.current_price = "82700.0"; a._refresh_preflight_if_market()
check("the filled-in price follows each market tick", a.query_one("#price-input").value == "82700.0", a.query_one("#price-input").value)
type_price(a, "82500")
a.current_price = "81000.0"; a._refresh_preflight_if_market()
check("once the user edits the box it stops following the market", a.query_one("#price-input").value == "82500", a.query_one("#price-input").value)
a.query_one("#price-input").value = ""; type_price(a, "")
a.current_price = "82838.8"; a.action_quick_load_amount(0.5)
check("clearing the box returns to market pricing", a._price_is_auto(), a._auto_px)

shib = new_app(); shib.instrument_id = "SHIB-USDT"
check("cheap coins keep their digits in the price box (not 0.00)", shib._price_text("SHIB-USDT", 0.00000548) == "0.00000548", shib._price_text("SHIB-USDT", 0.00000548))
unknown = new_app(); unknown.instrument_specs = {}
check("... also without a tick size", unknown._price_text("SHIB-USDT", 0.00000548) == "0.00000548" and unknown._price_text("BTC-USDT", 82798.1) == "82798.10")

a = sim_app(); a.sim_balances = {"USDT": 1000.0}; a._render_sim_wallet(); a.current_price = "82838.8"; a.action_quick_load_amount(1.0)
try: a.action_switch_instrument("SHIB-USDT")
except Exception: pass
check("switching pairs drops the old pair's price from the box", a.query_one("#price-input").value == "" and a._auto_px is None, (a.query_one("#price-input").value, a._auto_px))

async def stale_box_still_market():
    a = sim_app(); a.sim_balances = {"USDT": 1000.0, "BTC": 0.01}; a._render_sim_wallet()
    a.current_price = "82838.8"; a.pct_side = "sell"; a.action_quick_load_amount(1.0)   # box = 82838.8
    a.current_price = "82700.0"                                                          # market falls; the box is NOT refreshed
    for w in press_btn(a, "manual-sell-btn"): await w
    return a
a = run(stale_box_still_market())
check("a SELL sent while the box still shows an old filled-in price goes out at the LIVE price (market order)",
      a.order_tracker.open_orders() == [] and a.accountant.fills and a.accountant.fills[-1]["px"] == 82700.0, (a.accountant.fills, a.order_tracker.open_orders()))

a = sim_app(); a.sim_balances = {"USDT": 1000.0}; a._render_sim_wallet()
a.current_price = "82700.0"; a.action_quick_load_amount(0.5)         # app fills 82700.0
type_price(a, "82705"); type_price(a, "82700.0")                      # user edits, then types the same text again
a.current_price = "81000.0"; a._refresh_preflight_if_market()
check("a price the user typed stays theirs, even if it equals the text the app once filled in", a.query_one("#price-input").value == "82700.0" and not a._price_is_auto(), (a.query_one("#price-input").value, a._auto_px))

print("order form resets after an order")
def box(a, wid): return a.query_one(wid).value
async def after_order(kind):
    a = sim_app(); a.sim_balances = {"USDT": 1000.0, "BTC": 0.01}; a._render_sim_wallet()
    a.current_price = "82838.8"
    if kind == "typed_limit":
        type_price(a, "80000"); a.query_one("#amount-input").value = "0.001"
    else:
        a.action_quick_load_amount(0.5)
    for w in press_btn(a, "manual-buy-btn"): await w
    return a
for kind in ("quick_fill", "typed_limit"):
    a = run(after_order(kind))
    check(f"after a BUY ({kind}) the Price, Amount and Total boxes are empty", (box(a, "#price-input"), box(a, "#amount-input"), box(a, "#total-input")) == ("", "", ""), (box(a, "#price-input"), box(a, "#amount-input"), box(a, "#total-input")))
check("... and the filled-in-price flag is cleared", a._auto_px is None)

async def refused_keeps_form():
    a = sim_app(); a.sim_balances = {"USDT": 10.0}; a._render_sim_wallet()
    a.current_price = "82838.8"; a.query_one("#amount-input").value = "1"      # far more than the wallet
    for w in press_btn(a, "manual-buy-btn"): await w
    return a
a = run(refused_keeps_form())
check("a REFUSED order leaves the form alone so it can be corrected", box(a, "#amount-input") == "1" and a.order_tracker.open_orders() == [], box(a, "#amount-input"))

async def bot_leaves_form():
    a = sim_app(); a.sim_balances = {"USDT": 1000.0}; a._render_sim_wallet()
    a.query_one("#amount-input").value = "0.5"; type_price(a, "81000")
    bot_id = a.strategy_manager.start_grid_bot("BTC-USDT", 85000, 88000, 5, 100)
    await a._execute_order("buy", "market", "0.001", "", None, None, "GridBot", bot_id)
    return a
a = run(bot_leaves_form())
check("a bot's order does NOT wipe what the user is typing", box(a, "#amount-input") == "0.5" and box(a, "#price-input") == "81000", (box(a, "#amount-input"), box(a, "#price-input")))

async def lost_answer_clears():
    real = sys.modules["okx_private"].OKXPrivateClient
    class Timeout:
        @staticmethod
        def place_order(**kw): return {"code": "500", "msg": "timed out"}
        @staticmethod
        def get_order(i, o=None, c=None): return {"code": "51603", "msg": "Order does not exist", "data": []}
    sys.modules["okx_private"].OKXPrivateClient = Timeout
    try:
        a = new_app(sim=False); a._last_tick = time.monotonic(); a.current_price = "82838.8"
        a.query_one("#amount-input").value = "0.001"; type_price(a, "80000")
        for w in press_btn(a, "manual-buy-btn"): await w
    finally:
        sys.modules["okx_private"].OKXPrivateClient = real
    return a
a = run(lost_answer_clears())
check("when the exchange's answer is LOST the form is cleared too (no accidental double send)", box(a, "#amount-input") == "" and len(a.order_tracker.open_orders()) == 1, (box(a, "#amount-input"), a.order_tracker.open_orders()))

print("pressing a % button again re-prices")
a = sim_app(); a.sim_balances = {"USDT": 1000.0}; a._render_sim_wallet()
a.current_price = "82838.8"; a.action_quick_load_amount(1.0)
amt1, px1, tot1 = box(a, "#amount-input"), box(a, "#price-input"), box(a, "#total-input")
a.current_price = "82000.0"; a.action_quick_load_amount(1.0)           # waited for a better price, pressed again, did not buy
amt2, px2, tot2 = box(a, "#amount-input"), box(a, "#price-input"), box(a, "#total-input")
check("the second press replaces the price with the new market price", (px1, px2) == ("82838.8", "82000.0"), (px1, px2))
check("... and the amount is recalculated for it (more coins at the lower price)", float(amt2) > float(amt1), (amt1, amt2))
check("... and the total follows", abs(float(tot2) - float(tot1)) < 0.01 and abs(float(amt2) * 82000.0 - float(tot2)) < 0.5, (tot1, tot2, amt2))

async def retype_old_price():
    a = sim_app(); a.sim_balances = {"USDT": 1000.0, "BTC": 0.01}; a._render_sim_wallet()
    a.current_price = "82838.8"; a.action_quick_load_amount(0.5)
    for w in press_btn(a, "manual-buy-btn"): await w                      # form is reset after the order
    a.current_price = "82700.0"
    type_price(a, "82838.8"); a.query_one("#amount-input").value = "0.001"  # user deliberately types the OLD price as a limit
    for w in press_btn(a, "manual-sell-btn"): await w
    return a
a = run(retype_old_price())
o = [x for x in a.order_tracker.open_orders() if x.side == "sell"]
check("after an order, typing the same price as before is the USER's limit price, not 'market'", len(o) == 1 and o[0].ord_type == "limit" and o[0].px == 82838.8, (o, a.accountant.fills))

print(f"\n{PASSED} passed, {len(FAILED)} failed")
if FAILED: print("FAILED:", *FAILED, sep="\n  - "); sys.exit(1)
