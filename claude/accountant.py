import time
import logging
from typing import Dict, Any

class PnLAccountant:
    """
    [OXX TACTICAL ACCOUNTANT]
    A physically decoupled math engine for tracking session PnL and 
    calculating pre-flight trade hurdles.
    """
    def __init__(self, taker_fee_rate: float = 0.0035, maker_fee_rate: float = 0.0020):
        # We default to standard VIP 0 rates if the API hasn't updated yet
        self.taker_rate = abs(float(taker_fee_rate))
        self.maker_rate = abs(float(maker_fee_rate))
        self.tier_label = "PENDING"
        self.realized_pnl_gross = 0.0
        self.total_fees_paid = 0.0
        self.positions = {} 
        self.fills = []
        # Spot cannot be shorted. When False, selling more than the session's tracked
        # inventory (e.g. coins you held before launch) books only the fee: there is no
        # cost basis, so inventing a 'short' would show fake profit when price falls.
        self.allow_short = False
        self.fee_level = "?"
        self.group_rates = {}
        self.worst_rates = (self.maker_rate, self.taker_rate)

    def load_fee_schedule(self, row: dict) -> None:
        """Reads one row of OKX /account/trade-fee (SPOT).

        OKX reports charges as NEGATIVE numbers; abs() treats everything as a cost, which is
        conservative if a rebate (positive) ever appears.  `feeGroup` holds one rate pair per
        fee group, and each instrument belongs to one group (instrument field `groupId`), so a
        single account-wide rate is wrong for most pairs.
        """
        self.fee_level = str(row.get("level", "?")).upper()
        self.group_rates = {}
        for g in row.get("feeGroup") or []:
            try:
                self.group_rates[str(g["groupId"])] = (abs(float(g["maker"])), abs(float(g["taker"])))
            except (KeyError, TypeError, ValueError):
                continue
        if self.group_rates:
            # Unknown group -> assume the most expensive one rather than under-estimate costs.
            self.worst_rates = (max(m for m, _ in self.group_rates.values()),
                                max(t for _, t in self.group_rates.values()))
        else:
            self.worst_rates = (abs(float(row.get("maker", 0.0020))), abs(float(row.get("taker", 0.0035))))
        self.apply_fee_group(None)

    def apply_fee_group(self, group_id) -> None:
        """Select the rates for an instrument's fee group (None/unknown -> worst case)."""
        rates = self.group_rates.get(str(group_id)) if group_id is not None else None
        if rates is not None:
            self.maker_rate, self.taker_rate = rates
            self.tier_label = f"{self.fee_level} g{group_id}"
        else:
            self.maker_rate, self.taker_rate = self.worst_rates
            self.tier_label = f"{self.fee_level} worst-case"

    def update_tier_data(self, taker: float, maker: float, level: str = "VIP 0"):
        """Updates the internal rates and tier label based on live OKX data."""
        self.taker_rate = abs(float(taker))
        self.maker_rate = abs(float(maker))
        self.tier_label = str(level).upper()

    def calculate_preflight_metrics(self, price: float, size: float, tp_price: float = None, sl_price: float = None) -> Dict[str, Any]:
        """
        Calculates tactical metrics with Liquidity-Aware logic:
        - Entry: Taker Rate (Conservative)
        - TP Exit: Maker Rate (Resting Limit)
        - SL Exit: Taker Rate (Market/Emergency)
        """
        if price <= 0 or size <= 0:
            return {"fee": 0.0, "break_even": 0.0, "net_tp": 0.0, "net_sl": 0.0}

        entry_fee = price * size * self.taker_rate
        
        # HURDLE: (Entry * (1 + Taker)) / (1 - Maker)
        # Assumes a successful trade clears via a resting TP (Maker).
        break_even = (price * (1 + self.taker_rate)) / (1 - self.maker_rate)
        
        total_est_friction = entry_fee
        net_tp = 0.0
        net_sl = 0.0
        
        if tp_price:
            # TP uses Maker Rate
            tp_exit_fee = tp_price * size * self.maker_rate
            net_tp = ((tp_price - price) * size) - (entry_fee + tp_exit_fee)
            total_est_friction = entry_fee + tp_exit_fee

        if sl_price:
            # SL uses Taker Rate (Emergency)
            sl_exit_fee = sl_price * size * self.taker_rate
            net_sl = ((sl_price - price) * size) - (entry_fee + sl_exit_fee)
            # If no TP set, show friction for the SL side
            if not tp_price:
                total_est_friction = entry_fee + sl_exit_fee

        return {
            "fee": total_est_friction,
            "break_even": break_even,
            "net_tp": net_tp,
            "net_sl": net_sl
        }

    def record_confirmed_fill(self, inst_id: str, side: str, price: float, size: float, tag: str = "Manual", fee_rate: float = None):
        """Records a fill in the ledger.

        fee_rate: pass the maker rate for resting limit fills; defaults to the taker rate
        (conservative).
        """
        rate = self.taker_rate if fee_rate is None else abs(float(fee_rate))
        fee_usd = price * size * rate
        self.total_fees_paid += fee_usd

        side_u = side.upper()
        self.fills.append({
            "time": time.strftime("%H:%M:%S"),
            "inst": inst_id,
            "side": side_u,
            "px": price,
            "sz": size,
            "fee": fee_usd,
            "tag": tag,
        })

        signed = size if side_u == "BUY" else -size
        pos = self.positions.get(inst_id, {"size": 0.0, "avg_price": 0.0})
        cur_sz, cur_avg = pos["size"], pos["avg_price"]
        eps = 1e-12

        if signed < 0 and cur_sz <= eps and not self.allow_short:
            # Selling inventory we never tracked: fee only (see allow_short above).
            self.positions[inst_id] = pos
            return

        if abs(cur_sz) <= eps or (cur_sz > 0) == (signed > 0):
            # Opening, or adding in the same direction: weighted-average entry price.
            new_sz = cur_sz + signed
            pos["avg_price"] = (abs(cur_sz) * cur_avg + size * price) / abs(new_sz)
            pos["size"] = new_sz
        else:
            # Reducing (or flipping) the position: realize PnL on the closed part only.
            closing = min(abs(cur_sz), size)
            direction = 1 if cur_sz > 0 else -1
            self.realized_pnl_gross += (price - cur_avg) * closing * direction
            new_sz = cur_sz + signed
            if abs(new_sz) <= eps or (new_sz < 0 and not self.allow_short):
                # Flat (or the excess was untracked pre-session inventory on a spot account).
                pos["size"], pos["avg_price"] = 0.0, 0.0
            elif (new_sz > 0) != (cur_sz > 0):
                # Flipped sides: the leftover is a brand-new position entered at this price.
                pos["size"], pos["avg_price"] = new_sz, price
            else:
                pos["size"] = new_sz  # partial close: entry price is unchanged

        self.positions[inst_id] = pos

    def get_session_summary(self, current_market_prices: Dict[str, float]) -> Dict[str, Any]:
        """Calculates the total NET SCORE of the session."""
        unrealized_gross = 0.0
        for inst, pos in self.positions.items():
            if pos["size"] == 0: continue
            mark_price = current_market_prices.get(inst, pos["avg_price"])
            unrealized_gross += (mark_price - pos["avg_price"]) * pos["size"]

        return {
            "net": (self.realized_pnl_gross + unrealized_gross) - self.total_fees_paid,
            "fees": self.total_fees_paid
        }
