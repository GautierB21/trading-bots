from .base import BaseStrategy
from src.rates import get_rate_trend

SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]

# Classic rate-sensitivity split: defensives (staples, utilities, health
# care) hold up when rates rise because their cash flows are steady and
# bond-like; richly-valued growth sectors get hurt more since more of their
# value sits in far-out earnings, discounted harder at a higher rate.
DEFENSIVE_SECTORS = {"XLP", "XLU", "XLV"}
GROWTH_SECTORS = {"XLK", "XLY", "XLC"}


class SectorRotationStrategy(BaseStrategy):
    """Rank US sector SPDR ETFs (tech, financials, energy, ...) by relative
    momentum, overweight the strongest few.

    Same ranked-momentum mechanics as strategies/momentum.py, but the axis
    of the bet is different: which *sector* is leading, not which *stock*.
    A genuinely different diversification source from every other
    stock-picking strategy here — it's a portfolio-allocation call, not
    security selection, even though the code looks similar.

    Tilted by the 10-year yield trend (src/rates.py): rising rates nudge
    the ranking toward defensives and away from growth, falling rates do
    the opposite. This only shifts the ranking, it doesn't override pure
    momentum — a sector still needs real relative strength to make the cut."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        lookback = config.get("lookback", 60)
        top_n = config.get("top_n", 3)
        atr_stop_mult = config.get("atr_stop_mult", 2.5)
        rate_tilt_pct = config.get("rate_tilt_pct", 0.03)  # +/-3pp added to ranked return
        symbols = config.get("symbols", SECTOR_ETFS)
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

        rate_trend = get_rate_trend()
        if rate_trend == "rising":
            tilt_up, tilt_down = DEFENSIVE_SECTORS, GROWTH_SECTORS
        elif rate_trend == "falling":
            tilt_up, tilt_down = GROWTH_SECTORS, DEFENSIVE_SECTORS
        else:
            tilt_up, tilt_down = set(), set()
        for sym in returns:
            if sym in tilt_up:
                returns[sym] += rate_tilt_pct
            elif sym in tilt_down:
                returns[sym] -= rate_tilt_pct

        ranked = sorted(returns.keys(), key=lambda s: returns[s], reverse=True)
        top = set(ranked[:top_n])
        holdings = bot.get("holdings", [])

        sold = set()
        for h in holdings:
            sym = h["symbol"]
            if sym in prices and self.atr_stop_triggered(bot, sym, market_data, multiplier=atr_stop_mult):
                signals.append((sym, "sell", h["quantity"], prices[sym]))
                sold.add(sym)

        for h in holdings:
            sym = h["symbol"]
            if sym in sold:
                continue
            if sym not in top and sym in prices:
                signals.append((sym, "sell", h["quantity"], prices[sym]))

        held_symbols = {h["symbol"] for h in holdings}
        buy_targets = [s for s in top if s not in held_symbols and s in prices]
        for sym in buy_targets:
            if cash <= 0:
                break
            alloc = min(self.sized_allocation(bot, market_data, top_n, 0.5), cash)
            price = prices[sym]
            quantity = alloc / price
            if quantity > 0:
                signals.append((sym, "buy", quantity, price))
                cash -= alloc

        return signals
