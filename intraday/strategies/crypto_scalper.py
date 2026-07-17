from .base import IntradayStrategy
from ..indicators import ema

# The "2:1" comment this used to carry (0.8%/0.4%) only compared raw price
# moves — but the 0.52% round-trip Kraken fee (0.26% x2) hits both sides,
# not just the win: net win was +0.8-0.52=+0.28%, net loss was
# -0.4-0.52=-0.92%. Real R:R was ~0.30 inverted, needing a ~77% win rate
# just to break even, which an EMA5/12 crossover has no business hitting.
# Widened so the fee-adjusted math is sane: net win +2.0-0.52=+1.48%, net
# loss -0.8-0.52=-1.32%, R:R ~1.12, breakeven ~47%.
PROFIT_TARGET = 0.020    # +2.0% (net +1.48% after 0.52% round-trip fees)
STOP_LOSS = 0.008        # -0.8% (net -1.32% after fees)
POSITION_PCT = 0.10
MAX_POSITIONS = 5
MIN_CANDLES = 13         # ema12 needs a prior bar too, to detect the crossover


class CryptoScalper(IntradayStrategy):
    """EMA5/EMA12 crossover scalper on 1min candles."""

    def analyze(self, candles_by_symbol):
        signals = []
        open_positions = sum(1 for p in self.positions.values() if p["quantity"] > 1e-9)
        for symbol in self.symbols:
            candles = candles_by_symbol.get(symbol) or []
            if len(candles) < MIN_CANDLES:
                continue

            closes = [c["close"] for c in candles]
            volumes = [c["volume"] for c in candles]
            price = closes[-1]
            pos = self.get_position(symbol)

            if pos and pos["quantity"] > 0:
                change = (price - pos["avg_price"]) / pos["avg_price"]
                if change >= PROFIT_TARGET:
                    signals.append((symbol, "sell", pos["quantity"], price,
                                     f"take profit +{change * 100:.2f}%"))
                elif change <= -STOP_LOSS:
                    signals.append((symbol, "sell", pos["quantity"], price,
                                     f"stop loss {change * 100:.2f}%"))
                continue

            ema5 = ema(closes, 5)
            ema12 = ema(closes, 12)
            if ema5[-2] is None or ema12[-2] is None:
                continue

            crossed_up = ema5[-2] <= ema12[-2] and ema5[-1] > ema12[-1]
            recent = volumes[-6:-1]
            avg_volume = sum(recent) / len(recent) if recent else 0
            volume_confirm = volumes[-1] > avg_volume

            if crossed_up and volume_confirm and open_positions < MAX_POSITIONS:
                qty = (self.cash * POSITION_PCT) / price
                if qty > 0:
                    signals.append((symbol, "buy", qty, price,
                                     "EMA5 crossed above EMA12 with volume confirmation"))
                    open_positions += 1

        return signals
