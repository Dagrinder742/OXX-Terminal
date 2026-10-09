"""Pure-logic tests for the OXX Terminal modules.

Run from the project folder:   python test_oxx_logic.py

* No Textual, no network, no real credentials: secure_vault is replaced by a stub and
  requests.get/post are replaced by recorders, so nothing here can touch your account.
* These prove the MATH and REQUEST-BUILDING are right.  They do not prove the UI
  renders correctly or that OKX accepts the orders -- see the checklist in the notes.
"""
import base64
import hashlib
import hmac
import json
import logging
import sys
import types

# ---- isolate from the real vault before anything imports it
class _StubVault:
    creds = {"api_key": "KEY", "secret_key": "SECRET", "passphrase": "PASS"}

    @classmethod
    def load_credentials(cls):
        return cls.creds

sys.modules["secure_vault"] = types.SimpleNamespace(EncryptedVault=_StubVault)
logging.disable(logging.CRITICAL)

from order_format import quantize_size, quantize_price, fmt_price, fmt_qty, money
from accountant import PnLAccountant
from strategy_engine import GridStrategyEngine, DCAStrategyEngine, OKXGridValidator
import okx_private
from okx_private import OKXPrivateClient

PASSED, FAILED = 0, []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok    {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


print("order_format")
check("long float size -> exact lot multiple", quantize_size(100 / 5 / 67234.5, "0.00000001") == "0.00029746")
check("scientific-notation size handled", quantize_size(5.00000005e-09, "0.00000001") == "0")
check("size rounds DOWN, never up", quantize_size("0.99999999", "0.001") == "0.999")
check("price snaps to tick", quantize_price("86000.123", "0.1") == "86000.1")
check("cheap-coin price keeps its digits", quantize_price("0.00001234", "0.00000001") == "0.00001234")
check("'$' and ',' tolerated", quantize_price("$86,000.16", "0.1") == "86000.2")
check("SHIB price displays", "0.00001234" in fmt_price(0.00001234))
check("BTC price displays 2 dp", fmt_price(86306.6) == "86,306.60")
check("tiny size never shows as 0.0000", fmt_qty(0.00001) == "0.00001000")
check("negative money keeps sign in front", money(-1.5) == "-$1.50")

print("accountant")
a = PnLAccountant(taker_fee_rate=0, maker_fee_rate=0)
a.allow_short = True
a.record_confirmed_fill("X", "buy", 100, 1)
a.record_confirmed_fill("X", "sell", 100, 3)
check("long -> short flip: new avg is the flip price", approx(a.positions["X"]["avg_price"], 100) and approx(a.positions["X"]["size"], -2))
b = PnLAccountant(taker_fee_rate=0, maker_fee_rate=0)
b.allow_short = True
b.record_confirmed_fill("X", "sell", 100, 1)
b.record_confirmed_fill("X", "buy", 90, 3)
check("short -> long flip: new avg is the flip price", approx(b.positions["X"]["avg_price"], 90) and approx(b.positions["X"]["size"], 2))
check("short covered at a lower price realizes profit", approx(b.realized_pnl_gross, 10))
c = PnLAccountant(taker_fee_rate=0, maker_fee_rate=0)
c.record_confirmed_fill("X", "buy", 100, 2)
c.record_confirmed_fill("X", "sell", 110, 1)
check("partial close keeps entry price, realizes gain", approx(c.positions["X"]["avg_price"], 100) and approx(c.realized_pnl_gross, 10))
d = PnLAccountant(taker_fee_rate=0.0035, maker_fee_rate=0.002)
d.record_confirmed_fill("BTC-USDT", "sell", 100, 1)  # coins held before the session
check("selling untracked inventory books only the fee (no fake short profit)",
      d.positions["BTC-USDT"]["size"] == 0 and approx(d.get_session_summary({"BTC-USDT": 90})["net"], -0.35))
e = PnLAccountant(taker_fee_rate=0, maker_fee_rate=0)
e.record_confirmed_fill("X", "buy", 100, 1)
e.record_confirmed_fill("X", "sell", 100, 3)
check("over-selling a long ends flat on spot", e.positions["X"]["size"] == 0)
f = PnLAccountant(taker_fee_rate=0.0023, maker_fee_rate=0.0014)
m = f.calculate_preflight_metrics(86000, 0.001, 87000, 85000)
check("hurdle = entry*(1+taker)/(1-maker)", approx(m["break_even"], 86000 * 1.0023 / (1 - 0.0014), 1e-6))
check("TP under the hurdle is a negative net", f.calculate_preflight_metrics(86000, 0.001, 86100, None)["net_tp"] < 0)

acc2 = PnLAccountant()
acc2.record_confirmed_fill("BTC-USDT", "buy", 100.0, 1.0, fee_quote=0.07)
check("an exchange-reported fee is used instead of the rate estimate", abs(acc2.total_fees_paid - 0.07) < 1e-12, acc2.total_fees_paid)
acc3 = PnLAccountant(); acc3.record_confirmed_fill("BTC-USDT", "buy", 100.0, 1.0)
check("without one, the estimate still applies", abs(acc3.total_fees_paid - 100.0 * acc3.taker_rate) < 1e-9)

print("grid strategy")
g = GridStrategyEngine("BTC-USDT", 98, 102, 5, 100)
g.process_tick(100.0)
flicker = [g.process_tick(100.01 if i % 2 == 0 else 99.99) for i in range(40)]
check("price flickering around a level fires nothing", all(s is None for s in flicker), [s for s in flicker if s])
g2 = GridStrategyEngine("BTC-USDT", 98, 102, 5, 100)
g2.process_tick(99.0)
sig = g2.process_tick(100.6)
check("no inventory -> no SELL", sig is not None and sig[0] == "LOG", sig)
g3 = GridStrategyEngine("BTC-USDT", 98, 102, 5, 100)
g3.process_tick(101.0)
buy = g3.process_tick(99.5)
check("falling through a level -> BUY", buy is not None and buy[0] == "BUY", buy)
g3.update_position("buy", buy[1], buy[2])
sell = g3.process_tick(101.2)
check("rising later -> SELL, no more than the bot holds", sell is not None and sell[0] == "SELL" and sell[2] <= g3.current_pos + 1e-12, sell)
shib = GridStrategyEngine("SHIB-USDT", 0.0000090, 0.0000110, 5, 100)
check("cheap-coin grid levels are distinct and non-zero", len(set(shib.grid_levels)) == 5 and min(shib.grid_levels) > 0, shib.grid_levels)
g4 = GridStrategyEngine("BTC-USDT", 98, 102, 5, 100)
g4.process_tick(101.0); g4.process_tick(99.5)
g4.order_filled("buy", 99.5, 0.001)                      # bot now really holds 0.001
g4.order_placed("sell", 0.001)                           # ...and has promised all of it to a resting sell
skip = g4.process_tick(101.2)
check("coins promised to a resting SELL are not sold again", skip is not None and skip[0] == "LOG", skip)
g4.order_closed("sell", 0.001)                           # that sell was cancelled without filling
g4.last_grid_index = 0
again = g4.process_tick(101.2)
check("... and are available again once that sell is released", again is not None and again[0] == "SELL" and again[2] <= 0.001 + 1e-12, again)
g5 = GridStrategyEngine("BTC-USDT", 98, 102, 5, 100)
g5.order_filled("buy", 100.0, 0.002); g5.order_placed("sell", 0.002); g5.order_filled("sell", 101.0, 0.0005)
check("a partial sell fill shrinks both the position and the reservation",
      abs(g5.current_pos - 0.0015) < 1e-12 and abs(g5.open_sell_qty - 0.0015) < 1e-12, (g5.current_pos, g5.open_sell_qty))
from strategy_engine import StrategyManager
mgr = StrategyManager()
mgr.order_placed("gone", "sell", 1); mgr.order_filled("gone", "sell", 1, 1); mgr.order_closed("gone", "sell", 1)
check("lifecycle events for a bot that was stopped are ignored, not errors", True)
v = OKXGridValidator()
ok, _ = v.validate_setup(98, 102, 5, 100, 100, round_trip_fee_rate=0.0046)
check("default +/-2%, 5 levels passes the fee check", ok)
ok, msg = v.validate_setup(99.9, 100.1, 5, 100, 100, round_trip_fee_rate=0.0046)
check("grid tighter than round-trip fees is rejected", (not ok) and "fees" in msg, msg)
dca = DCAStrategyEngine("BTC-USDT", 50, 2.0, max_buys=3)
price, buys = 100.0, 0
for _ in range(20):
    s = dca.process_tick(price)
    buys += bool(s and s[0] == "BUY")
    price *= 0.97
check("DCA stops after max_buys", buys == 3, buys)

print("okx_private request building")
sent = {}


class _Resp:
    def json(self):
        return {"code": "0", "data": []}


def _fake_post(url, headers=None, data=None, timeout=None):
    sent.update(method="POST", url=url, headers=headers, body=data)
    return _Resp()


def _fake_get(url, headers=None, timeout=None):
    sent.update(method="GET", url=url, headers=headers, body="")
    return _Resp()


okx_private.requests.post, okx_private.requests.get = _fake_post, _fake_get
OKXPrivateClient.place_order("BTC-USDT", "buy", "market", "0.001")
payload = json.loads(sent["body"])
check("market order asks for BASE-currency size", payload.get("tgtCcy") == "base_ccy", payload)
OKXPrivateClient.place_order("BTC-USDT", "buy", "limit", "0.001", px="86000.1")
payload = json.loads(sent["body"])
check("limit order has price and no tgtCcy", payload.get("px") == "86000.1" and "tgtCcy" not in payload, payload)
OKXPrivateClient.place_order("BTC-USDT", "buy", "limit", "0.001", px="86000.1", cl_ord_id="oxxabc123")
check("the client order id is sent as clOrdId", json.loads(sent["body"]).get("clOrdId") == "oxxabc123", sent["body"])
OKXPrivateClient.place_order("BTC-USDT", "buy", "limit", "0.001", px="86000.1")
check("... and omitted when not given", "clOrdId" not in json.loads(sent["body"]))
OKXPrivateClient.get_order("BTC-USDT", ord_id="555")
check("get_order asks for that order by ordId (GET with query)", sent["method"] == "GET" and sent["url"].endswith("/api/v5/trade/order?instId=BTC-USDT&ordId=555"), sent["url"])
OKXPrivateClient.get_order("BTC-USDT", cl_ord_id="oxxabc123")
check("... or by client id when the ordId is unknown", sent["url"].endswith("instId=BTC-USDT&clOrdId=oxxabc123"), sent["url"])
check("get_order with no id is refused locally", OKXPrivateClient.get_order("BTC-USDT").get("code") == "1")
OKXPrivateClient.cancel_order("BTC-USDT", ord_id="555")
check("cancel_order POSTs the instrument and ordId", sent["method"] == "POST" and sent["url"].endswith("/api/v5/trade/cancel-order") and json.loads(sent["body"]) == {"instId": "BTC-USDT", "ordId": "555"}, sent)
_cancel_expect = base64.b64encode(hmac.new(b"SECRET", (sent["headers"]["OK-ACCESS-TIMESTAMP"] + "POST" + "/api/v5/trade/cancel-order" + sent["body"]).encode(), hashlib.sha256).digest()).decode()
check("... signed over its exact body", sent["headers"]["OK-ACCESS-SIGN"] == _cancel_expect)
OKXPrivateClient.cancel_order("BTC-USDT", cl_ord_id="oxxabc123")
check("cancel by client id sends clOrdId", json.loads(sent["body"]) == {"instId": "BTC-USDT", "clOrdId": "oxxabc123"}, sent["body"])
OKXPrivateClient.place_order("BTC-USDT", "buy", "limit", "0.001", px="86000.1")   # restore: signature tests below read `sent`
ts = sent["headers"]["OK-ACCESS-TIMESTAMP"]
expected = base64.b64encode(hmac.new(b"SECRET", (ts + "POST" + "/api/v5/trade/order" + sent["body"]).encode(), hashlib.sha256).digest()).decode()
check("POST signature matches an independent HMAC of the exact body sent", sent["headers"]["OK-ACCESS-SIGN"] == expected)
check("timestamp has real milliseconds + Z", len(ts) == 24 and ts.endswith("Z") and ts[19] == ".", ts)
OKXPrivateClient.get_fill_history(limit=5)
ts = sent["headers"]["OK-ACCESS-TIMESTAMP"]
path = "/api/v5/trade/fills?instType=SPOT&limit=5"
expected = base64.b64encode(hmac.new(b"SECRET", (ts + "GET" + path).encode(), hashlib.sha256).digest()).decode()
check("GET signature covers the query string", sent["headers"]["OK-ACCESS-SIGN"] == expected and sent["url"].endswith(path))


def _boom(*a, **k):
    raise ConnectionError("network down")


okx_private.requests.get = _boom
res = OKXPrivateClient.get_account_balance()
check("network failure returns an error dict instead of raising", res.get("code") == "500", res)
_StubVault.creds = {"api_key": "KEY", "secret_key": None, "passphrase": "PASS"}
OKXPrivateClient.clear_credentials_cache()
res = OKXPrivateClient.get_account_balance()
check("missing secret returns an error dict instead of raising", res.get("code") == "1", res)

print("credential cache (the vault takes ~7 s per decrypt on your phone)")
import threading, time as _time
loads = []
class _CountingVault:
    creds = {"api_key": "KEY", "secret_key": "SECRET", "passphrase": "PASS"}
    @classmethod
    def load_credentials(cls):
        loads.append(threading.get_ident()); _time.sleep(0.05)   # stand-in for the slow decrypt
        return cls.creds
okx_private.EncryptedVault = _CountingVault
okx_private.requests.get = _fake_get
OKXPrivateClient.clear_credentials_cache()
for _ in range(10): OKXPrivateClient.get_account_balance()
check("10 sequential requests decrypt the vault once", len(loads) == 1, len(loads))
OKXPrivateClient.clear_credentials_cache(); loads.clear()
ths = [threading.Thread(target=OKXPrivateClient.get_account_balance) for _ in range(8)]
[th.start() for th in ths]; [th.join() for th in ths]
check("8 simultaneous first requests share ONE decrypt", len(loads) == 1, len(loads))
OKXPrivateClient.get_account_balance(); n = len(loads)
OKXPrivateClient.clear_credentials_cache(); OKXPrivateClient.get_account_balance()
check("clearing the cache (new keys saved) forces a re-read", len(loads) == n + 1, (n, len(loads)))
_CountingVault.creds = {}                       # nothing saved yet
OKXPrivateClient.clear_credentials_cache(); loads.clear()
OKXPrivateClient.get_account_balance(); OKXPrivateClient.get_account_balance()
check("incomplete credentials are never cached", len(loads) == 2, len(loads))
_CountingVault.creds = {"api_key": "KEY", "secret_key": "SECRET", "passphrase": "PASS"}
res = OKXPrivateClient.get_account_balance()
check("keys saved later are picked up without a restart", res.get("code") == "0", res)

print(f"\n{PASSED} passed, {len(FAILED)} failed")
if FAILED:
    print("FAILED:", *FAILED, sep="\n  - ")
    sys.exit(1)
