import numpy as np
from .base import BaseStrategy


class BollingerBandsStrategy(BaseStrategy):
    """Buy at lower band, sell at upper band. Equal-weighted across a capped
    number of concurrent positions, sized +/-10% by how far price has
    breached the band (right at the band = -10%, deep breach = +10%).

    Change from the original: buying happens on *confirmation* — price
    closed below the lower band yesterday and closed back above it today —
    instead of on the raw touch. Buying the instant price hits the band is
    indistinguishable from buying into a falling knife; waiting one bar for
    the bounce to actually start costs a little entry price but filters out
    the trades that just keep falling through the band."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        period = config.get("period", 20)
        std_dev = config.get("std_dev", 2)
        max_positions = config.get("max_positions", 5)
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        symbols = config.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"])
        cash = bot["cash"]
        signals = []
        current_positions = len(bot.get("holdings", []))

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < period + 1:
                continue

            closes = df["Close"].values.astype(float)
            window_now = closes[-period:]
            window_prev = closes[-period - 1:-1]

            mid_now = np.mean(window_now)
            std_now = np.std(window_now, ddof=1)
            upper_now = mid_now + std_dev * std_now
            lower_now = mid_now - std_dev * std_now

            mid_prev = np.mean(window_prev)
            std_prev = np.std(window_prev, ddof=1)
            lower_prev = mid_prev - std_dev * std_prev

            price = float(closes[-1])
            price_prev = float(closes[-2])
            qty_held = self.get_holding_quantity(bot, symbol)

            if qty_held > 0:
                if self.atr_stop_triggered(bot, symbol, market_data, multiplier=atr_stop_mult):
                    signals.append((symbol, "sell", qty_held, price))
                    continue
                if price >= upper_now:
                    signals.append((symbol, "sell", qty_held, price))
                    continue

            elif current_positions < max_positions and cash > 0:
                confirmed_bounce = price_prev <= lower_prev and price > lower_now
                if confirmed_bounce:
                    band_half = std_dev * std_now
                    conviction = 0.5 if band_half == 0 else max(0.0, min(1.0, (lower_now - price_prev) / band_half))
                    alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
                    quantity = alloc / price
                    if quantity > 0:
                        signals.append((symbol, "buy", quantity, price))
                        cash -= alloc
                        current_positions += 1

        return signals
