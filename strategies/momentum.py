import numpy as np
from .base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    """Buy top N performers by lookback return, equal-weighted with a
    +/-10% conviction tilt by relative return strength, sell everything else.

    Two changes from the original: (1) only symbols with a *positive*
    absolute return are eligible — ranking alone let a stock at -2% count as
    "top" during a broad selloff, which isn't a momentum signal, it's just
    "least bad"; (2) lookback 20d->60d, closer to the academic momentum
    window (20d is dominated by short-term noise/reversal)."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        lookback = config.get("lookback", 60)
        max_positions = config.get("max_positions", config.get("top_n", 5))
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        symbols = config.get("symbols", [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD",
            "DIS", "NFLX", "ADBE", "CRM", "INTC",
        ])
        cash = bot["cash"]
        signals = []

        returns = {}
        prices = {}
        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < lookback + 1:
                continue
            closes = df["Close"].values.astype(float)
            ret = (closes[-1] - closes[-(lookback + 1)]) / closes[-(lookback + 1)]
            returns[symbol] = ret
            prices[symbol] = float(closes[-1])

        if not returns:
            return signals

        ranked = sorted(returns.keys(), key=lambda s: returns[s], reverse=True)
        positive_ranked = [s for s in ranked if returns[s] > 0]
        top_symbols = set(positive_ranked[:max_positions])

        sold = set()
        # ATR stop: hard exit regardless of ranking
        for h in bot.get("holdings", []):
            sym = h["symbol"]
            if sym in prices and self.atr_stop_triggered(bot, sym, market_data, multiplier=atr_stop_mult):
                signals.append((sym, "sell", h["quantity"], prices[sym]))
                sold.add(sym)

        # Sell holdings that fell out of the top N (or have no positive momentum left)
        for h in bot.get("holdings", []):
            sym = h["symbol"]
            if sym in sold:
                continue
            if sym not in top_symbols and sym in prices:
                signals.append((sym, "sell", h["quantity"], prices[sym]))

        # Buy top N not already held, equal-weight tilted by relative return
        # strength within the top N (strongest = +10%, weakest = -10%)
        held_symbols = {h["symbol"] for h in bot.get("holdings", [])}
        buy_targets = [s for s in top_symbols if s not in held_symbols and s in prices]

        if buy_targets:
            top_returns = [returns[s] for s in top_symbols]
            r_min, r_max = min(top_returns), max(top_returns)
            r_range = r_max - r_min

            for sym in buy_targets:
                if cash <= 0:
                    break
                conviction = 0.5 if r_range == 0 else (returns[sym] - r_min) / r_range
                alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
                price = prices[sym]
                quantity = alloc / price
                if quantity > 0:
                    signals.append((sym, "buy", quantity, price))
                    cash -= alloc

        return signals
