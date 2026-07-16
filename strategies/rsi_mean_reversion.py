import numpy as np
from .base import BaseStrategy


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class RSIMeanReversionStrategy(BaseStrategy):
    """Buy on oversold RSI, sell on overbought RSI. Equal-weighted across a
    capped number of concurrent positions, sized +/-10% by how deep the RSI
    signal is (right at the threshold = -10%, deeply oversold = +10%).

    Three changes from the original: (1) trend filter — only buys an oversold
    dip when price is above its own 200d SMA (buying the dip in an uptrend,
    not a falling knife in a structural downtrend); requires >=200 bars of
    history, so thin-history symbols simply don't qualify; (2) max holding
    period — if RSI never recovers to overbought, exit anyway after
    max_hold_days rather than holding indefinitely; (3) ATR hard stop."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        period = config.get("period", 14)
        oversold = config.get("oversold", 35)
        overbought = config.get("overbought", 65)
        max_positions = config.get("max_positions", 5)
        max_hold_days = config.get("max_hold_days", 15)
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        symbols = config.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"])
        cash = bot["cash"]
        signals = []
        current_positions = len(bot.get("holdings", []))

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < period + 2:
                continue

            closes = df["Close"].values.astype(float)
            rsi = compute_rsi(closes, period)
            if rsi is None:
                continue

            price = float(closes[-1])
            qty_held = self.get_holding_quantity(bot, symbol)

            if qty_held > 0:
                held_days = self.days_held(bot, symbol, market_data)
                if self.atr_stop_triggered(bot, symbol, market_data, multiplier=atr_stop_mult):
                    signals.append((symbol, "sell", qty_held, price))
                    continue
                if rsi > overbought:
                    signals.append((symbol, "sell", qty_held, price))
                    continue
                if held_days is not None and held_days >= max_hold_days:
                    signals.append((symbol, "sell", qty_held, price))
                    continue

            elif rsi < oversold and current_positions < max_positions and cash > 0:
                if len(closes) < 200:
                    continue  # not enough history to confirm the trend filter
                sma200 = float(np.mean(closes[-200:]))
                if price <= sma200:
                    continue  # falling knife, not a dip-in-uptrend
                conviction = max(0.0, min(1.0, (oversold - rsi) / oversold))
                alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
                quantity = alloc / price
                if quantity > 0:
                    signals.append((symbol, "buy", quantity, price))
                    cash -= alloc
                    current_positions += 1

        return signals
