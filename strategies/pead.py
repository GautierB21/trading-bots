import datetime
from .base import BaseStrategy
from src import earnings


class PEADStrategy(BaseStrategy):
    """Post-Earnings-Announcement Drift: buy stocks that just beat earnings
    estimates by a wide margin, hold for a fixed window, exit — the market
    is documented to systematically underreact to earnings surprises,
    drifting in the same direction for weeks after the report.

    Event-driven, not technical or price-pattern based — genuinely different
    signal source from every other strategy here. Data via src/earnings.py:
    yfinance first (free, no key, already used everywhere in this project),
    Finnhub as a fallback if FINNHUB_API_KEY is set. Not every symbol has
    analyst-estimate data on yfinance (LVMH doesn't, for one) — those just
    get skipped this run rather than crash."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        symbols = config.get("symbols", [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "JPM", "V", "JNJ", "WMT", "HD", "PG", "MA", "DIS",
        ])
        min_surprise_pct = config.get("min_surprise_pct", 5.0)
        max_days_since_earnings = config.get("max_days_since_earnings", 3)
        hold_days = config.get("hold_days", 30)
        max_positions = config.get("max_positions", 5)
        atr_stop_mult = config.get("atr_stop_mult", 2.5)
        cash = bot["cash"]
        signals = []
        current_positions = len(bot.get("holdings", []))
        today = datetime.date.today()

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or df.empty:
                continue
            price = float(df["Close"].dropna().values[-1])
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

            surprises = earnings.fetch_earnings_surprises(symbol, limit=1)
            if not surprises:
                continue
            latest = surprises[0]
            if latest["surprise_pct"] is None or latest["surprise_pct"] < min_surprise_pct:
                continue

            try:
                report_date = datetime.date.fromisoformat(latest["date"][:10])
            except ValueError:
                continue
            days_since = (today - report_date).days
            if days_since < 0 or days_since > max_days_since_earnings:
                continue  # drift window already missed, or bad/future-dated data

            conviction = max(0.0, min(1.0, latest["surprise_pct"] / 20.0))
            alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
            quantity = alloc / price
            if quantity > 0:
                signals.append((symbol, "buy", quantity, price))
                cash -= alloc
                current_positions += 1
                print(f"[pead] {symbol}: +{latest['surprise_pct']:.1f}% surprise "
                      f"{days_since}d ago -> buy")

        return signals
