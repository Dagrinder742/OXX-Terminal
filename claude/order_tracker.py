"""Order lifecycle tracking -- the difference between "the exchange accepted my order" and
"my order traded".

Why this exists: an accepted limit order may rest unfilled for minutes, fill in pieces, or be
cancelled.  Booking it as a fill at the moment of acceptance made the ledger, PnL and bot state
wrong.  Here, placing an order only REGISTERS it; fills are booked from what the exchange reports.

Everything here is plain Python (no Textual) so it can be tested without a terminal:
  * new_cl_ord_id()   unique client order id, so a placement whose answer was lost can be looked up
  * TrackedOrder      one order and how much of it has already been booked
  * OrderTracker      polls the exchange, books new fills exactly once, cancels, reports
  * SimExchange       a fake exchange with the same interface, driven by live prices (simulation mode)

OKX field names used (from the OKX v5 docs, as I remember them -- verify against the current docs):
  GET /api/v5/trade/order -> state (live | partially_filled | filled | canceled | mmp_canceled),
  accFillSz and avgPx (cumulative), fee (cumulative, NEGATIVE = charge) and feeCcy.
"""
import asyncio
import itertools
import logging
import string
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

TERMINAL_STATES = {"filled", "canceled", "mmp_canceled"}
_EPS = 1e-12
_ALPHABET = string.digits + string.ascii_lowercase
_counter = itertools.count(1)


def _b36(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _ALPHABET[r] + out
    return out or "0"


def new_cl_ord_id() -> str:
    """OKX clOrdId: letters and digits only, at most 32 characters."""
    return "oxx" + _b36(int(time.time() * 1000)) + _b36(next(_counter))


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TrackedOrder:
    cl_ord_id: str
    inst_id: str
    side: str                     # "buy" | "sell"
    ord_type: str                 # "limit" | "market"
    sz: float                     # requested size, base currency
    px: Optional[float] = None
    tag: str = "Manual"
    bot_id: Optional[str] = None
    ord_id: Optional[str] = None
    state: str = "live"           # live | partially_filled | filled | canceled | not_placed
    booked_sz: float = 0.0        # already given to the ledger
    booked_value: float = 0.0     # booked_sz * average price
    booked_fee: float = 0.0       # quote-currency fee already booked
    uncertain: bool = False       # placement answer was lost: confirm by clOrdId
    first_missing: Optional[float] = None
    errors: int = 0
    warned: bool = False
    created: float = field(default_factory=time.monotonic)

    @property
    def base(self) -> str:
        return self.inst_id.split("-")[0]

    @property
    def quote(self) -> str:
        parts = self.inst_id.split("-")
        return parts[1] if len(parts) > 1 else ""

    @property
    def remaining(self) -> float:
        return max(0.0, self.sz - self.booked_sz)


class OrderTracker:
    """Tracks open orders and books each fill exactly once.

    exchange_fn()  returns an object with get_order(inst_id, ord_id, cl_ord_id) and
                   cancel_order(inst_id, ord_id, cl_ord_id) that answer in OKX's JSON shape.
                   It is a function so the exchange can be chosen at call time (simulation or live).
    on_fill(order, size, price, fee_quote)   a NEW piece of fill; fee_quote None = unknown
    on_closed(order, state, unfilled)        the order is finished (filled / canceled / not_placed)
    on_note(message)                         human-readable events
    """

    MISSING_GRACE = 20.0      # seconds an uncertain order may be "not found" before we say it was never placed
    ERROR_WARN_AFTER = 5      # consecutive failed reads before we tell the user

    def __init__(self, exchange_fn: Callable, on_fill: Callable, on_closed: Callable,
                 on_note: Optional[Callable] = None, clock: Callable = time.monotonic):
        self._exchange_fn = exchange_fn
        self._on_fill = on_fill
        self._on_closed = on_closed
        self._on_note = on_note or (lambda msg: None)
        self._clock = clock
        self.orders = {}      # cl_ord_id -> TrackedOrder (open ones only)

    # ------------------------------------------------------------------ registry
    def register(self, order: TrackedOrder) -> None:
        self.orders[order.cl_ord_id] = order

    def open_orders(self, bot_ids=None) -> list:
        """Open orders, optionally only those that belong to the given bot ids."""
        orders = list(self.orders.values())
        if bot_ids is not None:
            orders = [o for o in orders if o.bot_id in bot_ids]
        return orders

    # ------------------------------------------------------------------ polling
    async def poll(self) -> None:
        for order in list(self.orders.values()):
            await self._poll_one(order)

    async def _poll_one(self, order: TrackedOrder) -> None:
        exchange = self._exchange_fn()
        try:
            res = await asyncio.to_thread(exchange.get_order, order.inst_id, order.ord_id, order.cl_ord_id)
        except Exception as e:  # never let one bad read stop the others
            res = {"code": "500", "msg": f"{type(e).__name__}: {e}"}
        self._apply_response(order, res)

    def _apply_response(self, order: TrackedOrder, res: dict) -> None:
        if order.cl_ord_id not in self.orders:
            return            # a late answer for an order that is already finished
        code = str(res.get("code"))
        rows = res.get("data") or []
        if code == "0" and rows:
            order.errors = 0
            order.first_missing = None
            order.uncertain = False
            self._apply_row(order, rows[0])
            return

        msg = str(res.get("msg") or (rows[0].get("sMsg") if rows else "") or "")
        missing = code == "51603" or "not exist" in msg.lower()
        if missing and order.uncertain:
            now = self._clock()
            if order.first_missing is None:
                order.first_missing = now
            elif now - order.first_missing >= self.MISSING_GRACE:
                order.state = "not_placed"
                self._finish(order, "not_placed")
                self._on_note(f"[yellow]{order.tag} order {order.cl_ord_id} was NOT placed "
                              f"(the exchange has no record of it).[/yellow]")
            return

        order.errors += 1
        if order.errors >= self.ERROR_WARN_AFTER and not order.warned:
            order.warned = True
            self._on_note(f"[red]Cannot read status of {order.tag} order {order.cl_ord_id} "
                          f"(code {code}: {msg or 'no data'}). Still tracking; check the exchange.[/red]")

    def _apply_row(self, order: TrackedOrder, row: dict) -> None:
        if not order.ord_id and row.get("ordId"):
            order.ord_id = row["ordId"]
        state = str(row.get("state") or "").lower()
        acc = _f(row.get("accFillSz"))
        avg = _f(row.get("avgPx")) or (order.px or 0.0)

        if acc > order.booked_sz + _EPS:
            if avg <= 0:
                self._on_note(f"[yellow]{order.tag}: fill reported without a price; will book it on the next read.[/yellow]")
            else:
                delta = acc - order.booked_sz
                value_total = acc * avg
                fill_px = (value_total - order.booked_value) / delta
                if fill_px <= 0:
                    fill_px = avg
                fee_total = self._fee_in_quote(order, row, avg)
                fee_delta = None
                if fee_total is not None:
                    fee_delta = max(0.0, fee_total - order.booked_fee)
                    order.booked_fee = fee_total
                order.booked_sz = acc
                order.booked_value = value_total
                self._on_fill(order, delta, fill_px, fee_delta)

        if state:
            order.state = state
        if state in TERMINAL_STATES:
            self._finish(order, state)

    @staticmethod
    def _fee_in_quote(order: TrackedOrder, row: dict, avg: float) -> Optional[float]:
        """Cumulative fee converted to the quote currency, or None when it can't be known.
        Spot BUY fees are usually charged in the base coin, SELL fees in the quote currency."""
        raw = row.get("fee")
        if raw in (None, ""):
            return None
        amount = abs(_f(raw))
        ccy = str(row.get("feeCcy") or "").upper()
        if ccy == order.quote.upper():
            return amount
        if ccy == order.base.upper():
            return amount * avg
        return None

    def _finish(self, order: TrackedOrder, state: str) -> None:
        self.orders.pop(order.cl_ord_id, None)
        unfilled = 0.0 if state == "filled" else order.remaining
        if unfilled < 1e-9:
            unfilled = 0.0
        self._on_closed(order, state, unfilled)

    # ------------------------------------------------------------------ cancelling
    async def cancel(self, orders) -> dict:
        """Asks the exchange to cancel each order, then ALWAYS re-reads it: a fill that beat the
        cancel is booked, and the final state is what we report -- not what we hoped for."""
        summary = {"requested": 0, "cancelled": 0, "already_done": 0, "unconfirmed": [], "failed": []}
        for order in list(orders):
            if order.cl_ord_id not in self.orders:
                continue
            summary["requested"] += 1
            exchange = self._exchange_fn()
            try:
                res = await asyncio.to_thread(exchange.cancel_order, order.inst_id, order.ord_id, order.cl_ord_id)
            except Exception as e:
                res = {"code": "500", "msg": f"{type(e).__name__}: {e}"}
            row = (res.get("data") or [{}])[0]
            accepted = str(res.get("code")) == "0" and str(row.get("sCode", "0")) == "0"
            reason = str(row.get("sMsg") or res.get("msg") or "unknown error")

            await self._poll_one(order)

            if order.cl_ord_id in self.orders:           # still open after the re-read
                if accepted:
                    summary["unconfirmed"].append(order)
                else:
                    summary["failed"].append((order, reason))
            elif order.state in ("canceled", "mmp_canceled"):
                summary["cancelled"] += 1
            else:                                        # filled (or never placed) before the cancel landed
                summary["already_done"] += 1
        return summary


# ====================================================================== simulation
class SimExchange:
    """A stand-in exchange for simulation mode, with the same interface and OKX-shaped answers.

    price_fn(inst_id) -> latest price or None.   rates_fn() -> (maker_rate, taker_rate).
    Fill model (deliberately simple): market orders fill at the current price as taker; a limit
    order that is already marketable fills at the current price as taker; otherwise it RESTS and
    fills at its own price (as maker) once the market trades through it.  No partial fills.
    Fees follow OKX spot: BUY fees are taken in the base coin, SELL fees in the quote currency.
    """

    def __init__(self, price_fn: Callable, rates_fn: Callable = lambda: (0.0020, 0.0035)):
        self.price_fn = price_fn
        self.rates_fn = rates_fn
        self._orders = {}                 # cl_ord_id -> dict
        self._seq = itertools.count(1)

    # ---- placement
    def place(self, inst_id, side, ord_type, sz, px, cl_ord_id) -> dict:
        o = {"inst": inst_id, "side": side.lower(), "type": ord_type, "sz": float(sz),
             "px": float(px) if px else None, "state": "live", "acc": 0.0, "avg": 0.0,
             "fee": 0.0, "fee_ccy": "", "ordId": f"SIM{next(self._seq)}", "clOrdId": cl_ord_id}
        self._orders[cl_ord_id] = o
        self._try_fill(o, placement=True)
        return {"code": "0", "msg": "", "data": [{"clOrdId": cl_ord_id, "ordId": o["ordId"], "sCode": "0", "sMsg": ""}]}

    def _try_fill(self, o: dict, placement: bool = False) -> None:
        if o["state"] != "live":
            return
        price = self.price_fn(o["inst"])
        if not price:
            return
        buy = o["side"] == "buy"
        if o["type"] == "market":
            self._fill(o, price, taker=True)
        elif placement and ((buy and o["px"] >= price) or (not buy and o["px"] <= price)):
            self._fill(o, price, taker=True)
        elif not placement and ((buy and price <= o["px"]) or (not buy and price >= o["px"])):
            self._fill(o, o["px"], taker=False)

    def _fill(self, o: dict, fill_px: float, taker: bool) -> None:
        maker_rate, taker_rate = self.rates_fn()
        rate = taker_rate if taker else maker_rate
        o["state"], o["acc"], o["avg"] = "filled", o["sz"], fill_px
        if o["side"] == "buy":
            o["fee"], o["fee_ccy"] = -o["sz"] * rate, o["inst"].split("-")[0]
        else:
            o["fee"], o["fee_ccy"] = -o["sz"] * fill_px * rate, o["inst"].split("-")[1]

    # ---- queries
    def _find(self, ord_id, cl_ord_id):
        if cl_ord_id and cl_ord_id in self._orders:
            return self._orders[cl_ord_id]
        for o in self._orders.values():
            if ord_id and o["ordId"] == ord_id:
                return o
        return None

    def get_order(self, inst_id, ord_id=None, cl_ord_id=None) -> dict:
        o = self._find(ord_id, cl_ord_id)
        if o is None:
            return {"code": "51603", "msg": "Order does not exist", "data": []}
        self._try_fill(o)
        row = {"instId": o["inst"], "ordId": o["ordId"], "clOrdId": o["clOrdId"], "side": o["side"],
               "ordType": o["type"], "state": o["state"], "sz": repr(o["sz"]),
               "px": repr(o["px"]) if o["px"] else "", "accFillSz": repr(o["acc"]),
               "avgPx": repr(o["avg"]) if o["acc"] else "0", "fee": repr(o["fee"]), "feeCcy": o["fee_ccy"]}
        return {"code": "0", "msg": "", "data": [row]}

    def cancel_order(self, inst_id, ord_id=None, cl_ord_id=None) -> dict:
        o = self._find(ord_id, cl_ord_id)
        if o is not None:
            self._try_fill(o)             # a fill that happened before the cancel arrives wins
        if o is None or o["state"] != "live":
            return {"code": "1", "msg": "All operations failed",
                    "data": [{"sCode": "51400", "sMsg": "Order cancellation failed as the order has been filled, canceled or does not exist"}]}
        o["state"] = "canceled"
        return {"code": "0", "msg": "", "data": [{"ordId": o["ordId"], "clOrdId": o["clOrdId"], "sCode": "0", "sMsg": ""}]}
