from .base import BaseStrategy


class Reversal1DayStrategy(BaseStrategy):
    """Cross-sectional short-term reversal: rank the whole universe by
    yesterday's single-day return, buy the extreme-decline tail (likely
    overreaction, not a real repricing), hold a few days, exit.

    Distinct from rsi_reversion, which reacts to a multi-day oversold
    indicator on one symbol at a time — this trades a 1-day cross-sectional
    signal with a short, fixed hold, closer to microstructure overreaction
    than to RSI mean-reversion."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        max_positions = config.get("max_positions", 5)
        hold_days = config.get("hold_days", 3)
        min_decline_pct = config.get("min_decline_pct", 3.0)
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        symbols = config.get("symbols", [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "V", "JNJ", "WMT", "HD", "PG", "MA", "DIS",
            "BAC", "XOM", "CVX", "KO", "PEP",
        ])
        cash = bot["cash"]
        signals = []
        holdings = bot.get("holdings", [])
        current_positions = len(holdings)

        returns = {}
        prices = {}
        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < 2:
                continue
            closes = df["Close"].values.astype(float)
            ret = (closes[-1] - closes[-2]) / closes[-2] * 100
            returns[symbol] = ret
            prices[symbol] = float(closes[-1])

        # Exits: fixed hold period or ATR stop — independent of today's ranking
        for h in holdings:
            sym = h["symbol"]
            if sym not in prices:
                continue
            if self.atr_stop_triggered(bot, sym, market_data, multiplier=atr_stop_mult):
                signals.append((sym, "sell", h["quantity"], prices[sym]))
                current_positions -= 1
                continue
            held_days = self.days_held(bot, sym, market_data)
            if held_days is not None and held_days >= hold_days:
                signals.append((sym, "sell", h["quantity"], prices[sym]))
                current_positions -= 1

        held_symbols = {h["symbol"] for h in holdings}
        candidates = sorted(
            (s for s in returns if returns[s] <= -min_decline_pct and s not in held_symbols),
            key=lambda s: returns[s],
        )

        for sym in candidates:
            if current_positions >= max_positions or cash <= 0:
                break
            price = prices[sym]
            conviction = max(0.0, min(1.0, -returns[sym] / 10.0))
            alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
            quantity = alloc / price
            if quantity > 0:
                signals.append((sym, "buy", quantity, price))
                cash -= alloc
                current_positions += 1

        return signals
