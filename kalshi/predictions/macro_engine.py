#!/usr/bin/env python3
"""
macro_engine.py - macro-context layer for Kalshi 15-minute BTC markets.

Follows the blueprint:
  1. Macro feed      : 1h / 4h / 24h candles -> EMA 20/50/200 + ATR  -> bias in [-1, +1]
  2. Rolling log DB  : 1-second price ticks + 15-minute window outcomes (SQLite)
  3. Execution engine: adjusts a base up-probability using the macro bias

Standard library only (works on Termux / Windows).

Commands:
  python macro_engine.py selftest            offline checks, no network
  python macro_engine.py macro               print current macro regime
  python macro_engine.py collect             log 1s ticks + settle windows into the DB
  python macro_engine.py eval --strike 67000 --secs-left 300 [--base-p 0.55]
  python macro_engine.py report              does the macro bias predict outcomes?

IMPORTANT - price source: this uses Coinbase public data as a PROXY for the
CF Benchmarks BRTI index Kalshi settles on. Proxy and BRTI can differ by tens
of dollars, which matters when you are measuring $400 swings against a strike.
Swap fetch_price() for a real BRTI source if you have one.
"""

import argparse
import json
import logging
import math
import sqlite3
import sys
import time
import urllib.request

DB_PATH = "kalshi_history.db"
API = "https://api.exchange.coinbase.com"
PRODUCT = "BTC-USD"

WINDOW_SECS = 900        # 15-minute market
SETTLE_AVG_SECS = 60     # settlement = average of the last 60 seconds
MIN_SETTLE_TICKS = 45    # skip a window if the last-60s average is too sparse
TF_WEIGHTS = {"1h": 0.5, "4h": 0.3, "24h": 0.2}   # untuned starting guess
MAX_SHIFT = 0.03         # max probability shift from macro bias (untuned guess)
TICK_KEEP_DAYS = 14      # prune raw ticks older than this

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("macro_engine")


# --------------------------------------------------------------------------
# Pure logic (no network, no DB) - this is what selftest exercises
# --------------------------------------------------------------------------
def ema(values, period):
    """Exponential moving average, seeded with the SMA of the first `period` values."""
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def atr(candles, period=14):
    """Wilder's Average True Range. candles: dicts with high/low/close, oldest first."""
    if len(candles) < period + 1:
        return None
    trs = []
    for prev, cur in zip(candles, candles[1:]):
        trs.append(max(cur["high"] - cur["low"],
                       abs(cur["high"] - prev["close"]),
                       abs(cur["low"] - prev["close"])))
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def resample(candles, hours):
    """Aggregate 1h candles into `hours`-hour candles aligned to the epoch. Drops incomplete buckets."""
    size = 3600 * hours
    buckets = {}
    for c in candles:
        buckets.setdefault(c["ts"] // size, []).append(c)
    out = []
    for key in sorted(buckets):
        grp = sorted(buckets[key], key=lambda c: c["ts"])
        if len(grp) < hours:
            continue
        out.append({"ts": key * size,
                    "open": grp[0]["open"],
                    "high": max(c["high"] for c in grp),
                    "low": min(c["low"] for c in grp),
                    "close": grp[-1]["close"]})
    return out


def timeframe_summary(candles):
    """EMA/ATR snapshot + trend score in [-1, +1] for one timeframe."""
    closes = [c["close"] for c in candles]
    if not closes:
        return None
    e20, e50, e200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    a = atr(candles)
    close = closes[-1]
    votes = []
    if e20 is not None:
        votes.append(1 if close > e20 else -1)
    if e20 is not None and e50 is not None:
        votes.append(1 if e20 > e50 else -1)
    if e50 is not None and e200 is not None:
        votes.append(1 if e50 > e200 else -1)
    return {"close": close, "ema20": e20, "ema50": e50, "ema200": e200,
            "atr": a, "atr_pct": (a / close * 100) if a else None,
            "score": (sum(votes) / len(votes)) if votes else 0.0,
            "n": len(closes)}


def combine_bias(summaries, weights=TF_WEIGHTS):
    """Weighted average of timeframe scores, re-normalised over timeframes that exist."""
    num = den = 0.0
    for tf, w in weights.items():
        s = summaries.get(tf)
        if s:
            num += w * s["score"]
            den += w
    return num / den if den else 0.0


def adjust_probability(base_p, bias, max_shift=MAX_SHIFT):
    """Shift the base up-probability by bias * max_shift, clamped to [0.02, 0.98]."""
    return min(0.98, max(0.02, base_p + bias * max_shift))


def normal_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def baseline_p_up(price, strike, secs_left, sigma_15m):
    """PLACEHOLDER base probability: normal model on distance-to-strike.
    Replace with your own market_reverser logic; it is only here so `eval` runs standalone."""
    if secs_left <= 0 or sigma_15m <= 0:
        return 1.0 if price > strike else 0.0
    sigma = sigma_15m * math.sqrt(secs_left / WINDOW_SECS)
    return normal_cdf((price - strike) / sigma)


# --------------------------------------------------------------------------
# Network (Coinbase public API)
# --------------------------------------------------------------------------
def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "macro_engine/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def fetch_price():
    return float(http_get_json(f"{API}/products/{PRODUCT}/ticker")["price"])


def fetch_candles(granularity, count):
    """Fetch `count` candles (oldest first), paging 300 at a time."""
    out, end = {}, int(time.time())
    while len(out) < count:
        start = end - 300 * granularity
        url = (f"{API}/products/{PRODUCT}/candles?granularity={granularity}"
               f"&start={start}&end={end}")
        rows = http_get_json(url)
        if not rows:
            break
        for ts, low, high, op, close, _vol in rows:
            out[ts] = {"ts": ts, "low": low, "high": high, "open": op, "close": close}
        end = start
        time.sleep(0.2)   # stay well under the public rate limit
    return [out[k] for k in sorted(out)][-count:]


def macro_context():
    """Pull 1h/4h/24h data and build the regime summary + bias."""
    h1 = fetch_candles(3600, 1200)          # 1200h -> 300 four-hour candles
    summaries = {
        "1h": timeframe_summary(h1[-300:]),
        "4h": timeframe_summary(resample(h1, 4)),
        "24h": timeframe_summary(fetch_candles(86400, 300)),
    }
    atr_1h = summaries["1h"]["atr"] if summaries["1h"] else None
    return {"tf": summaries,
            "bias": combine_bias(summaries),
            # ATR is not a standard deviation; 0.5 = sqrt(15min/60min). Rough scale only.
            "sigma_15m": atr_1h * 0.5 if atr_1h else None}


# --------------------------------------------------------------------------
# Rolling log database
# --------------------------------------------------------------------------
def init_db(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ticks (ts INTEGER PRIMARY KEY, price REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS windows (
            window_start INTEGER PRIMARY KEY,
            strike REAL, settle REAL, delta REAL, outcome INTEGER,
            n_settle_ticks INTEGER, macro_bias REAL);
    """)
    return conn


def log_tick(conn, ts, price):
    conn.execute("INSERT OR REPLACE INTO ticks VALUES (?, ?)", (ts, price))


def finalize_window(conn, window_start, macro_bias):
    """Compute strike / settlement for a finished window. Returns the row, or None if data was incomplete."""
    end = window_start + WINDOW_SECS
    first = conn.execute("SELECT ts, price FROM ticks WHERE ts >= ? AND ts < ? ORDER BY ts LIMIT 1",
                         (window_start, end)).fetchone()
    # collector must have been running at the open, otherwise the strike is wrong
    if first is None or first[0] > window_start + 5:
        return None
    rows = conn.execute("SELECT price FROM ticks WHERE ts >= ? AND ts < ?",
                        (end - SETTLE_AVG_SECS, end)).fetchall()
    if len(rows) < MIN_SETTLE_TICKS:
        return None
    strike = first[1]
    settle = sum(r[0] for r in rows) / len(rows)
    row = (window_start, strike, settle, settle - strike, int(settle > strike), len(rows), macro_bias)
    conn.execute("INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?)", row)
    conn.commit()
    return row


def prune_ticks(conn, keep_days=TICK_KEEP_DAYS):
    conn.execute("DELETE FROM ticks WHERE ts < ?", (int(time.time()) - keep_days * 86400,))
    conn.commit()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_macro(_args):
    ctx = macro_context()
    for tf, s in ctx["tf"].items():
        if not s:
            print(f"{tf}: no data")
            continue
        fmt = lambda v: f"{v:,.0f}" if v is not None else "n/a"
        print(f"{tf:>3}  close {s['close']:,.0f}  EMA20 {fmt(s['ema20'])}  EMA50 {fmt(s['ema50'])}  "
              f"EMA200 {fmt(s['ema200'])}  ATR {fmt(s['atr'])} ({s['atr_pct']:.2f}%)  score {s['score']:+.2f}")
    print(f"macro bias {ctx['bias']:+.2f}   rough 15m sigma ${ctx['sigma_15m']:,.0f}")


def cmd_eval(args):
    ctx = macro_context()
    price = args.price if args.price is not None else fetch_price()
    base = args.base_p
    if base is None:
        base = baseline_p_up(price, args.strike, args.secs_left, ctx["sigma_15m"])
        print("(base probability is the placeholder normal model, not your algorithm)")
    adj = adjust_probability(base, ctx["bias"])
    print(f"price {price:,.2f}  strike {args.strike:,.2f}  secs left {args.secs_left}")
    print(f"macro bias {ctx['bias']:+.2f}  base P(up) {base:.3f}  adjusted P(up) {adj:.3f}")


def cmd_collect(_args):
    conn = init_db()
    ctx, ctx_at = macro_context(), time.time()
    cur_ws, cur_bias = None, ctx["bias"]
    log.info("collecting; Ctrl+C to stop. bias %+.2f", cur_bias)
    try:
        while True:
            now = int(time.time())
            try:
                log_tick(conn, now, fetch_price())
            except Exception as e:
                logging.warning(f"tick failed: {e}")
            ws = now - now % WINDOW_SECS
            if ws != cur_ws:
                if cur_ws is not None:
                    row = finalize_window(conn, cur_ws, cur_bias)
                    if row:
                        log.info("window %s strike %.2f settle %.2f delta %+.2f %s bias %+.2f",
                                 time.strftime("%H:%M", time.localtime(row[0])), row[1], row[2],
                                 row[3], "UP" if row[4] else "DOWN", row[6])
                    else:
                        log.info("window %s skipped (incomplete data)", cur_ws)
                    prune_ticks(conn)
                if time.time() - ctx_at > 300:    # refresh macro every 5 min
                    try:
                        ctx, ctx_at = macro_context(), time.time()
                    except Exception as e:
                        logging.warning(f"macro refresh failed, keeping old bias: {e}")
                cur_ws, cur_bias = ws, ctx["bias"]
            conn.commit()
            time.sleep(max(0.0, 1 - (time.time() - now)))
    except KeyboardInterrupt:
        log.info("stopped")


def cmd_report(_args):
    conn = init_db()
    rows = conn.execute("SELECT outcome, macro_bias FROM windows").fetchall()
    n = len(rows)
    if n == 0:
        print("no windows logged yet - run `collect` first")
        return
    print(f"{n} windows, overall up-rate {sum(r[0] for r in rows) / n:.1%}")
    for name, pick in (("bias > 0 (bullish)", lambda b: b > 0),
                       ("bias < 0 (bearish)", lambda b: b < 0),
                       ("bias = 0 (neutral)", lambda b: b == 0)):
        grp = [r[0] for r in rows if pick(r[1])]
        if grp:
            print(f"  {name:<20} n={len(grp):<4} up-rate {sum(grp) / len(grp):.1%}")
    if n < 300:
        print(f"WARNING: only {n} windows - differences this small are noise. Wait for 300+.")


def cmd_selftest(_args):
    # EMA: constant series stays constant; known small case
    assert ema([5.0] * 30, 20) == 5.0
    assert ema([1, 2, 3], 5) is None
    assert abs(ema([1, 2, 3, 4], 3) - 3.0) < 1e-9          # SMA(1,2,3)=2, k=.5 -> 4*.5+2*.5 = 3
    # ATR on flat candles with range 2 -> 2
    flat = [{"high": 11, "low": 9, "close": 10, "ts": i * 3600} for i in range(30)]
    assert abs(atr(flat) - 2.0) < 1e-9
    # resample: 8 hourly candles -> two 4h candles; partial bucket dropped
    hourly = [{"ts": i * 3600, "open": i, "high": i + 1, "low": i - 1, "close": i + 0.5} for i in range(9)]
    r4 = resample(hourly, 4)
    assert len(r4) == 2 and r4[0]["open"] == 0 and r4[0]["high"] == 4 and r4[1]["close"] == 7.5
    # trend scoring: steady uptrend -> +1, steady downtrend -> -1
    up = [{"ts": i, "open": i, "high": i + 1, "low": i - 1, "close": 100 + i} for i in range(250)]
    dn = [{"ts": i, "open": i, "high": i + 1, "low": i - 1, "close": 400 - i} for i in range(250)]
    assert timeframe_summary(up)["score"] == 1.0
    assert timeframe_summary(dn)["score"] == -1.0
    # bias combine ignores missing timeframes
    assert combine_bias({"1h": {"score": 1.0}, "4h": None, "24h": None}) == 1.0
    assert abs(combine_bias({"1h": {"score": 1.0}, "4h": {"score": -1.0}, "24h": {"score": 0.0}}) - 0.2) < 1e-9
    # probability adjustment: direction, size, clamp
    assert abs(adjust_probability(0.5, 1.0) - 0.53) < 1e-9
    assert abs(adjust_probability(0.5, -1.0) - 0.47) < 1e-9
    assert adjust_probability(0.99, 1.0) == 0.98 and adjust_probability(0.001, -1.0) == 0.02
    # baseline model: at the strike with time left = 50%; above strike > 50%
    assert abs(baseline_p_up(100, 100, 450, 50) - 0.5) < 1e-9
    assert baseline_p_up(110, 100, 450, 50) > 0.5
    # DB: simulate a full window, price ramps from 1000 to 1100 over 900s
    conn = init_db(":memory:")
    ws = 900 * 1000
    for s in range(WINDOW_SECS):
        log_tick(conn, ws + s, 1000 + s * 100 / 899)
    row = finalize_window(conn, ws, 0.4)
    assert row and row[1] == 1000 and row[4] == 1
    expected = sum(1000 + s * 100 / 899 for s in range(840, 900)) / 60   # last 60s average
    assert abs(row[2] - expected) < 1e-6, (row[2], expected)
    # window that started mid-way must be rejected (strike would be wrong)
    ws2 = ws + WINDOW_SECS
    for s in range(300, WINDOW_SECS):
        log_tick(conn, ws2 + s, 1000)
    assert finalize_window(conn, ws2, 0.0) is None
    # window with too few settlement ticks must be rejected
    ws3 = ws2 + WINDOW_SECS
    for s in range(0, 700):
        log_tick(conn, ws3 + s, 1000)
    assert finalize_window(conn, ws3, 0.0) is None
    print("selftest: all checks passed (offline logic only - live feed NOT tested)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("selftest", cmd_selftest), ("macro", cmd_macro),
                     ("collect", cmd_collect), ("report", cmd_report)):
        sub.add_parser(name).set_defaults(fn=fn)
    e = sub.add_parser("eval")
    e.add_argument("--strike", type=float, required=True)
    e.add_argument("--secs-left", type=int, required=True)
    e.add_argument("--price", type=float, help="default: fetch live")
    e.add_argument("--base-p", type=float, help="your own base P(up); default: placeholder model")
    e.set_defaults(fn=cmd_eval)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
