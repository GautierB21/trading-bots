import numpy as np
import pandas as pd
from .base import BaseStrategy

CONVICTION_SCALE = 0.05  # 5% fast/slow SMA spread maps to full conviction


def compute_adx(df, period=14):
    """Trend-strength filter for the crossover — classic SMA crossover's
    weakness is whipsawing in a sideways/choppy market with no real trend.
    Needs High/Low; returns None (treated as "no filter, allow the trade")
    for Close-only sources like the CoinGecko crypto series."""
    if "High" not in df.columns or "Low" not in df.columns:
        return None
    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    closes = df["Close"].values.astype(float)
    if len(closes) < period * 2:
        return None

    up_move = np.diff(highs)
    down_move = -np.diff(lows)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    prev_close = closes[:-1]
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - prev_close),
        np.abs(lows[1:] - prev_close),
    ])

    atr = pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().values
    atr_safe = np.where(atr == 0, np.nan, atr)
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1 / period, adjust=False).mean().values / atr_safe
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1 / period, adjust=False).mean().values / atr_safe
    di_sum = plus_di + minus_di
    dx = np.where(di_sum == 0, 0.0, 100 * np.abs(plus_di - minus_di) / np.where(di_sum == 0, np.nan, di_sum))
    adx = pd.Series(dx).ewm(alpha=1 / period, adjust=False).mean().values
    val = adx[-1]
    return float(val) if np.isfinite(val) else None


class SMACrossoverStrategy(BaseStrategy):
    """Buy when fast SMA crosses above slow SMA, sell on cross below.
    Equal-weighted across a capped number of concurrent positions, sized
    +/-10% by how wide the crossover gap is.

    Two changes from the original: (1) ADX(14) > 20 gate — only takes the
    crossover when the market is actually trending, skipping the chop where
    crossovers whipsaw; (2) one-bar confirmation — a cross is acted on the
    day *after* it happens, and only if the fast SMA is still above the slow
    SMA (i.e. it didn't immediately reverse)."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        fast = config.get("fast_period", 20)
        slow = config.get("slow_period", 50)
        max_positions = config.get("max_positions", 5)
        adx_threshold = config.get("adx_threshold", 25)
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        symbols = config.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"])
        cash = bot["cash"]
        signals = []
        current_positions = len(bot.get("holdings", []))

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < slow + 2:
                continue

            closes = df["Close"].values
            if len(closes) < slow + 2:
                continue

            fast_sma_now = np.mean(closes[-fast:])
            fast_sma_prev = np.mean(closes[-(fast + 1):-1])
            fast_sma_2ago = np.mean(closes[-(fast + 2):-2])
            slow_sma_now = np.mean(closes[-slow:])
            slow_sma_prev = np.mean(closes[-(slow + 1):-1])
            slow_sma_2ago = np.mean(closes[-(slow + 2):-2])

            price = float(closes[-1])
            qty_held = self.get_holding_quantity(bot, symbol)

            crossed_below = fast_sma_prev >= slow_sma_prev and fast_sma_now < slow_sma_now

            if qty_held > 0:
                if self.atr_stop_triggered(bot, symbol, market_data, multiplier=atr_stop_mult):
                    signals.append((symbol, "sell", qty_held, price))
                    continue
                if crossed_below:
                    signals.append((symbol, "sell", qty_held, price))
                    continue

            elif current_positions < max_positions and cash > 0:
                crossed_above_yesterday = fast_sma_2ago <= slow_sma_2ago and fast_sma_prev > slow_sma_prev
                still_above = fast_sma_now > slow_sma_now
                if crossed_above_yesterday and still_above:
                    adx = compute_adx(df)
                    if adx is not None and adx < adx_threshold:
                        continue  # crossover confirmed but market isn't trending
                    spread_pct = (fast_sma_now - slow_sma_now) / slow_sma_now
                    conviction = max(0.0, min(1.0, spread_pct / CONVICTION_SCALE))
                    alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
                    quantity = alloc / price
                    if quantity > 0:
                        signals.append((symbol, "buy", quantity, price))
                        cash -= alloc
                        current_positions += 1

        return signals
