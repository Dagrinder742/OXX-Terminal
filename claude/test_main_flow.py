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
check("size/price put on the exchange grid", app.session_fills[0]["sz"] == "0.00029746" and app.session_fills[0]["px"] == "86000.1", app.session_fills[:1])
check("sim fill reaches the ledger", app.accountant.positions["BTC-USDT"]["size"] > 0)
check("history panel updated", "SIM-Manual" in app._w["#history-content"].text)
n = len(app.session_fills)
run(app._execute_order_task("buy", "limit", "0.000001", "86000", None, None))
check("below-minimum order is refused, not sent", len(app.session_fills) == n and any("below the exchange minimum" in m for m, _ in app.notes), app.notes[-1:])
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
    app._last_tick = 0.0                      # feed never ticked
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
async def modal_save():
    _Vault.saved_on.clear(); _Vault.fail_save = False
    mdl = make_modal(); loop_thread = threading.get_ident()
    await asyncio.gather(mdl._submit_credentials(), mdl._submit_credentials())   # double tap
    return loop_thread, list(_Vault.saved_on), mdl.dismissed
lt, saved_on, dismissed = run(modal_save())
check("saving keys runs off the UI thread", len(saved_on) == 1 and saved_on[0] != lt, (lt, saved_on))
check("a double tap saves once and closes once", len(saved_on) == 1 and dismissed == [True], (saved_on, dismissed))
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

print(f"\n{PASSED} passed, {len(FAILED)} failed")
if FAILED: print("FAILED:", *FAILED, sep="\n  - "); sys.exit(1)
