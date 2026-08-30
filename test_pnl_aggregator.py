import time
from typing import List, Dict, Any

class PnLAggregator:
    """
    [MONEY COUNTER CORE] 
    Prototypes the logic for aggregating manual and strategy-based PnL 
    into a single high-fidelity USD readout.
    """
    def __init__(self):
        self.realized_pnl = 0.0
        self.positions = {} # {inst_id: {"size": float, "avg_price": float}}
        self.fills = [] # Log of all session fills for audit

    def record_fill(self, inst_id: str, side: str, price: float, size: float, tag: str = "Manual"):
        """Records a trade and updates the session's net position."""
        fill = {
            "time": time.strftime("%H:%M:%S"),
            "inst": inst_id,
            "side": side.upper(),
            "px": price,
            "sz": size,
            "tag": tag
        }
        self.fills.append(fill)

        # Update Position / Realize PnL
        pos = self.positions.get(inst_id, {"size": 0.0, "avg_price": 0.0})
        curr_sz = pos["size"]
        curr_avg = pos["avg_price"]

        if side.upper() == "BUY":
            new_sz = curr_sz + size
            # If we were short, realize profit/loss on the covered portion
            if curr_sz < 0:
                covered = min(abs(curr_sz), size)
                self.realized_pnl += (curr_avg - price) * covered
            
            # Update average price for the remaining/new long position
            if new_sz > 0:
                pos["avg_price"] = ((curr_avg * max(0, curr_sz)) + (price * size)) / new_sz
            pos["size"] = new_sz

        elif side.upper() == "SELL":
            new_sz = curr_sz - size
            # If we were long, realize profit/loss on the sold portion
            if curr_sz > 0:
                sold = min(curr_sz, size)
                self.realized_pnl += (price - curr_avg) * sold
            
            # Update average price for the remaining/new short position
            if new_sz < 0:
                # Average price for a short is the entry price
                pos["avg_price"] = ((curr_avg * min(0, curr_sz)) + (price * -size)) / new_sz
            pos["size"] = new_sz

        self.positions[inst_id] = pos

    def get_session_report(self, current_market_prices: Dict[str, float]) -> Dict[str, Any]:
        """Calculates total net value (Realized + Unrealized)."""
        unrealized = 0.0
        active_positions = []

        for inst, pos in self.positions.items():
            if pos["size"] == 0: continue
            
            mark_price = current_market_prices.get(inst, pos["avg_price"])
            u_pnl = (mark_price - pos["avg_price"]) * pos["size"]
            unrealized += u_pnl
            
            active_positions.append({
                "inst": inst,
                "size": pos["size"],
                "avg": pos["avg_price"],
                "pnl": u_pnl
            })

        total_net = self.realized_pnl + unrealized
        return {
            "realized": self.realized_pnl,
            "unrealized": unrealized,
            "net": total_net,
            "positions": active_positions
        }

def test_money_counter_scenario():
    counter = PnLAggregator()
    
    print("\n[STEP 1] Manual Buy BTC @ $95,000")
    counter.record_fill("BTC-USD", "BUY", 95000.0, 0.1, tag="Manual")
    
    print("[STEP 2] Grid Bot Sell BTC @ $98,000 (Partial TP)")
    counter.record_fill("BTC-USD", "SELL", 98000.0, 0.05, tag="GridBot")
    
    print("[STEP 3] DCA Bot Buy ETH @ $2,500")
    counter.record_fill("ETH-USD", "BUY", 2500.0, 1.0, tag="DCABot")

    # MOCK MARKET MOVE
    market = {"BTC-USD": 97000.0, "ETH-USD": 2650.0}
    report = counter.get_session_report(market)

    print("\n" + "="*50)
    print("      OXX TERMINAL: THE MONEY COUNTER (MOCK)")
    print("="*50)
    
    color = "GREEN" if report['net'] >= 0 else "RED"
    print(f" SESSION NET SCORE:  ${report['net']:,.2f} ({color})")
    print(f" Realized (Gains):   ${report['realized']:,.2f}")
    print(f" Unrealized (Open):  ${report['unrealized']:,.2f}")
    print("-" * 50)
    print(" ACTIVE POSITIONS:")
    for p in report['positions']:
        p_color = "CYAN" if p['pnl'] >= 0 else "MAGENTA"
        print(f"  • {p['inst']:<10} | Sz: {p['size']:>6.3f} | Avg: ${p['avg']:>10,.2f} | PnL: {p_color}(${p['pnl']:,.2f})")
    print("="*50)

if __name__ == "__main__":
    test_money_counter_scenario()
