import logging
import time
import math

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Strategy_Engine")

class OKXGridValidator:
    def __init__(self, min_order_val: float = 1.0, min_grids: int = 2, max_grids: int = 150):
        self.min_order_val = min_order_val
        self.min_grids = min_grids
        self.max_grids = max_grids

    def validate_setup(self, lower_price: float, upper_price: float, grid_count: int, 
                       total_investment: float, current_market_price: float) -> tuple:
        
        # 1. Range bounds check
        if lower_price >= upper_price:
            return False, "Error: Lower price must be strictly less than upper price."
        
        # 2. Market price containment check (OKX requirement for Spot Grid)
        if not (lower_price <= current_market_price <= upper_price):
            return False, f"Error: Price (${current_market_price}) is outside grid range [${lower_price}, ${upper_price}]."

        # 3. Grid count boundaries
        if not (self.min_grids <= grid_count <= self.max_grids):
            return False, f"Error: Grid count must be between {self.min_grids} and {self.max_grids}."

        # 4. Investment per grid (OKX minimum sizing check)
        investment_per_grid = total_investment / grid_count
        if investment_per_grid < self.min_order_val:
            return False, (
                f"Error: Investment per grid (${investment_per_grid:.2f}) is below "
                f"OKX minimum threshold (${self.min_order_val:.2f})."
            )

        return True, "Validation Passed"

class GridStrategyEngine:
    def __init__(self, inst_id: str, lower_bound: float, upper_bound: float, grids: int, investment_amount: float, grid_type: str = "arithmetic"):
        self.inst_id = inst_id
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.grids = grids
        self.investment_amount = investment_amount
        self.grid_type = grid_type.lower()
        self.grid_levels = []
        self.last_grid_index = None
        self.active = False
        self.realized_pnl = 0.0
        self.current_pos = 0.0
        self.avg_price = 0.0
        self._initialize_grid()

    def _initialize_grid(self):
        """Calculates the price points for each grid buy/sell level."""
        if self.grids <= 1:
            raise ValueError("Grid count must be greater than 1.")

        if self.grid_type == "geometric":
            # Geometric ratio
            ratio = (self.upper_bound / self.lower_bound) ** (1 / (self.grids - 1))
            self.grid_levels = [round(self.lower_bound * (ratio ** i), 2) for i in range(self.grids)]
        else:
            # Arithmetic (default)
            step = (self.upper_bound - self.lower_bound) / (self.grids - 1)
            self.grid_levels = [round(self.lower_bound + (i * step), 2) for i in range(self.grids)]
            
        self.grid_levels = sorted(self.grid_levels)
        logger.info(f"Initialized {self.grid_type.upper()} Grid Strategy for {self.inst_id} with {self.grids} levels: {self.grid_levels}")

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
            anchor_lvl = self.grid_levels[self.last_grid_index] if self.last_grid_index is not None else "None"
            return ("LOG", f"Grid Bot Active @ ${current_price}. Anchor Level: {anchor_lvl}", 0, "GridBot")

        # Check for grid crossing
        new_index = None
        for i, level in enumerate(self.grid_levels):
            if current_price >= level:
                new_index = i
        
        if new_index is not None and self.last_grid_index is not None:
            if new_index > self.last_grid_index:
                # Price moved up -> SELL at the levels we crossed
                self.last_grid_index = new_index
                sz = self.investment_amount / self.grids / current_price
                return ("SELL", self.grid_levels[new_index], sz, "GridBot")
            elif new_index < self.last_grid_index:
                # Price moved down -> BUY at the level we crossed
                self.last_grid_index = new_index
                sz = self.investment_amount / self.grids / current_price
                return ("BUY", self.grid_levels[new_index], sz, "GridBot")

        return None

    def update_position(self, side: str, price: float, size: float):
        """Updates internal state based on a confirmed fill."""
        if side.lower() == "buy":
            new_pos = self.current_pos + size
            if new_pos > 0:
                self.avg_price = ((self.avg_price * self.current_pos) + (price * size)) / new_pos
            self.current_pos = new_pos
            logger.info(f"GridBot {self.inst_id} filled BUY: {size} @ {price}. New Pos: {self.current_pos}, Avg: {self.avg_price}")
        
        elif side.lower() == "sell":
            if self.current_pos > 0:
                # Realize PnL against the average price
                pnl_gain = (price - self.avg_price) * size
                self.realized_pnl += pnl_gain
                self.current_pos -= size
                logger.info(f"GridBot {self.inst_id} filled SELL: {size} @ {price}. Realized Gain: {pnl_gain}. Total Realized: {self.realized_pnl}")
            else:
                self.current_pos -= size

    def calculate_pnl(self, current_price: float) -> float:
        """Calculates total PnL (Realized + Unrealized)."""
        unrealized = self.current_pos * (current_price - self.avg_price) if self.current_pos != 0 else 0
        return self.realized_pnl + unrealized

class StrategyManager:
    """Orchestrates multiple active strategy instances."""
    def __init__(self):
        self.active_bots = {} # {bot_id: bot_instance}
        self.total_pnl = 0.0

    @staticmethod
    def calculate_ema(data: list, period: int) -> list:
        """Computes the Exponential Moving Average (EMA) for a given series."""
        if len(data) < period:
            return [None] * len(data)
        
        ema = [None] * len(data)
        multiplier = 2 / (period + 1)
        
        # Start with simple SMA for the first valid point
        initial_sma = sum(data[:period]) / period
        ema[period - 1] = initial_sma
        
        for i in range(period, len(data)):
            ema[i] = (data[i] - ema[i - 1]) * multiplier + ema[i - 1]
            
        return ema

    @staticmethod
    def calculate_rsi(data: list, period: int = 14) -> list:
        """Computes the Relative Strength Index (RSI) using Wilder's smoothing."""
        if len(data) <= period:
            return [None] * len(data)
            
        rsi = [None] * len(data)
        deltas = [data[i] - data[i - 1] for i in range(1, len(data))]
        
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        if avg_loss == 0:
            rsi[period] = 100
        else:
            rs = avg_gain / avg_loss
            rsi[period] = 100 - (100 / (1 + rs))
            
        for i in range(period + 1, len(data)):
            # Wilder's Smoothing
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            
            if avg_loss == 0:
                rsi[i] = 100
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))
                
        return rsi

    def start_grid_bot(self, inst_id: str, lower: float, upper: float, grids: int, investment: float, grid_type: str = "arithmetic"):
        bot_id = f"grid_{inst_id}_{int(time.time())}"
        bot = GridStrategyEngine(inst_id, lower, upper, grids, investment, grid_type)
        self.active_bots[bot_id] = bot
        return bot_id

    def start_dca_bot(self, inst_id: str, base_amount: float, drop_pct: float):
        bot_id = f"dca_{inst_id}_{int(time.time())}"
        bot = DCAStrategyEngine(inst_id, base_amount, drop_pct)
        self.active_bots[bot_id] = bot
        return bot_id

    def update_bot_fill(self, bot_id, side, price, size):
        """Passes a fill event to a specific bot."""
        if bot_id in self.active_bots:
            self.active_bots[bot_id].update_position(side, price, size)

    def get_total_session_pnl(self, current_prices):
        """
        Aggregates PnL across all active bots.
        current_prices: {inst_id: price}
        """
        total = 0.0
        for bot in self.active_bots.values():
            price = current_prices.get(bot.inst_id)
            if price is not None:
                total += bot.calculate_pnl(price)
            else:
                # If no current price, just add realized
                total += bot.realized_pnl
        return total

    def stop_all(self):
        count = len(self.active_bots)
        self.active_bots.clear()
        return count

    def get_status_summary(self):
        bot_details = []
        for bid, bot in self.active_bots.items():
            type_str = "GRID" if isinstance(bot, GridStrategyEngine) else "DCA"
            bot_details.append(f"{type_str} | {bot.inst_id} | Pos: {bot.current_pos:.4f}")
            
        return {
            "count": len(self.active_bots),
            "status": "ACTIVE" if self.active_bots else "IDLE",
            "details": "\n".join(bot_details) if bot_details else "No active bots"
        }

class DCAStrategyEngine:
    def __init__(self, inst_id: str, base_order_size: float, drop_trigger_pct: float):
        self.inst_id = inst_id
        self.base_order_size = base_order_size # In USD
        self.drop_trigger_pct = drop_trigger_pct
        self.last_purchase_price = None
        self.active = False
        self.realized_pnl = 0.0
        self.current_pos = 0.0
        self.avg_price = 0.0

    def process_tick(self, current_price: float):
        """Checks if the price has dropped enough from the last buy to trigger a DCA order."""
        if not self.active:
            self.active = True
            self.last_purchase_price = current_price
            sz = self.base_order_size / current_price
            return ("BUY", current_price, sz, "DCABot")

        drop_pct = ((self.last_purchase_price - current_price) / self.last_purchase_price) * 100
        if drop_pct >= self.drop_trigger_pct:
            logger.info(f"DCA Triggered! Price dropped by {drop_pct:.2f}%")
            self.last_purchase_price = current_price
            sz = self.base_order_size / current_price
            return ("BUY", current_price, sz, "DCABot")

        return None

    def update_position(self, side: str, price: float, size: float):
        if side.lower() == "buy":
            new_pos = self.current_pos + size
            if new_pos > 0:
                self.avg_price = ((self.avg_price * self.current_pos) + (price * size)) / new_pos
            self.current_pos = new_pos
            logger.info(f"DCABot {self.inst_id} filled BUY: {size} @ {price}. New Pos: {self.current_pos}, Avg: {self.avg_price}")
        elif side.lower() == "sell":
            # DCA usually only buys, but we allow sell for manual intervention/TP
            if self.current_pos > 0:
                pnl_gain = (price - self.avg_price) * size
                self.realized_pnl += pnl_gain
                self.current_pos -= size
                logger.info(f"DCABot {self.inst_id} filled SELL: {size} @ {price}. Realized Gain: {pnl_gain}")
            else:
                self.current_pos -= size

    def calculate_pnl(self, current_price: float) -> float:
        unrealized = self.current_pos * (current_price - self.avg_price) if self.current_pos != 0 else 0
        return self.realized_pnl + unrealized
