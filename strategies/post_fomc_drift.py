import datetime
import pandas as pd
from .base import BaseStrategy
from src.macro_calendar import is_macro_event_day


class PostFOMCDriftStrategy(BaseStrategy):
    """Post-announcement drift: markets have historically continued moving
    in the direction of their initial reaction to a Fed/ECB decision for
    several days afterward, rather than reverting immediately. Reacts to
    what the decision *did* to the market, not a prediction of what the
    decision *will be* — the engine is long-only, so it can only ride a
    positive reaction, never fade or short a negative one.

    Uses src/macro_calendar.py for event dates (see that file for why this
    can't be based on Fed Funds futures probabilities: no free feed for
    that is wired into the project)."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        symbols = config.get("symbols", ["SPY", "QQQ"])
        reaction_window_days = config.get("reaction_window_days", 1)
        min_reaction_pct = config.get("min_reaction_pct", 1.0)
        hold_days = config.get("hold_days", 5)
        max_positions = config.get("max_positions", len(symbols))
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        cash = bot["cash"]
        signals = []
        current_positions = len(bot.get("holdings", []))

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or len(df) < 2:
                continue
            closes = df["Close"].values.astype(float)
            price = float(closes[-1])
            qty_held = self.get_holding_quantity(bot, symbol)

            if qty_held > 0:
                if self.atr_stop_triggered(bot, symbol, market_data, multiplier=atr_stop_mult):
                    signals.append((symbol, "sell", qty_held, price))
                    continue
                held_days = self.days_held(bot, symbol, market_data)
                if held_days is not None and held_days >= hold_days:
                    signals.append((symbol, "sell", qty_held, price))
                continue

            if current_positions >= max_positions or cash <= 0:
                continue

            as_of = pd.Timestamp(df.index[-1]).date()
            recent_event = any(
                is_macro_event_day(as_of - datetime.timedelta(days=d))
                for d in range(reaction_window_days + 1)
            )
            if not recent_event:
                continue

            day_return = (closes[-1] - closes[-2]) / closes[-2] * 100
            if day_return < min_reaction_pct:
                continue  # long-only: no reaction, or a negative one, means no trade

            conviction = max(0.0, min(1.0, day_return / 3.0))
            alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
            quantity = alloc / price
            if quantity > 0:
                signals.append((symbol, "buy", quantity, price))
                cash -= alloc
                current_positions += 1
                print(f"[post_fomc_drift] {symbol}: +{day_return:.2f}% reaction near a macro event -> buy")

        return signals
