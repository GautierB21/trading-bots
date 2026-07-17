from .base import IntradayStrategy

TOP_N = 5
POSITION_PCT = 0.12
STOP_LOSS = 0.03  # -3% hard floor — ranking-only exit means a symbol that
                   # crashes but drags the whole top-N down with it (a
                   # correlated market-wide selloff) never drops out of the
                   # top-N and never gets sold; this is the only price-based
                   # exit this strategy has.


class CryptoMomentum(IntradayStrategy):
    """Compares 15min returns across all crypto symbols; holds only the top-N."""

    def analyze(self, candles_by_symbol):
        signals = []
        returns = {}
        prices = {}

        for symbol in self.symbols:
            candles = candles_by_symbol.get(symbol) or []
            if len(candles) < 2:
                continue
            first_open = candles[0]["open"]
            last_close = candles[-1]["close"]
            if not first_open:
                continue
            returns[symbol] = (last_close - first_open) / first_open
            prices[symbol] = last_close

        if not returns:
            return signals

        ranked = sorted(returns.items(), key=lambda kv: kv[1], reverse=True)
        top = {sym for sym, _ in ranked[:TOP_N]}

        # Stop loss, independent of ranking.
        for symbol, pos in self.positions.items():
            if pos["quantity"] <= 1e-9 or symbol not in prices:
                continue
            change = (prices[symbol] - pos["avg_price"]) / pos["avg_price"]
            if change <= -STOP_LOSS:
                signals.append((symbol, "sell", pos["quantity"], prices[symbol],
                                 f"stop loss {change * 100:.2f}%"))

        stopped_out = {s[0] for s in signals}

        # Sell anything no longer in the top performers.
        for symbol, pos in self.positions.items():
            if symbol in stopped_out:
                continue
            if pos["quantity"] > 1e-9 and symbol not in top:
                price = prices.get(symbol, pos["avg_price"])
                signals.append((symbol, "sell", pos["quantity"], price,
                                 "dropped out of top performers"))

        # Buy into top performers not already held.
        for symbol in top:
            pos = self.get_position(symbol)
            if not pos or pos["quantity"] <= 1e-9:
                price = prices[symbol]
                qty = (self.cash * POSITION_PCT) / price
                if qty > 0:
                    signals.append((symbol, "buy", qty, price,
                                     f"top performer {returns[symbol] * 100:+.2f}% over {self.timeframe}min"))

        return signals
