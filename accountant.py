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

    def record_confirmed_fill(self, inst_id: str, side: str, price: float, size: float, tag: str = "Manual"):
        """Records a successful fill in the ledger."""
        # Use Taker Rate for the realized ledger as a conservative standard
        fee_usd = price * size * self.taker_rate
        self.total_fees_paid += fee_usd

        fill = {
            "time": time.strftime("%H:%M:%S"),
            "inst": inst_id,
            "side": side.upper(),
            "px": price,
            "sz": size,
            "fee": fee_usd,
            "tag": tag
        }
        self.fills.append(fill)

        # Basic position tracking for session PnL
        pos = self.positions.get(inst_id, {"size": 0.0, "avg_price": 0.0})
        curr_sz = pos["size"]
        curr_avg = pos["avg_price"]

        if side.upper() == "BUY":
            new_sz = curr_sz + size
            if curr_sz < 0:
                covered = min(abs(curr_sz), size)
                self.realized_pnl_gross += (curr_avg - price) * covered
            if new_sz > 0:
                pos["avg_price"] = ((curr_avg * max(0, curr_sz)) + (price * size)) / new_sz
            pos["size"] = new_sz
        elif side.upper() == "SELL":
            new_sz = curr_sz - size
            if curr_sz > 0:
                sold = min(curr_sz, size)
                self.realized_pnl_gross += (price - curr_avg) * sold
            if new_sz < 0:
                pos["avg_price"] = ((curr_avg * min(0, curr_sz)) + (price * -size)) / new_sz
            pos["size"] = new_sz

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
