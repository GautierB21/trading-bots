from abc import ABC, abstractmethod
import numpy as np
import pandas as pd


class BaseStrategy(ABC):
    """Abstract base for all trading strategies.

    generate_signals returns list of (symbol, side, quantity, price) tuples.
    side is "buy" or "sell".
    """

    @abstractmethod
    def generate_signals(self, bot, market_data):
        """
        Args:
            bot: dict with keys id, name, strategy, capital, cash, config (parsed), holdings
            market_data: dict of symbol -> pandas DataFrame with OHLCV columns

        Returns:
            list of (symbol, side, quantity, price)
        """
        pass

    def get_holding_quantity(self, bot, symbol):
        for h in bot.get("holdings", []):
            if h["symbol"] == symbol:
                return h["quantity"]
        return 0.0

    def get_holding_avg_price(self, bot, symbol):
        for h in bot.get("holdings", []):
            if h["symbol"] == symbol:
                return h["avg_price"]
        return 0.0

    def portfolio_equity(self, bot, market_data):
        """Cash + mark-to-market value of current holdings. Used as the base
        for equal-weight position sizing instead of bot['cash'] alone, so
        sizing stays stable as equity grows/shrinks rather than just as
        remaining cash shrinks."""
        equity = bot["cash"]
        for h in bot.get("holdings", []):
            df = market_data.get(h["symbol"])
            if df is not None and not df.empty:
                price = float(df["Close"].dropna().values[-1])
            else:
                price = h.get("avg_price", 0.0)
            equity += h["quantity"] * price
        return equity

    def sized_allocation(self, bot, market_data, max_positions, conviction=0.5):
        """Target capital for one position: equity / max_positions, tilted
        +/-10% by conviction (0..1, 0.5 = neutral). Replaces the old
        '% of remaining cash' sizing, which collapsed to 1-3 concurrent
        positions regardless of how many symbols were in the universe."""
        equity = self.portfolio_equity(bot, market_data)
        base = equity / max_positions
        tilt = max(-1.0, min(1.0, (conviction - 0.5) * 2)) * 0.10
        return base * (1 + tilt)

    def compute_atr(self, df, period=14):
        """Average True Range. Uses High/Low/Close when available (yfinance
        equities); falls back to close-to-close absolute change when the
        source only has Close (CoinGecko crypto series) — a cruder but still
        volatility-scaled proxy."""
        closes = df["Close"].astype(float).values
        if len(closes) < period + 1:
            return None
        if "High" in df.columns and "Low" in df.columns:
            highs = df["High"].astype(float).values
            lows = df["Low"].astype(float).values
            prev_close = np.concatenate([[closes[0]], closes[:-1]])
            tr = np.maximum.reduce([highs - lows, np.abs(highs - prev_close), np.abs(lows - prev_close)])
        else:
            tr = np.abs(np.diff(closes, prepend=closes[0]))
        return float(np.mean(tr[-period:]))

    def atr_stop_triggered(self, bot, symbol, market_data, atr_period=14, multiplier=2.0):
        """Hard stop independent of the strategy's own exit signal: true once
        price has fallen more than multiplier*ATR below the position's entry
        price. None of these strategies previously had any loss floor other
        than 'wait for the opposite signal to fire', which may never happen."""
        qty_held = self.get_holding_quantity(bot, symbol)
        if qty_held <= 0:
            return False
        df = market_data.get(symbol)
        if df is None or df.empty:
            return False
        entry_price = self.get_holding_avg_price(bot, symbol)
        if entry_price <= 0:
            return False
        atr = self.compute_atr(df, atr_period)
        if atr is None:
            return False
        current_price = float(df["Close"].dropna().values[-1])
        return current_price <= entry_price - multiplier * atr

    def days_held(self, bot, symbol, market_data):
        """Days since the current position in symbol was opened, or None if
        not held / no entry_date recorded."""
        for h in bot.get("holdings", []):
            if h["symbol"] != symbol:
                continue
            entry_date = h.get("entry_date")
            if not entry_date:
                return None
            df = market_data.get(symbol)
            if df is None or df.empty:
                return None
            as_of = pd.Timestamp(df.index[-1]).normalize()
            entry_ts = pd.Timestamp(entry_date).normalize()
            return (as_of - entry_ts).days
        return None
