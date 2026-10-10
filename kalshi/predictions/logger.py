#!/usr/bin/env python3
"""logger.py - log one row per 15-minute window to windows.csv.

Run it when a window starts and answer each prompt as the clock reaches
that time. Only target, the three early prices and the final yes/no are
required; press Enter to skip anything else.
Use Kalshi's ACTUAL settled result (yes/no), not your own calculation.

Per Kalshi's rules text, settlement is the average of the CF index over the
last 60 seconds, so the app's "Now" price is only a proxy for it.
"""
import csv
import datetime
import os
import sys

FIELDS = ["ts", "asset", "target", "p0", "p3", "p6", "market_yes_cents",
          "p10", "up_pct10", "up_mult10", "down_mult10",
          "max_dev", "final", "result"]


def ask_float(prompt, optional=False):
    while True:
        raw = input(prompt).strip()
        if optional and raw == "":
            return ""
        try:
            return float(raw)
        except ValueError:
            print("  Enter a number.")


def ask_result():
    while True:
        raw = input("Kalshi settled result (yes/no): ").strip().lower()
        if raw in ("yes", "no"):
            return raw
        print("  Type yes or no.")


def main(path="windows.csv"):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        while True:
            asset = input("\nAsset (btc/eth/...; blank to quit): ").strip().lower()
            if not asset:
                break
            target = ask_float("Target (price to beat): ")
            p0 = ask_float("Price at 15:00 left (min 0): ")
            p3 = ask_float("Price at 12:00 left (min 3): ")
            p6 = ask_float("Price at 9:00 left (min 6): ")
            mkt6 = ask_float("Up % shown at 9:00 left (Enter to skip): ", optional=True)
            p10 = ask_float("Price at 5:00 left (min 10) (Enter to skip): ", optional=True)
            up10 = ask_float("Up % shown at 5:00 left (Enter to skip): ", optional=True)
            um10 = ask_float("Up multiplier at 5:00 left, e.g. 2.14 (Enter to skip): ", optional=True)
            dm10 = ask_float("Down multiplier at 5:00 left, e.g. 1.73 (Enter to skip): ", optional=True)
            input("Wait for the window to settle, then press Enter...")
            max_dev = ask_float("Largest swing from target seen this window, in $ (Enter to skip): ",
                                optional=True)
            final = ask_float("Final price, or the 60-second average if you know it (Enter to skip): ",
                              optional=True)
            result = ask_result()
            w.writerow({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                        "asset": asset, "target": target, "p0": p0, "p3": p3, "p6": p6,
                        "market_yes_cents": mkt6, "p10": p10, "up_pct10": up10,
                        "up_mult10": um10, "down_mult10": dm10,
                        "max_dev": max_dev, "final": final, "result": result})
            f.flush()
            print("Saved.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "windows.csv")
