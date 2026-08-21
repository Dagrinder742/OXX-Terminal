import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Strategy_Engine")

class GridStrategyEngine:
    def __init__(self, lower_bound: float, upper_bound: float, grids: int, investment_amount: float):
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.grids = grids
        self.investment_amount = investment_amount
        self.grid_levels = []
        self._initialize_grid()

    def _initialize_grid(self):
        """Calculates the price points for each grid buy/sell level."""
        if self.grids <= 1:
            raise ValueError("Grid count must be greater than 1.")

        step = (self.upper_bound - self.lower_bound) / (self.grids - 1)
        self.grid_levels = [round(self.lower_bound + (i * step), 2) for i in range(self.grids)]
        logger.info(f"Initialized Grid Strategy with {self.grids} levels between {self.lower_bound} and {self.upper_bound}")
        logger.info(f"Grid Levels: {self.grid_levels}")

    def evaluate_price(self, current_price: float) -> str:
        """
        Evaluates the current market price against grid thresholds
        to determine if a buy or sell trigger should occur.
        """
        # Find the closest grid level
        closest_level = min(self.grid_levels, key=lambda x: abs(x - current_price))

        # Simple threshold check for simulation/execution logic
        if current_price <= self.lower_bound:
            return "ALERT: Price breached lower grid bound! (Consider DCA / Accumulate)"
        elif current_price >= self.upper_bound:
            return "ALERT: Price breached upper grid bound! (Take Profit / Grid Complete)"
        else:
            return f"Market operating within bounds. Closest grid tier: {closest_level}"

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

