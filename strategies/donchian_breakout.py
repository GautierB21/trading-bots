import numpy as np
from .base import BaseStrategy


class DonchianBreakoutStrategy(BaseStrategy):
    """Buy on a new N-day high (Donchian channel breakout), exit on a new
    M-day low — classic Turtle-style dual channel.

    Different entry logic from sma_crossover/momentum: it reacts to a fresh
    high being made *right now*, not to an already-established moving-average
    trend or a ranked past return. Low correlation to those despite being
    another "buy strength" strategy, because the trigger event is different."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        entry_period = config.get("entry_period", 55)
        exit_period = config.get("exit_period", 20)
        max_positions = config.get("max_positions", 5)
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        symbols = config.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"])
        cash = bot["cash"]
        signals = []
        current_positions = len(bot.get("holdings", []))

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < entry_period + 1:
                continue

            closes = df["Close"].values.astype(float)
            price = float(closes[-1])
            qty_held = self.get_holding_quantity(bot, symbol)

            if qty_held > 0:
                if self.atr_stop_triggered(bot, symbol, market_data, multiplier=atr_stop_mult):
                    signals.append((symbol, "sell", qty_held, price))
                    continue
                exit_low = float(np.min(closes[-(exit_period + 1):-1]))
                if price <= exit_low:
                    signals.append((symbol, "sell", qty_held, price))
                    continue

            elif current_positions < max_positions and cash > 0:
                entry_high = float(np.max(closes[-(entry_period + 1):-1]))
                if price > entry_high:
                    breakout_pct = (price - entry_high) / entry_high
                    conviction = max(0.0, min(1.0, breakout_pct / 0.02))  # 2%+ breakout = full conviction
                    alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
                    quantity = alloc / price
                    if quantity > 0:
                        signals.append((symbol, "buy", quantity, price))
                        cash -= alloc
                        current_positions += 1

        return signals
