"""Order and display formatting helpers (pure Python, no Textual / network).

Why this exists
---------------
* OKX rejects orders whose price/size are not exact multiples of the instrument's
  tickSz / lotSz, and str(float) can yield things like 0.00029746633052971317 or
  5e-09.  quantize_price / quantize_size turn any number into a plain decimal
  string that sits exactly on the exchange grid.
* Fixed ".2f" / ".4f" display formats hide the price of cheap coins (SHIB) and
  tiny trade sizes.  fmt_price / fmt_qty pick decimals by magnitude.
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP


def _dec(value) -> Decimal:
    # str() first: Decimal(0.1) would carry binary-float noise.
    return Decimal(str(value).replace(",", "").replace("$", "").strip())


def _plain(d: Decimal) -> str:
    """Decimal -> plain string, never scientific notation, no trailing zeros."""
    if d == 0:
        return "0"
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def quantize_size(value, lot_size) -> str:
    """Round a size DOWN to a multiple of lotSz (never spend more than asked)."""
    lot = _dec(lot_size)
    if lot <= 0:
        raise ValueError("lot size must be positive")
    steps = (_dec(value) / lot).to_integral_value(rounding=ROUND_DOWN)
    return _plain(steps * lot)


def quantize_price(value, tick_size) -> str:
    """Round a price to the NEAREST multiple of tickSz."""
    tick = _dec(tick_size)
    if tick <= 0:
        raise ValueError("tick size must be positive")
    steps = (_dec(value) / tick).to_integral_value(rounding=ROUND_HALF_UP)
    return _plain(steps * tick)


def fmt_price(x: float) -> str:
    """Display price with decimals chosen by magnitude (keeps cheap coins readable)."""
    ax = abs(x)
    if ax >= 100:
        return f"{x:,.2f}"
    if ax >= 1:
        return f"{x:,.3f}"
    if ax >= 0.01:
        return f"{x:.4f}"
    if ax >= 0.0001:
        return f"{x:.6f}"
    return f"{x:.8f}"


def fmt_qty(x: float) -> str:
    """Display size; small sizes get more decimals so they never show as 0.0000."""
    ax = abs(x)
    if ax >= 1:
        return f"{x:,.4f}"
    if ax >= 0.001:
        return f"{x:.6f}"
    return f"{x:.8f}"


def money(v: float) -> str:
    """$1,234.56 / -$1,234.56 (sign in front of the dollar sign)."""
    return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"
