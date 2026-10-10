#!/usr/bin/env python3
"""backtest.py - score the engine against logged windows.

  python backtest.py windows.csv          # real data from logger.py
  python backtest.py --demo 500           # simulated random walk (sanity check)

Options: --fee 1.0 (cents per contract, verdict test only)  --split 0.7
         --snap-sec 300 (seconds left when you logged the 5:00 snapshot)
Optional CSV columns may be blank; sections without enough data say so.
"""
import argparse
import csv
import itertools
import math
import random

from engine import (analyze, fair_p_up, sigma_per_sqrt_sec,
                    Params, UP, DOWN, COIL, CHOP)

GAP = 0.05  # model must differ from the market by 5+ points to count as a "bet"


# ---------- helpers ----------
def wilson(k, n, z=1.96):
    """95% confidence interval for a hit rate."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def fnum(r, key):
    v = (r.get(key) or "").strip()
    return float(v) if v else None


def load(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            tgt = fnum(r, "target")
            if tgt is None:
                tgt = fnum(r, "strike")  # older column name
            rows.append(dict(
                strike=tgt, p0=float(r["p0"]), p3=float(r["p3"]), p6=float(r["p6"]),
                final=fnum(r, "final"), market_yes=fnum(r, "market_yes_cents"),
                p10=fnum(r, "p10"), up10=fnum(r, "up_pct10"),
                up_mult=fnum(r, "up_mult10"), down_mult=fnum(r, "down_mult10"),
                max_dev=fnum(r, "max_dev"), result=r["result"].strip().lower()))
    return rows


def make_demo(n, seed=1, true_vol=0.35):
    """Driftless random walk priced by a market that uses the SAME model plus a
    4.5% built-in cost. No strategy can beat it, so a clear edge here is a bug."""
    rnd = random.Random(seed)
    true = Params(annual_vol=true_vol)
    clamp = lambda x, lo, hi: min(hi, max(lo, x))
    rows = []
    for _ in range(n):
        p0 = 86000 + rnd.uniform(-2000, 2000)
        step_sd = sigma_per_sqrt_sec(p0, true_vol) * math.sqrt(15)  # 15-second steps
        w = [p0]
        for _ in range(60):
            w.append(w[-1] + rnd.gauss(0, step_sd))
        target = p0
        p3, p6, p10 = w[12], w[24], w[40]
        settle = sum(w[57:61]) / 4.0          # roughly the last-60-second average
        max_dev = max(abs(x - target) for x in w)
        mkt6 = clamp(round(100 * fair_p_up(p6, target, 540, true)), 1, 99)
        pu10 = clamp(fair_p_up(p10, target, 300, true), 0.02, 0.98)
        delta = 0.0225                          # half of a 4.5% overround each side
        rows.append(dict(
            strike=target, p0=p0, p3=p3, p6=p6, final=settle,
            market_yes=float(mkt6), p10=p10,
            up10=float(clamp(round(100 * pu10), 1, 99)),
            up_mult=round(1 / (pu10 + delta), 2),
            down_mult=round(1 / ((1 - pu10) + delta), 2),
            max_dev=max_dev, result="yes" if settle > target else "no"))
    return rows


# ---------- test 1: the momentum verdicts ----------
def evaluate(rows, params, fee=0.0):
    stats = {v: dict(n=0, hits=0, naive=0, pnl=0.0, pnl_n=0)
             for v in (UP, DOWN, COIL, CHOP)}
    band_in = band_n = 0
    for r in rows:
        res = analyze(r["p0"], r["p3"], r["p6"], params)
        s = stats[res.verdict]
        s["n"] += 1
        if r["final"] is not None:
            band_n += 1
            if abs(r["final"] - r["p6"]) <= res.band:
                band_in += 1
        if res.verdict in (UP, DOWN):
            pred_yes = res.verdict == UP
            yes = r["result"] == "yes"
            hit = pred_yes == yes
            s["hits"] += hit
            s["naive"] += (r["p6"] > r["strike"]) == yes  # "just follow the strike side"
            if r["market_yes"] is not None:
                cost = r["market_yes"] if pred_yes else 100 - r["market_yes"]
                s["pnl"] += ((100 if hit else 0) - cost - fee) / 100
                s["pnl_n"] += 1
    return stats, band_in, band_n


def report(title, rows, params, fee):
    stats, band_in, band_n = evaluate(rows, params, fee)
    print(f"\n=== {title}  (n={len(rows)}) ===")
    print(f"params: {params}")
    print(f"{'verdict':<14}{'n':>5}  {'hit rate':>9}  {'95% CI':>13}  {'naive':>7}  {'avg P&L/contract':>17}")
    for v in (UP, DOWN, COIL, CHOP):
        s = stats[v]
        if v in (UP, DOWN) and s["n"]:
            lo, hi = wilson(s["hits"], s["n"])
            pnl = f"{s['pnl'] / s['pnl_n']:+.3f}" if s["pnl_n"] else "n/a"
            print(f"{v:<14}{s['n']:>5}  {s['hits'] / s['n']:>9.1%}  "
                  f"{lo:>5.1%}-{hi:<6.1%}  {s['naive'] / s['n']:>7.1%}  {pnl:>17}")
        else:
            print(f"{v:<14}{s['n']:>5}  {'(no call)':>9}")
    if band_n:
        lo, hi = wilson(band_in, band_n)
        print(f"band coverage: final landed inside +/-band {band_in / band_n:.1%} "
              f"(CI {lo:.1%}-{hi:.1%}, n={band_n})")
    else:
        print("band coverage: no final prices logged")
    return stats


def tune(train, fee, min_priced=30):
    """Pick params by average P&L per contract (needs market prices in the data).

    Hit rate alone is a trap: any rule that follows the side of the strike
    wins often, but the market already prices that in. P&L is what counts.
    Falls back to the hit-rate lower bound only if no market prices were logged.
    Note: this P&L uses the displayed Up % as the price, with no spread, so it
    is optimistic. The multiplier-based test below is the realistic one.
    """
    use_pnl = any(r["market_yes"] is not None for r in train)
    grid = itertools.product([0.0002, 0.0005, 0.001],   # coil_pct
                             [0.0001, 0.0002, 0.0004],  # min_leg_pct
                             [0.0, 1.0, 1.5])           # accel_ratio
    best, best_score = Params(), -math.inf
    for c, m, a in grid:
        p = Params(coil_pct=c, min_leg_pct=m, accel_ratio=a)
        st, _, _ = evaluate(train, p, fee)
        n = st[UP]["n"] + st[DOWN]["n"]
        k = st[UP]["hits"] + st[DOWN]["hits"]
        if use_pnl:
            pn = st[UP]["pnl_n"] + st[DOWN]["pnl_n"]
            score = (st[UP]["pnl"] + st[DOWN]["pnl"]) / pn if pn >= min_priced else -math.inf
        else:
            score = wilson(k, n)[0] if n else -math.inf
        if score > best_score:
            best, best_score = p, score
    return best


# ---------- test 2: distance over time at the 5:00-left snapshot ----------
def snapshots(rows):
    return [r for r in rows if r["p10"] is not None and r["up10"] is not None]


def brier(pairs):
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


def distance_report(title, rows, params, snap_sec):
    snap = snapshots(rows)
    print(f"\n=== {title} ===")
    if len(snap) < 20:
        print(f"Only {len(snap)} windows with a 5:00 snapshot (price + Up %). Need many more.")
        return
    yes = lambda r: 1.0 if r["result"] == "yes" else 0.0
    model = [(fair_p_up(r["p10"], r["strike"], snap_sec, params), yes(r)) for r in snap]
    mkt = [(r["up10"] / 100.0, yes(r)) for r in snap]
    print(f"windows: {len(snap)}   annual vol assumed: {params.annual_vol:.2f}")
    print(f"Brier score (lower is better): model {brier(model):.4f} | "
          f"market {brier(mkt):.4f} | always-50% 0.2500")

    for label, gap in (("where model and market differ by 2+ points", 0.02),
                       ("where model and market differ by 5+ points", GAP)):
        n = hits = 0
        pnl = 0.0
        for r, (pm, _) in zip(snap, model):
            if r["up_mult"] is None or r["down_mult"] is None:
                continue
            diff = pm - r["up10"] / 100.0
            if diff == 0 or abs(diff) < gap:
                continue
            up = diff > 0
            m = r["up_mult"] if up else r["down_mult"]
            hit = (r["result"] == "yes") == up
            n += 1
            hits += hit
            pnl += m * hit - 1
        if n:
            print(f"bet {label}: {n} bets, hit rate {hits / n:.1%}, "
                  f"avg P&L per $1 staked {pnl / n:+.3f}")
        else:
            print(f"bet {label}: no qualifying windows (needs multipliers logged)")

    both = [1 / r["up_mult"] + 1 / r["down_mult"] for r in snap
            if r["up_mult"] and r["down_mult"]]
    if both:
        print(f"built-in cost implied by multipliers: {sum(both) / len(both) - 1:+.1%} "
              f"(assumes multiplier = payout per $1)")


def tune_vol(train, snap_sec):
    """One parameter only: the annual vol that minimises Brier score on train."""
    snap = snapshots(train)
    if len(snap) < 20:
        return Params()
    best, best_b = Params(), math.inf
    for v in (0.20, 0.30, 0.40, 0.50, 0.60, 0.80):
        p = Params(annual_vol=v)
        b = brier([(fair_p_up(r["p10"], r["strike"], snap_sec, p),
                    1.0 if r["result"] == "yes" else 0.0) for r in snap])
        if b < best_b:
            best, best_b = p, b
    return best


# ---------- test 3: is there really a ceiling? ----------
def cap_report(rows):
    d = sorted(r["max_dev"] for r in rows if r["max_dev"] is not None)
    print("\n=== Largest swing from target per window ===")
    if len(d) < 20:
        print(f"Only {len(d)} windows with max swing logged.")
        return
    n = len(d)
    q = lambda p: d[min(n - 1, int(p * n))]
    print(f"windows: {n}   median ${q(0.5):,.0f}   90th pct ${q(0.9):,.0f}   "
          f"95th pct ${q(0.95):,.0f}   max ${d[-1]:,.0f}")
    print(f"share at or above $400: {sum(x >= 400 for x in d) / n:.1%}   "
          f"at or above $500: {sum(x >= 500 for x in d) / n:.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--demo", type=int, metavar="N")
    ap.add_argument("--fee", type=float, default=0.0)
    ap.add_argument("--split", type=float, default=0.7)
    ap.add_argument("--snap-sec", type=float, default=300.0)
    a = ap.parse_args()

    if a.demo:
        rows = make_demo(a.demo)
        print(f"DEMO MODE: {a.demo} simulated windows. The market uses the same model as the")
        print("engine plus a 4.5% built-in cost, so no strategy can win. Expect: momentum hit")
        print("rates that look high but match the 'naive' column, model Brier equal to market")
        print("Brier, and distance-test P&L at or below zero (the 4.5% cost eats any noise).")
        print("A clear, repeatable positive P&L here = a bug.")
    elif a.csv:
        rows = load(a.csv)
    else:
        ap.error("give a csv path or --demo N")

    if len(rows) < 100:
        print(f"\nWARNING: only {len(rows)} windows. Results below are mostly noise; aim for 300+.")

    cut = int(len(rows) * a.split)
    train, test = rows[:cut], rows[cut:]   # chronological, no shuffling

    print("\n########## Test 1: momentum verdicts ##########")
    report("ALL DATA, default params", rows, Params(), a.fee)
    best = tune(train, a.fee)
    print("\n--- Tuning on the first %d%% only (27 param combos tried) ---" % int(a.split * 100))
    report("TRAIN, tuned params", train, best, a.fee)
    report("TEST (unseen), tuned params  <-- the number that matters", test, best, a.fee)
    report("TEST (unseen), default params", test, Params(), a.fee)

    print("\n########## Test 2: distance over time (5:00-left snapshot) ##########")
    distance_report("ALL windows, default vol", rows, Params(), a.snap_sec)
    v = tune_vol(train, a.snap_sec)
    print(f"\nVol tuned on train only (6 values tried): {v.annual_vol:.2f}")
    distance_report("TEST (unseen), tuned vol  <-- the number that matters", test, v, a.snap_sec)

    print("\n########## Test 3: the swing ceiling ##########")
    cap_report(rows)

    print("\nIf TEST is much worse than TRAIN, the tuning fit noise. --fee is cents per contract.")


if __name__ == "__main__":
    main()
