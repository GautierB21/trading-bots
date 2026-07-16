from .base import BaseStrategy


class DCAStrategy(BaseStrategy):
    """Dollar-cost average: buy fixed amount per symbol each run."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        amount_per_period = config.get("amount_per_period", 100)
        symbols = config.get("symbols", ["SPY", "QQQ"])
        max_position = config.get("max_position", 10)
        cash = bot["cash"]
        signals = []

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) == 0:
                continue

            price = float(df["Close"].values[-1])
            qty_held = self.get_holding_quantity(bot, symbol)

            if qty_held >= max_position:
                continue

            if cash < amount_per_period:
                continue

            quantity = amount_per_period / price
            signals.append((symbol, "buy", quantity, price))
            cash -= amount_per_period

        return signals
