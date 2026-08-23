import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Strategy_Engine")

class GridStrategyEngine:
    def __init__(self, inst_id: str, lower_bound: float, upper_bound: float, grids: int, investment_amount: float):
        self.inst_id = inst_id
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.grids = grids
        self.investment_amount = investment_amount
        self.grid_levels = []
        self.last_grid_index = None
        self.active = False
        self._initialize_grid()

    def _initialize_grid(self):
        """Calculates the price points for each grid buy/sell level."""
        if self.grids <= 1:
            raise ValueError("Grid count must be greater than 1.")

        step = (self.upper_bound - self.lower_bound) / (self.grids - 1)
        self.grid_levels = [round(self.lower_bound + (i * step), 2) for i in range(self.grids)]
        logger.info(f"Initialized Grid Strategy for {self.inst_id} with {self.grids} levels between {self.lower_bound} and {self.upper_bound}")

    def process_tick(self, current_price: float):
        """
        Evaluates the current market price and returns a signal if a grid level is crossed.
        Returns: (signal_type, price, size) or None
        """
        if not self.active:
            # Initial anchor point
            for i, level in enumerate(self.grid_levels):
                if current_price >= level:
                    self.last_grid_index = i
            self.active = True
            return ("LOG", f"Bot initialized at ${current_price}. Anchor grid level: {self.grid_levels[self.last_grid_index] if self.last_grid_index is not None else 'None'}", 0)

        # Check for grid crossing
        new_index = None
        for i, level in enumerate(self.grid_levels):
            if current_price >= level:
                new_index = i
        
        if new_index is not None and self.last_grid_index is not None:
            if new_index > self.last_grid_index:
                # Price moved up through a grid level -> SELL
                self.last_grid_index = new_index
                sz = self.investment_amount / current_price
                return ("SELL", self.grid_levels[new_index], sz)
            elif new_index < self.last_grid_index:
                # Price moved down through a grid level -> BUY
                self.last_grid_index = new_index
                sz = self.investment_amount / current_price
                return ("BUY", self.grid_levels[new_index], sz)

        return None

class StrategyManager:
    """Orchestrates multiple active strategy instances."""
    def __init__(self):
        self.active_bots = {} # {bot_id: bot_instance}
        self.total_pnl = 0.0

    def start_grid_bot(self, inst_id: str, lower: float, upper: float, grids: int, investment: float):
        bot_id = f"grid_{inst_id}_{int(time.time())}"
        bot = GridStrategyEngine(inst_id, lower, upper, grids, investment)
        self.active_bots[bot_id] = bot
        return bot_id

    def stop_all(self):
        count = len(self.active_bots)
        self.active_bots.clear()
        return count

    def get_status_summary(self):
        return {
            "count": len(self.active_bots),
            "pnl": self.total_pnl,
            "status": "ACTIVE" if self.active_bots else "IDLE"
        }

class DCAStrategyEngine:
    def __init__(self, target_asset: str, base_order_size: float, drop_trigger_pct: float):
        self.target_asset = target_asset
        self.base_order_size = base_order_size
        self.drop_trigger_pct = drop_trigger_pct
        self.last_purchase_price = None

    def check_dca_trigger(self, current_price: float) -> bool:
        """Checks if the price has dropped enough from the last buy to trigger a DCA order."""
        if self.last_purchase_price is None:
            self.last_purchase_price = current_price
            return True # Initial order

        drop_pct = ((self.last_purchase_price - current_price) / self.last_purchase_price) * 100
        if drop_pct >= self.drop_trigger_pct:
            logger.info(f"DCA Triggered! Price dropped by {drop_pct:.2f}% (Target: {self.drop_trigger_pct}%)")
            self.last_purchase_price = current_price
            return True

        return False
