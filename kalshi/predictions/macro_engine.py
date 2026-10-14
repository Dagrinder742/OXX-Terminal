#!/usr/bin/env python3
"""
macro_engine.py v2 - macro-context + market-data logger for Kalshi 15-minute BTC markets.

Layers (from the blueprint):
  1. Macro feed      : 1h / 4h / 24h candles -> EMA 20/50/200 + ATR -> bias in [-1, +1]
  2. Rolling log DB  : 1-second ticks, 15-minute outcomes, Kalshi market snapshots
  3. Execution engine: adjusts a base up-probability using the macro bias

What v2 adds to the log (all in new tables, your existing database keeps working):
  venue_ticks    Kraken + Bitstamp prices each second (BRTI blends several exchanges,
                 so the average of venues should track it better than Coinbase alone)
  kalshi_windows Kalshi's own strike (floor_strike), result, and expiration_value (the
                 real settlement average) -> ground truth to grade our proxy prices
  snapshots      Kalshi bid/ask/last at 14:00, 10:00, 5:00 and 2:00 left, plus our
                 price at that moment -> lets us test against the MARKET, not just 50/50
  macro_log      per-window bias, per-timeframe scores, ATR, sigma, distance from EMA20

Commands:
  selftest        offline checks, no network
  kalshi-test     checks the Kalshi endpoint parsing against the live API  (RUN THIS FIRST)
  macro           print the current macro regime
  collect         log everything into kalshi_history.db (Ctrl+C to stop, safe to relaunch)
  eval            --strike X --secs-left N [--base-p P]
  report          signal check, proxy accuracy, and market comparison

Standard library only. Prices from Coinbase/Kraken/Bitstamp are PROXIES for BRTI.
"""

import argparse
import calendar
import contextlib
import io
import json
import logging
import math
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DB_PATH = "kalshi_history.db"
CB_API = "https://api.exchange.coinbase.com"
PRODUCT = "BTC-USD"
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_SERIES = "KXBTC15M"

WINDOW_SECS = 900
SETTLE_AVG_SECS = 60
MIN_SETTLE_TICKS = 45
SNAP_SECS_LEFT = (840, 600, 300, 120)    # when to snapshot the Kalshi market
SNAP_TOLERANCE = 10                      # skip a snapshot if we are >10s past its target
MACRO_REFRESH_AT = 450                   # seconds into a window; mid-window so it never delays the open
RESULT_POLL_EVERY = 15
RESULT_GIVE_UP = 1800                    # stop polling for a result 30 min after close
TF_WEIGHTS = {"1h": 0.5, "4h": 0.3, "24h": 0.2}   # untuned guess
MAX_SHIFT = 0.03                                  # untuned guess
TICK_KEEP_DAYS = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("macro_engine")


# --------------------------------------------------------------------------
# Pure logic (no network, no DB)
# --------------------------------------------------------------------------
def ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def atr(candles, period=14):
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
    size = 3600 * hours
    buckets = {}
    for c in candles:
        buckets.setdefault(c["ts"] // size, []).append(c)
    out = []
    for key in sorted(buckets):
        grp = sorted(buckets[key], key=lambda c: c["ts"])
        if len(grp) < hours:
            continue
        out.append({"ts": key * size, "open": grp[0]["open"],
                    "high": max(c["high"] for c in grp),
                    "low": min(c["low"] for c in grp),
                    "close": grp[-1]["close"]})
    return out


def timeframe_summary(candles):
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
            "score": (sum(votes) / len(votes)) if votes else 0.0, "n": len(closes)}


def combine_bias(summaries, weights=TF_WEIGHTS):
    num = den = 0.0
    for tf, w in weights.items():
        s = summaries.get(tf)
        if s:
            num += w * s["score"]
            den += w
    return num / den if den else 0.0


def adjust_probability(base_p, bias, max_shift=MAX_SHIFT):
    return min(0.98, max(0.02, base_p + bias * max_shift))


def normal_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def baseline_p_up(price, strike, secs_left, sigma_15m):
    """PLACEHOLDER base probability (normal model on distance-to-strike). Replace with market_reverser logic."""
    if secs_left <= 0 or sigma_15m <= 0:
        return 1.0 if price > strike else 0.0
    return normal_cdf((price - strike) / (sigma_15m * math.sqrt(secs_left / WINDOW_SECS)))


def brier(pairs):
    """Mean squared error of probabilities vs 0/1 outcomes. Lower is better; always-50% scores 0.25."""
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def money(m, base):
    """Dollar price from a Kalshi market dict: '<base>_dollars' string, else legacy cents '<base>'."""
    v = to_float(m.get(base + "_dollars"))
    if v is not None:
        return v
    c = to_float(m.get(base))
    return c / 100 if c is not None else None


def parse_iso_utc(s):
    try:
        return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def market_mid(yes_bid, yes_ask, last):
    """Market-implied P(up): bid/ask midpoint if there is a real two-sided quote, else last trade."""
    if yes_bid is not None and yes_ask is not None and yes_ask > 0:
        return (yes_bid + yes_ask) / 2
    return last


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
def http_get_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "macro_engine/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_coinbase():
    return float(http_get_json(f"{CB_API}/products/{PRODUCT}/ticker", 3)["price"])


def fetch_kraken():
    res = http_get_json("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", 3)["result"]
    return float(next(iter(res.values()))["c"][0])


def fetch_bitstamp():
    return float(http_get_json("https://www.bitstamp.net/api/v2/ticker/btcusd/", 3)["last"])


VENUES = {"coinbase": fetch_coinbase, "kraken": fetch_kraken, "bitstamp": fetch_bitstamp}


def fetch_price():
    return fetch_coinbase()


def fetch_all_prices(pool, warn_at):
    """Fetch every venue in parallel. A failing venue returns None; warnings are rate-limited to 1/min each."""
    futs = {name: pool.submit(fn) for name, fn in VENUES.items()}
    out = {}
    for name, fut in futs.items():
        try:
            out[name] = fut.result(timeout=4)
        except Exception as e:
            out[name] = None
            if time.time() - warn_at.get(name, 0) > 60:
                warn_at[name] = time.time()
                logging.warning(f"{name} price failed: {e}")
    return out


def fetch_candles(granularity, count):
    out, end = {}, int(time.time())
    while len(out) < count:
        start = end - 300 * granularity
        rows = http_get_json(f"{CB_API}/products/{PRODUCT}/candles?granularity={granularity}"
                             f"&start={start}&end={end}")
        if not rows:
            break
        for ts, low, high, op, close, _vol in rows:
            out[ts] = {"ts": ts, "low": low, "high": high, "open": op, "close": close}
        end = start
        time.sleep(0.2)
    return [out[k] for k in sorted(out)][-count:]


def macro_context():
    h1 = fetch_candles(3600, 1200)
    summaries = {"1h": timeframe_summary(h1[-300:]),
                 "4h": timeframe_summary(resample(h1, 4)),
                 "24h": timeframe_summary(fetch_candles(86400, 300))}
    atr_1h = summaries["1h"]["atr"] if summaries["1h"] else None
    return {"tf": summaries, "bias": combine_bias(summaries),
            "sigma_15m": atr_1h * 0.5 if atr_1h else None}   # rough: ATR is not a std dev


def macro_context_retry(tries=3):
    for i in range(tries):
        try:
            return macro_context()
        except Exception as e:
            logging.warning(f"macro fetch failed ({i + 1}/{tries}): {e}")
            time.sleep(5)
    raise RuntimeError("could not load macro data - check your connection")


def kalshi_market_for_window(window_start):
    """Find the Kalshi 15-min market whose close_time is this window's end. None if not found."""
    end = window_start + WINDOW_SECS
    urls = (f"{KALSHI_API}/markets?series_ticker={KALSHI_SERIES}&status=open&limit=20",
            f"{KALSHI_API}/markets?series_ticker={KALSHI_SERIES}&min_close_ts={end - 1}&max_close_ts={end + 1}&limit=20")
    for url in urls:
        for m in http_get_json(url, 5).get("markets", []):
            if parse_iso_utc(m.get("close_time")) == end:
                return m
    return None


def kalshi_get_market(ticker):
    return http_get_json(f"{KALSHI_API}/markets/{ticker}", 5).get("market", {})


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
def init_db(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ticks (ts INTEGER PRIMARY KEY, price REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS windows (
            window_start INTEGER PRIMARY KEY, strike REAL, settle REAL, delta REAL,
            outcome INTEGER, n_settle_ticks INTEGER, macro_bias REAL);
        CREATE TABLE IF NOT EXISTS venue_ticks (ts INTEGER PRIMARY KEY, kraken REAL, bitstamp REAL);
        CREATE TABLE IF NOT EXISTS macro_log (
            window_start INTEGER PRIMARY KEY, bias REAL, score_1h REAL, score_4h REAL,
            score_24h REAL, atr_1h REAL, sigma_15m REAL, close_vs_ema20_1h_pct REAL);
        CREATE TABLE IF NOT EXISTS kalshi_windows (
            window_start INTEGER PRIMARY KEY, ticker TEXT, floor_strike REAL,
            result TEXT, expiration_value REAL, resolved_at INTEGER);
        CREATE TABLE IF NOT EXISTS snapshots (
            window_start INTEGER, secs_left INTEGER, snap_ts INTEGER, price REAL,
            yes_bid REAL, yes_ask REAL, no_bid REAL, no_ask REAL, last_price REAL,
            ticker TEXT, raw TEXT, PRIMARY KEY (window_start, secs_left));
    """)
    return conn


def log_tick(conn, ts, price):
    conn.execute("INSERT OR REPLACE INTO ticks VALUES (?, ?)", (ts, price))


def log_venues(conn, ts, prices):
    if prices.get("kraken") is not None or prices.get("bitstamp") is not None:
        conn.execute("INSERT OR REPLACE INTO venue_ticks VALUES (?,?,?)",
                     (ts, prices.get("kraken"), prices.get("bitstamp")))


def log_macro(conn, ws, ctx):
    tf = ctx["tf"]
    score = lambda k: tf[k]["score"] if tf.get(k) else None
    s1 = tf.get("1h")
    vs = (s1["close"] / s1["ema20"] - 1) * 100 if s1 and s1.get("ema20") else None
    conn.execute("INSERT OR REPLACE INTO macro_log VALUES (?,?,?,?,?,?,?,?)",
                 (ws, ctx["bias"], score("1h"), score("4h"), score("24h"),
                  s1["atr"] if s1 else None, ctx["sigma_15m"], vs))


def save_snapshot(conn, ws, secs_left, price, m):
    conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (ws, secs_left, int(time.time()), price, money(m, "yes_bid"), money(m, "yes_ask"),
                  money(m, "no_bid"), money(m, "no_ask"), money(m, "last_price"),
                  m.get("ticker"), json.dumps(m)))
    conn.execute("""INSERT INTO kalshi_windows (window_start, ticker, floor_strike) VALUES (?,?,?)
                    ON CONFLICT(window_start) DO UPDATE SET ticker = excluded.ticker,
                    floor_strike = COALESCE(excluded.floor_strike, floor_strike)""",
                 (ws, m.get("ticker"), to_float(m.get("floor_strike"))))


def save_result(conn, ws, m):
    """Store Kalshi's final result if present. Returns True once the market has resolved."""
    result = str(m.get("result") or "").lower()
    if result not in ("yes", "no"):
        return False
    conn.execute("""UPDATE kalshi_windows SET result = ?, expiration_value = ?, resolved_at = ?,
                    floor_strike = COALESCE(?, floor_strike) WHERE window_start = ?""",
                 (result, to_float(m.get("expiration_value")), int(time.time()),
                  to_float(m.get("floor_strike")), ws))
    conn.commit()
    return True


def finalize_window(conn, window_start, macro_bias):
    end = window_start + WINDOW_SECS
    first = conn.execute("SELECT ts, price FROM ticks WHERE ts >= ? AND ts < ? ORDER BY ts LIMIT 1",
                         (window_start, end)).fetchone()
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


def multi_strike_settle(conn, window_start):
    """Same as finalize_window but on the average of all available venues (needs >= 2 per tick)."""
    end = window_start + WINDOW_SECS
    rows = conn.execute("""SELECT t.ts, t.price, v.kraken, v.bitstamp FROM ticks t
                           LEFT JOIN venue_ticks v ON v.ts = t.ts
                           WHERE t.ts >= ? AND t.ts < ? AND (t.ts <= ? OR t.ts >= ?) ORDER BY t.ts""",
                        (window_start, end, window_start + 5, end - SETTLE_AVG_SECS)).fetchall()
    pts = []
    for ts, cb, kr, bs in rows:
        vals = [x for x in (cb, kr, bs) if x is not None]
        if len(vals) >= 2:
            pts.append((ts, sum(vals) / len(vals)))
    opens = [p for ts, p in pts if ts <= window_start + 5]
    closes = [p for ts, p in pts if ts >= end - SETTLE_AVG_SECS]
    if not opens or len(closes) < MIN_SETTLE_TICKS:
        return None
    return opens[0], sum(closes) / len(closes)


def prune_ticks(conn, keep_days=TICK_KEEP_DAYS):
    cutoff = int(time.time()) - keep_days * 86400
    conn.execute("DELETE FROM ticks WHERE ts < ?", (cutoff,))
    conn.execute("DELETE FROM venue_ticks WHERE ts < ?", (cutoff,))
    conn.commit()


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_macro(_args):
    ctx = macro_context()
    fmt = lambda v: f"{v:,.0f}" if v is not None else "n/a"
    for tf, s in ctx["tf"].items():
        if not s:
            print(f"{tf}: no data")
            continue
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
    print(f"price {price:,.2f}  strike {args.strike:,.2f}  secs left {args.secs_left}")
    print(f"macro bias {ctx['bias']:+.2f}  base P(up) {base:.3f}  "
          f"adjusted P(up) {adjust_probability(base, ctx['bias']):.3f}")


def cmd_kalshi_test(_args):
    """Check that the Kalshi endpoint and our parsing really work. Prints what it finds, fails loudly."""
    now = int(time.time())
    ws = now - now % WINDOW_SECS
    m = kalshi_market_for_window(ws)
    if m is None:
        print(f"FAIL: no open market found closing at {ws + WINDOW_SECS} (series {KALSHI_SERIES}).")
        print("Raw check: open", f"{KALSHI_API}/markets?series_ticker={KALSHI_SERIES}&status=open&limit=3", "in a browser.")
        return
    print("current market:", m.get("ticker"), "| status:", m.get("status"))
    print("  floor_strike :", m.get("floor_strike"), " (parsed:", to_float(m.get("floor_strike")), ")")
    for f in ("yes_bid", "yes_ask", "no_bid", "no_ask", "last_price"):
        print(f"  {f:<10}: raw={m.get(f + '_dollars', m.get(f))!r}  parsed={money(m, f)}")
    print("  market mid  :", market_mid(money(m, "yes_bid"), money(m, "yes_ask"), money(m, "last_price")))
    done = http_get_json(f"{KALSHI_API}/markets?series_ticker={KALSHI_SERIES}&status=settled&limit=1", 5).get("markets", [])
    if done:
        d = done[0]
        print("latest settled:", d.get("ticker"), "| result:", repr(d.get("result")),
              "| expiration_value:", repr(d.get("expiration_value")), "->", to_float(d.get("expiration_value")))
    else:
        print("WARN: no settled market returned - result parsing not verified")
    print("If every line above shows real numbers, collect will log snapshots and results correctly.")


def take_snapshot(conn, ws, left, price):
    """Snapshot the Kalshi market. Returns the ticker (or None). Never raises."""
    try:
        m = kalshi_market_for_window(ws)
        if m is None:
            logging.warning(f"no Kalshi market found for window {ws} at {left}s left")
            return None
        save_snapshot(conn, ws, left, price, m)
        return m.get("ticker")
    except Exception as e:
        logging.warning(f"kalshi snapshot failed ({left}s left): {e}")
        return None


def poll_results(conn, pending, now):
    for ws in list(pending):
        if now < ws + WINDOW_SECS + 20:
            continue
        try:
            if save_result(conn, ws, kalshi_get_market(pending[ws])):
                r = conn.execute("SELECT result, expiration_value, floor_strike FROM kalshi_windows "
                                 "WHERE window_start = ?", (ws,)).fetchone()
                log.info("kalshi result %s: %s (strike %s, settle %s)",
                         time.strftime("%H:%M", time.localtime(ws)), r[0], r[2], r[1])
                del pending[ws]
                continue
        except Exception as e:
            logging.warning(f"result poll failed for window {ws}: {e}")
        if now > ws + WINDOW_SECS + RESULT_GIVE_UP:
            logging.warning(f"gave up waiting for Kalshi result for window {ws}")
            del pending[ws]


def cmd_collect(_args):
    conn = init_db()
    ctx, ctx_at = macro_context_retry(), time.time()
    cur_ws, cur_bias, done_snaps = None, ctx["bias"], set()
    last_price, warn_at, next_poll = None, {}, 0
    pending = {ws: tk for ws, tk in conn.execute(
        "SELECT window_start, ticker FROM kalshi_windows WHERE result IS NULL AND ticker IS NOT NULL "
        "AND window_start > ?", (int(time.time()) - 3 * 3600,))}
    pool = ThreadPoolExecutor(max_workers=3)
    log.info("collecting (Ctrl+C to stop). bias %+.2f, %d results pending", cur_bias, len(pending))
    try:
        while True:
            now = int(time.time())
            prices = fetch_all_prices(pool, warn_at)
            if prices["coinbase"] is not None:
                last_price = prices["coinbase"]
                log_tick(conn, now, last_price)
                log_venues(conn, now, prices)
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
                cur_ws, cur_bias, done_snaps = ws, ctx["bias"], set()
                log_macro(conn, ws, ctx)
            elapsed = now - ws
            if elapsed >= MACRO_REFRESH_AT and time.time() - ctx_at > 300:
                try:
                    ctx, ctx_at = macro_context(), time.time()
                except Exception as e:
                    logging.warning(f"macro refresh failed, keeping old bias: {e}")
                    ctx_at = time.time() - 240          # retry in about a minute
            for left in SNAP_SECS_LEFT:
                target = WINDOW_SECS - left
                if left in done_snaps or elapsed < target:
                    continue
                done_snaps.add(left)
                if elapsed - target <= SNAP_TOLERANCE and last_price is not None:
                    ticker = take_snapshot(conn, ws, left, last_price)
                    if ticker:
                        pending[ws] = ticker
            if pending and now >= next_poll:
                next_poll = now + RESULT_POLL_EVERY
                poll_results(conn, pending, now)
            conn.commit()
            time.sleep(max(0.0, 1 - (time.time() - now)))
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        pool.shutdown(wait=False)
        conn.commit()


def report(conn):
    rows = conn.execute("SELECT outcome, macro_bias FROM windows").fetchall()
    n = len(rows)
    print(f"== 1. Does the macro bias predict outcomes? ({n} windows, proxy prices)")
    if n:
        print(f"overall up-rate {sum(r[0] for r in rows) / n:.1%}")
        for name, pick in (("bullish", lambda b: b > 0), ("bearish", lambda b: b < 0), ("neutral", lambda b: b == 0)):
            grp = [r[0] for r in rows if r[1] is not None and pick(r[1])]
            if grp:
                p = sum(grp) / len(grp)
                band = 1.96 * math.sqrt(p * (1 - p) / len(grp))
                print(f"  {name:<8} n={len(grp):<4} up-rate {p:.1%} (+/-{band:.1%})")
        print("  Only trust a difference if the bands do not overlap AND it holds across different market regimes.")

    kw = conn.execute("""SELECT k.window_start, k.floor_strike, k.result, k.expiration_value, w.strike, w.settle
                         FROM kalshi_windows k JOIN windows w ON w.window_start = k.window_start
                         WHERE k.result IN ('yes','no')""").fetchall()
    print(f"\n== 2. How good are our proxy prices? ({len(kw)} windows with Kalshi's own result)")
    if kw:
        agree_cb = sum((r[4] is not None and (r[5] > r[4]) == (r[2] == "yes")) for r in kw)
        print(f"  Coinbase-only outcome matches Kalshi: {agree_cb}/{len(kw)} = {agree_cb / len(kw):.1%}")
        strike_err = [abs(r[4] - r[1]) for r in kw if r[1] is not None]
        settle_err = [abs(r[5] - r[3]) for r in kw if r[3] is not None]
        if strike_err:
            print(f"  strike error (Coinbase vs Kalshi floor_strike): mean ${sum(strike_err) / len(strike_err):.2f}, max ${max(strike_err):.2f}")
        if settle_err:
            print(f"  settle error (Coinbase vs Kalshi expiration_value): mean ${sum(settle_err) / len(settle_err):.2f}, max ${max(settle_err):.2f}")
        multi = [(r, multi_strike_settle(conn, r[0])) for r in kw]
        multi = [(r, m) for r, m in multi if m]
        if multi:
            agree = sum((m[1] > m[0]) == (r[2] == "yes") for r, m in multi)
            se = [abs(m[1] - r[3]) for r, m in multi if r[3] is not None]
            print(f"  multi-venue average matches Kalshi: {agree}/{len(multi)} = {agree / len(multi):.1%}"
                  + (f", settle error mean ${sum(se) / len(se):.2f}" if se else ""))
        flips = [r for r in kw if r[4] is not None and (r[5] > r[4]) != (r[2] == "yes")]
        print(f"  windows where proxy and Kalshi disagree: {len(flips)}  <- these are noise your model cannot see")
    else:
        print("  none yet - needs the v2 collector running (and `kalshi-test` passing)")

    q = conn.execute("""SELECT s.price, s.yes_bid, s.yes_ask, s.last_price, k.floor_strike, k.result,
                               m.sigma_15m, m.bias
                        FROM snapshots s JOIN kalshi_windows k ON k.window_start = s.window_start
                        LEFT JOIN macro_log m ON m.window_start = s.window_start
                        WHERE s.secs_left = 300 AND k.result IN ('yes','no')""").fetchall()
    print(f"\n== 3. Model vs the market at 5:00 left ({len(q)} windows)")
    mk, full = [], []
    for price, yb, ya, lp, fs, res, sig, bias in q:
        out = 1 if res == "yes" else 0
        pm = market_mid(yb, ya, lp)
        if pm is None:
            continue
        mk.append((pm, out))
        if fs is not None and sig and bias is not None and price is not None:
            base = baseline_p_up(price, fs, 300, sig)
            full.append((pm, base, adjust_probability(base, bias), out))
    if mk:
        print("  market reliability (does a 70% price win ~70% of the time?):")
        for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
            g = [(p, o) for p, o in mk if lo <= p < hi]
            if g:
                print(f"    {lo:.0%}-{min(hi, 1):.0%}: n={len(g):<4} avg price {sum(p for p, _ in g) / len(g):.2f}  actual up {sum(o for _, o in g) / len(g):.1%}")
    if full:
        print(f"  Brier score on {len(full)} windows (lower = better; 0.25 = coin flip):")
        print(f"    market      {brier([(a, d) for a, _, _, d in full]):.4f}")
        print(f"    base model  {brier([(b, d) for _, b, _, d in full]):.4f}   (placeholder normal model, NOT market_reverser)")
        print(f"    + macro     {brier([(c, d) for _, _, c, d in full]):.4f}")
        print("  The macro layer only helps if '+ macro' beats 'base model' consistently. Beating 'market' is the real bar.")
    if len(q) < 300:
        print(f"  NOTE: {len(q)} windows is too few to trust small differences. Aim for 300+.")


def cmd_report(_args):
    report(init_db())


def cmd_selftest(_args):
    assert ema([5.0] * 30, 20) == 5.0 and ema([1, 2, 3], 5) is None
    assert abs(ema([1, 2, 3, 4], 3) - 3.0) < 1e-9
    flat = [{"high": 11, "low": 9, "close": 10, "ts": i * 3600} for i in range(30)]
    assert abs(atr(flat) - 2.0) < 1e-9
    hourly = [{"ts": i * 3600, "open": i, "high": i + 1, "low": i - 1, "close": i + 0.5} for i in range(9)]
    r4 = resample(hourly, 4)
    assert len(r4) == 2 and r4[0]["open"] == 0 and r4[0]["high"] == 4 and r4[1]["close"] == 7.5
    up = [{"ts": i, "open": i, "high": i + 1, "low": i - 1, "close": 100 + i} for i in range(250)]
    dn = [{"ts": i, "open": i, "high": i + 1, "low": i - 1, "close": 400 - i} for i in range(250)]
    assert timeframe_summary(up)["score"] == 1.0 and timeframe_summary(dn)["score"] == -1.0
    assert combine_bias({"1h": {"score": 1.0}, "4h": None, "24h": None}) == 1.0
    assert abs(combine_bias({"1h": {"score": 1.0}, "4h": {"score": -1.0}, "24h": {"score": 0.0}}) - 0.2) < 1e-9
    assert abs(adjust_probability(0.5, 1.0) - 0.53) < 1e-9 and adjust_probability(0.99, 1.0) == 0.98
    assert abs(baseline_p_up(100, 100, 450, 50) - 0.5) < 1e-9 and baseline_p_up(110, 100, 450, 50) > 0.5
    assert abs(brier([(0.5, 1), (0.5, 0)]) - 0.25) < 1e-9 and brier([(1.0, 1), (0.0, 0)]) == 0.0

    # Kalshi parsing (shape taken from a real market response)
    m = {"yes_bid_dollars": "0.2100", "yes_ask_dollars": "0.2200", "last_price_dollars": "0.2200",
         "no_bid_dollars": "0.7800", "floor_strike": 83307.11, "close_time": "2026-10-13T17:15:00Z",
         "result": "yes", "expiration_value": "83310.55"}
    assert money(m, "yes_bid") == 0.21 and money(m, "no_ask") is None
    assert money({"yes_bid": 21}, "yes_bid") == 0.21                      # legacy cents
    assert abs(market_mid(0.21, 0.22, 0.5) - 0.215) < 1e-9
    assert market_mid(0.0, 0.0, 0.4) == 0.4 and market_mid(None, None, 0.4) == 0.4
    assert parse_iso_utc(m["close_time"]) == 1791911700 and parse_iso_utc("TBD") is None
    assert to_float("TBD") is None and to_float(None) is None

    conn = init_db(":memory:")
    ws = 900 * 1000
    for s in range(WINDOW_SECS):
        log_tick(conn, ws + s, 1000 + s * 100 / 899)
        conn.execute("INSERT INTO venue_ticks VALUES (?,?,?)", (ws + s, 1010 + s * 100 / 899, None))
    row = finalize_window(conn, ws, 0.4)
    assert row and row[1] == 1000 and row[4] == 1
    assert abs(row[2] - sum(1000 + s * 100 / 899 for s in range(840, 900)) / 60) < 1e-6
    ms = multi_strike_settle(conn, ws)                                     # coinbase + kraken, +5 on average
    assert ms and abs(ms[0] - 1005) < 1e-6 and ms[1] > row[2]
    ws2 = ws + WINDOW_SECS
    for s in range(300, WINDOW_SECS):
        log_tick(conn, ws2 + s, 1000)
    assert finalize_window(conn, ws2, 0.0) is None                         # started mid-window
    ws3 = ws2 + WINDOW_SECS
    for s in range(700):
        log_tick(conn, ws3 + s, 1000)
    assert finalize_window(conn, ws3, 0.0) is None                         # sparse settlement ticks

    # Kalshi tables: snapshot -> result round trip
    save_snapshot(conn, ws, 300, 1050.0, {**m, "ticker": "KXBTC15M-TEST-15", "result": ""})
    assert conn.execute("SELECT floor_strike, result FROM kalshi_windows").fetchone() == (83307.11, None)
    assert save_result(conn, ws, {"result": ""}) is False                  # unresolved stays pending
    assert save_result(conn, ws, m) is True
    assert conn.execute("SELECT result, expiration_value FROM kalshi_windows").fetchone() == ("yes", 83310.55)

    # full report on synthetic data must run end to end
    for i in range(1, 40):
        w = ws + 10000 + i * WINDOW_SECS
        win = i % 2
        conn.execute("INSERT INTO windows VALUES (?,?,?,?,?,?,?)", (w, 1000, 1010 if win else 990, 10 if win else -10, win, 60, 0.3))
        conn.execute("INSERT INTO macro_log VALUES (?,?,?,?,?,?,?,?)", (w, 0.3, .3, .3, .3, 100, 50, 0.1))
        conn.execute("INSERT INTO kalshi_windows VALUES (?,?,?,?,?,?)", (w, "T%d" % i, 1000, "yes" if win else "no", 1010 if win else 990, 0))
        conn.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)", (w, 300, 0, 1005 if win else 995, .5, .52, .48, .5, .5, "T", "{}"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(conn)
    out = buf.getvalue()
    assert "Brier" in out and "matches Kalshi" in out and "reliability" in out, out
    print("selftest: all checks passed (offline logic only)")
    print("NOT verified offline: live Coinbase/Kraken/Bitstamp feeds and the Kalshi API -> run `kalshi-test`")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("selftest", cmd_selftest), ("kalshi-test", cmd_kalshi_test), ("macro", cmd_macro),
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
