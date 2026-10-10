"""engine.py - pure logic for the 15-minute reverse engine.

No input() or print() here, so it can be tested and backtested.
All Params defaults are UNTUNED GUESSES. Backtest them before trusting them.

Settlement note (from the Kalshi crypto rules text you shared): the value is a
simple average of the CF Benchmarks index over the 60 seconds before expiry,
not the last price. effective_seconds() models that. It assumes a driftless
random walk, which is itself an assumption to test, not a fact.
"""
import math
from dataclasses import dataclass

COIL, UP, DOWN, CHOP = "COIL", "MOMENTUM_UP", "MOMENTUM_DOWN", "CHOP"

SECONDS_PER_YEAR = 365 * 24 * 3600
AVG_WINDOW = 60  # seconds averaged at settlement, per the rules text


@dataclass(frozen=True)
class Params:
    coil_pct: float = 0.0005     # net move below this fraction of price = flat
    min_leg_pct: float = 0.0002  # each 3-min leg must move at least this much
    accel_ratio: float = 1.0     # |leg2| must be >= accel_ratio * |leg1| (0 = same direction only)
    band_factor: float = 0.6     # original script's arbitrary multiplier
    annual_vol: float = 0.40     # UNTUNED guess, used only by fair_p_up()


@dataclass(frozen=True)
class Result:
    verdict: str
    d3: float
    d6: float
    total: float
    band: float


def analyze(anchor, p3, p6, params=Params()):
    if anchor <= 0:
        raise ValueError("anchor must be > 0")
    d3 = p3 - anchor
    d6 = p6 - p3
    total = p6 - anchor

    min_leg = params.min_leg_pct * anchor
    same_dir = d3 * d6 > 0
    legs_ok = abs(d3) >= min_leg and abs(d6) >= min_leg
    accelerating = same_dir and legs_ok and abs(d6) >= params.accel_ratio * abs(d3)

    if abs(total) < params.coil_pct * anchor:
        verdict = COIL
    elif accelerating:
        verdict = UP if total > 0 else DOWN
    else:
        verdict = CHOP

    band = abs(total) * params.band_factor
    return Result(verdict, d3, d6, total, band)


# ---------- distance-over-time model ----------
def effective_seconds(seconds_left, avg_window=AVG_WINDOW):
    """Seconds of random-walk uncertainty left when settlement is the average
    of the last `avg_window` seconds.

    Variance of that average = a + tau/3, where a = seconds_left - tau,
    so the effective time is seconds_left - 2*tau/3 (about 40 s less for tau=60).
    Only valid while at least `avg_window` seconds remain; inside the window the
    running average is needed, which this does not model.
    """
    if seconds_left < avg_window:
        raise ValueError("inside the averaging window: needs the running average (not modeled)")
    return seconds_left - 2.0 * avg_window / 3.0


def sigma_per_sqrt_sec(price, annual_vol):
    """Dollar standard deviation per sqrt(second) for a given annualised vol."""
    return price * annual_vol / math.sqrt(SECONDS_PER_YEAR)


def zscore(price, target, seconds_left, params=Params()):
    """Distance from target in units of expected remaining spread.
    The spread is scaled off the target (not the live price) so that equal gaps
    above and below target are exact mirrors; the difference is well under 1%."""
    eff = effective_seconds(seconds_left)
    sd = sigma_per_sqrt_sec(target, params.annual_vol) * math.sqrt(eff)
    return (price - target) / sd


def fair_p_up(price, target, seconds_left, params=Params()):
    """Model probability that the settle value ends above target.
    Zero drift, normal moves, and `price` assumed to be the index itself."""
    z = zscore(price, target, seconds_left, params)
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
