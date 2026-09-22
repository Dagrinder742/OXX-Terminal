#!/usr/bin/env python3
"""
market_reverser.py
15-Minute Prediction Market Reverse-Engineering Engine
Calculates terminal-state gravity and boundary constraints based on early interval inputs.
"""

def calculate_market_projection():
    print("=== 15-MINUTE MARKET REVERSE ENGINE ===")
    print("Enter the prices observed at early intervals to evaluate trend vs. trap.\n")

    try:
        anchor_price = float(input("Enter the starting baseline price (Minute 0): "))
        p3 = float(input("Enter price at Minute 3: "))
        p6 = float(input("Enter price at Minute 6: "))
    except ValueError:
        print("Invalid input. Please enter valid numbers.")
        return

    # 1. Calculate early velocity (rate of change in first 6 mins)
    delta_3 = p3 - anchor_price
    delta_6 = p6 - p3
    total_delta = p6 - anchor_price

    # 2. Time-decay gravity factor (Minutes 6 to 15 remaining window)
    time_remaining_ratio = 9.0 / 15.0  # 9 minutes left after the 6-minute mark

    # 3. Trend consistency check (Did it stall or accelerate in the same direction?)
    is_accelerating = (abs(total_delta) > 0) and ((delta_3 > 0) == (delta_6 > 0))

    print("\n--- DIAGNOSTIC RESULTS ---")
    print(f"Net Movement (Min 0 to 6): {total_delta:+.2f}")

    # 4. Evaluate against the Reverse Logic Rules with explicit DO NOT BUY directions
    if not is_accelerating and abs(total_delta) < (abs(anchor_price) * 0.001):
        print("Verdict: [STALE CHALK WALK / COIL]")
        print("Action: DO NOT BUY UP OR DOWN. The market is chopping inside a fakeout range.")
    elif is_accelerating and total_delta > 0:
        print("Verdict: [HEAVY BUY-SIDE MOMENTUM]")
        print("Action: Trend is upward. Look for a minor dip near the 10-minute mark to join. Do not buy down (fade) this trend.")
    elif is_accelerating and total_delta < 0:
        print("Verdict: [HEAVY SELL-SIDE PRESSURE]")
        print("Action: Trend is downward. Avoid buying up (bottom dips).")
    else:
        print("Verdict: [CHOPPY / CHAOTIC NOISE]")
        print("Action: DO NOT BUY UP OR DOWN. Stand aside; decimal multiplier is unstable.")

    # 5. Terminal-state boundary estimation
    implied_pullback_buffer = abs(total_delta) * time_remaining_ratio
    print(f"\nEstimated Remaining Fluctuation Band: ±{implied_pullback_buffer:.2f}")
    print("========================================")

if __name__ == "__main__":
    calculate_market_projection()

