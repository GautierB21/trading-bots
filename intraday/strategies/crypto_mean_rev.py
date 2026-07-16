from .base import IntradayStrategy
from ..indicators import rsi

OVERSOLD = 25
OVERBOUGHT = 70
PROFIT_TARGET = 0.008   # +0.8%
POSITION_PCT = 0.10
MAX_POSITIONS = 8
RSI_PERIOD = 14


class CryptoMeanRev(IntradayStrategy):
    """RSI(14) mean reversion on 5min candles across volatile altcoins."""

    def analyze(self, candles_by_symbol):
        signals = []
        open_positions = sum(1 for p in self.positions.values() if p["quantity"] > 1e-9)

        for symbol in self.symbols:
            candles = candles_by_symbol.get(symbol) or []
            if len(candles) < RSI_PERIOD + 1:
                continue

            closes = [c["close"] for c in candles]
            price = closes[-1]
            r = rsi(closes, RSI_PERIOD)
            if r is None:
                continue

            pos = self.get_position(symbol)
            if pos and pos["quantity"] > 0:
                change = (price - pos["avg_price"]) / pos["avg_price"]
                if r > OVERBOUGHT or change >= PROFIT_TARGET:
                    signals.append((symbol, "sell", pos["quantity"], price,
                                     f"RSI {r:.1f} overbought or +{change * 100:.2f}%"))
                continue

            if r < OVERSOLD and open_positions < MAX_POSITIONS:
                qty = (self.cash * POSITION_PCT) / price
                if qty > 0:
                    signals.append((symbol, "buy", qty, price, f"RSI {r:.1f} oversold"))
                    open_positions += 1

        return signals
