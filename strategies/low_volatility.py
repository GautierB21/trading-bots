import numpy as np
from .base import BaseStrategy


class LowVolatilityStrategy(BaseStrategy):
    """Buy the least-volatile quintile of the universe, equal-weighted,
    rebalanced every `rebalance_days` — the low-volatility anomaly (Ang et
    al.): low-vol stocks have historically delivered better risk-adjusted
    returns than high-vol/high-beta ones. The opposite bet from momentum,
    which chases the most volatile recent winners."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        lookback = config.get("lookback", 60)
        top_n = config.get("top_n", 5)
        rebalance_days = config.get("rebalance_days", 20)
        atr_stop_mult = config.get("atr_stop_mult", 3.0)  # wider: low-vol names shouldn't hit tight stops often
        symbols = config.get("symbols", [
            "AAPL", "MSFT", "GOOGL", "JNJ", "PG", "KO", "WMT", "PEP",
            "V", "MA", "HD", "MCD", "COST", "UNH", "ABBV",
        ])
        cash = bot["cash"]
        holdings = bot.get("holdings", [])
        current_positions = len(holdings)

        # Only rebalance the basket every `rebalance_days` — in between,
        # just manage the hard stop. Age is measured from the newest
        # position so a fresh add doesn't force an immediate re-rank.
        if holdings:
            ages = [self.days_held(bot, h["symbol"], market_data) for h in holdings]
            ages = [a for a in ages if a is not None]
            if ages and max(ages) < rebalance_days:
                exits = []
                for h in holdings:
                    sym = h["symbol"]
                    df = market_data.get(sym)
                    if df is None or df.empty:
                        continue
                    price = float(df["Close"].dropna().values[-1])
                    if self.atr_stop_triggered(bot, sym, market_data, multiplier=atr_stop_mult):
                        exits.append((sym, "sell", h["quantity"], price))
                return exits

        vols = {}
        prices = {}
        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < lookback + 1:
                continue
            closes = df["Close"].values.astype(float)
            window = closes[-(lookback + 1):]
            returns = np.diff(window) / window[:-1]
            vols[symbol] = float(np.std(returns, ddof=1))
            prices[symbol] = float(closes[-1])

        if not vols:
            return []

        ranked = sorted(vols.keys(), key=lambda s: vols[s])  # ascending: lowest vol first
        target = set(ranked[:top_n])
        held_symbols = {h["symbol"] for h in holdings}

        signals = []
        for h in holdings:
            sym = h["symbol"]
            if sym not in target and sym in prices:
                signals.append((sym, "sell", h["quantity"], prices[sym]))

        buy_targets = [s for s in target if s not in held_symbols and s in prices]
        for sym in buy_targets:
            if cash <= 0:
                break
            price = prices[sym]
            alloc = min(self.sized_allocation(bot, market_data, top_n, 0.5), cash)
            quantity = alloc / price
            if quantity > 0:
                signals.append((sym, "buy", quantity, price))
                cash -= alloc

        return signals
