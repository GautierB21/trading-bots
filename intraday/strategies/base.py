from abc import ABC, abstractmethod


class IntradayStrategy(ABC):
    def __init__(self, name, budget, symbols, timeframe_minutes):
        self.name = name
        self.budget = budget
        self.symbols = symbols
        self.timeframe = timeframe_minutes
        self.cash = budget
        self.positions = {}       # symbol -> {"quantity": float, "avg_price": float}
        self.last_signals = []    # last analyze() output, incl. empty runs
        self.last_analyzed_at = None
        self.paused = False

    @abstractmethod
    def analyze(self, candles_by_symbol):
        """Called once per timeframe with {symbol: [candle dict, ...]} (ascending).
        Returns list of (symbol, side, quantity, price, reason) tuples."""
        raise NotImplementedError

    def get_position(self, symbol):
        return self.positions.get(symbol)

    def execute(self, symbol, side, quantity, price, commission_rate):
        """Apply a fill in-memory (cash + positions). Returns (filled_quantity,
        commission) on success, or None if the order is rejected."""
        if quantity <= 0 or price <= 0:
            return None

        if side == "buy":
            cost = quantity * price
            commission = cost * commission_rate
            total = cost + commission
            if total > self.cash + 1e-9:
                max_cost = self.cash / (1 + commission_rate)
                quantity = max_cost / price
                if quantity <= 1e-8:
                    return None
                cost = quantity * price
                commission = cost * commission_rate
                total = cost + commission

            self.cash -= total
            pos = self.positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
            new_qty = pos["quantity"] + quantity
            pos["avg_price"] = (pos["quantity"] * pos["avg_price"] + quantity * price) / new_qty
            pos["quantity"] = new_qty
            self.positions[symbol] = pos
            return quantity, commission

        # sell
        pos = self.positions.get(symbol)
        if not pos or pos["quantity"] <= 1e-9:
            return None
        quantity = min(quantity, pos["quantity"])
        proceeds = quantity * price
        commission = proceeds * commission_rate
        self.cash += proceeds - commission
        pos["quantity"] -= quantity
        if pos["quantity"] <= 1e-9:
            pos["quantity"] = 0.0
            pos["avg_price"] = 0.0
        self.positions[symbol] = pos
        return quantity, commission

    def portfolio_value(self, current_prices):
        value = self.cash
        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol) or pos["avg_price"]
            value += pos["quantity"] * price
        return value
