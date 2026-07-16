from .base import IntradayStrategy

WATCH_CANDLES = 20
DECLINE_THRESHOLD = 0.03   # -3%
BOUNCE_CANDLES = 3         # look for bounce in last 3
TAKE_PROFIT = 0.02         # +2%
STOP_LOSS = 0.02           # -2%
TIME_EXIT = 10             # exit after 10 candles
POSITION_PCT = 0.10        # 10% of cash per position
MAX_POSITIONS = 5


class DipBuyer(IntradayStrategy):
    """Contrarian dip-buying: buy a ≥3% decline once a bounce confirms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bars_held = {}   # symbol -> candles since entry

    def analyze(self, candles_by_symbol):
        signals = []
        open_positions = sum(1 for p in self.positions.values() if p["quantity"] > 1e-9)

        for symbol in self.symbols:
            candles = candles_by_symbol.get(symbol) or []
            if len(candles) < WATCH_CANDLES:
                continue

            price = candles[-1]["close"]
            pos = self.get_position(symbol)

            if pos and pos["quantity"] > 0:
                self.bars_held[symbol] = self.bars_held.get(symbol, 0) + 1
                change = (price - pos["avg_price"]) / pos["avg_price"]

                if change >= TAKE_PROFIT:
                    signals.append((symbol, "sell", pos["quantity"], price,
                                     f"take profit +{change * 100:.2f}%"))
                    self.bars_held.pop(symbol, None)
                elif change <= -STOP_LOSS:
                    signals.append((symbol, "sell", pos["quantity"], price,
                                     f"stop loss {change * 100:.2f}%"))
                    self.bars_held.pop(symbol, None)
                elif self.bars_held.get(symbol, 0) >= TIME_EXIT:
                    signals.append((symbol, "sell", pos["quantity"], price,
                                     f"timeout after {TIME_EXIT} candles"))
                    self.bars_held.pop(symbol, None)
                continue

            if open_positions >= MAX_POSITIONS:
                continue

            window = candles[-WATCH_CANDLES:]
            window_high = max(c["high"] for c in window)
            decline = (window_high - price) / window_high
            if decline < DECLINE_THRESHOLD:
                continue

            last3 = window[-BOUNCE_CANDLES:]
            green_count = sum(1 for c in last3 if c["close"] > c["open"])
            last = last3[-1]
            prev_close = last3[-2]["close"]
            bounce_confirmed = (
                green_count >= 2
                and last["close"] > last["open"]
                and last["close"] > prev_close
            )
            if not bounce_confirmed:
                continue

            qty = (self.cash * POSITION_PCT) / price
            if qty > 0:
                signals.append((symbol, "buy", qty, price,
                                 f"-{decline * 100:.2f}% dip with bounce confirmed"))
                self.bars_held[symbol] = 0
                open_positions += 1

        return signals
