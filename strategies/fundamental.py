import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import yfinance as yf
from .base import BaseStrategy
from src import data_fetcher_alpha as alpha
from src import data_fetcher_fmp as fmp

_INFO_CACHE_TTL = 3600  # seconds
_info_cache = {}  # symbol -> (fetched_at, info dict or None)
_PREFETCH_WORKERS = 8

MIN_SECTOR_PEERS = 3  # need at least this many same-sector symbols to trust a sector median
SECTOR_PE_CEILING_MULT = 1.3  # a stock's PE can run up to 1.3x its sector median


def _fetch_info(symbol):
    try:
        return yf.Ticker(symbol).info
    except Exception:
        return None


def _get_info(symbol):
    """yf.Ticker(...).info is a live snapshot, not a historical time series —
    a backtest calls generate_signals once per simulated day (~250x/year),
    which without caching means ~250 identical network calls per symbol and
    reliably times out. Cache it; a live daily cron run naturally spaces
    calls far enough apart that the TTL still refreshes."""
    cached = _info_cache.get(symbol)
    if cached and time.time() - cached[0] < _INFO_CACHE_TTL:
        return cached[1]
    info = _fetch_info(symbol)
    _info_cache[symbol] = (time.time(), info)
    return info


def _prefetch_infos(symbols):
    """Fill the cache for every symbol not already warm, concurrently. A cold
    cache means one real yf.Ticker(...).info network call per symbol — fetched
    sequentially that's minutes for a few dozen symbols (each call is 0.5-2s),
    comfortably past a reverse-proxy's request timeout. Threaded because this
    is pure network I/O (releases the GIL), same as yf.download(threads=True)
    elsewhere in this codebase."""
    now = time.time()
    missing = [s for s in symbols if not (
        (c := _info_cache.get(s)) and now - c[0] < _INFO_CACHE_TTL
    )]
    if not missing:
        return
    with ThreadPoolExecutor(max_workers=_PREFETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch_info, s): s for s in missing}
        for fut in as_completed(futures):
            symbol = futures[fut]
            _info_cache[symbol] = (time.time(), fut.result())


class FundamentalStrategy(BaseStrategy):
    """Buy fundamentally strong stocks, sell when they get expensive.

    PE screening is sector-relative, not an absolute 5-25 band: a fixed
    ceiling of 25 structurally excludes most of tech (routinely >25 PE) while
    over-weighting sectors that are cheap for structural reasons (EU
    banks/utilities). A sector's own median PE (computed across whatever's in
    the current universe, min 3 peers to trust it) is a fairer bar; falls
    back to the absolute band when sector data or peer count is unavailable."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        symbols = config.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"])
        min_market_cap = config.get("min_market_cap", 10_000_000_000)
        max_pe_ratio = config.get("max_pe_ratio", 25)
        min_pe_ratio = config.get("min_pe_ratio", 5)
        min_roe = config.get("min_roe", 10)
        max_debt_to_equity = config.get("max_debt_to_equity", 1.5)
        position_size_pct = config.get("position_size_pct", 0.7)
        max_positions = config.get("max_positions", 5)
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        cash = bot["cash"]
        signals = []
        current_positions = len(bot.get("holdings", []))
        use_fmp = fmp.is_available() and not bot.get("is_backtest")
        use_alpha = alpha.is_available() and not bot.get("is_backtest")

        if not use_fmp and not use_alpha:
            _prefetch_infos(symbols)

        # --- pass 1: gather fundamentals for the whole universe ---
        fundamentals = {}
        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or df.empty:
                continue
            price = float(df["Close"].dropna().values[-1])

            provider_data = fmp.fetch_fundamentals(symbol) if use_fmp else None
            source = "fmp"
            if provider_data is None and use_alpha:
                provider_data = alpha.fetch_fundamentals(symbol)
                source = "alpha_vantage"

            if provider_data is not None:
                pe_ratio = provider_data["pe_ratio"]
                market_cap = provider_data["market_cap"]
                roe = provider_data["roe"]
                roe = roe * 100 if roe is not None else None
                debt_to_equity = provider_data["debt_to_equity"]
                sector = provider_data.get("sector")
            else:
                info = _get_info(symbol)
                if not info:
                    continue
                source = "yfinance"
                pe_ratio = info.get("trailingPE")
                market_cap = info.get("marketCap")
                roe = info.get("returnOnEquity")
                roe = roe * 100 if roe is not None else None
                debt_to_equity = info.get("debtToEquity")
                sector = info.get("sector")

            fundamentals[symbol] = {
                "price": price, "pe_ratio": pe_ratio, "market_cap": market_cap,
                "roe": roe, "debt_to_equity": debt_to_equity, "sector": sector,
                "source": source,
            }

        # sector median PE across today's universe
        sector_pes = {}
        for f in fundamentals.values():
            if f["sector"] and f["pe_ratio"] is not None and f["pe_ratio"] > 0:
                sector_pes.setdefault(f["sector"], []).append(f["pe_ratio"])
        sector_median_pe = {
            sec: float(np.median(vals)) for sec, vals in sector_pes.items() if len(vals) >= MIN_SECTOR_PEERS
        }

        # --- pass 2: screen and generate signals ---
        for symbol, f in fundamentals.items():
            price = f["price"]
            pe_ratio = f["pe_ratio"]
            market_cap = f["market_cap"]
            roe = f["roe"]
            debt_to_equity = f["debt_to_equity"]
            sector = f["sector"]

            sector_median = sector_median_pe.get(sector)
            if sector_median is not None:
                pe_ceiling = sector_median * SECTOR_PE_CEILING_MULT
            else:
                pe_ceiling = max_pe_ratio

            print(
                f"[fundamental] {symbol}: source={f['source']} sector={sector} pe={pe_ratio} "
                f"pe_ceiling={pe_ceiling:.1f} market_cap={market_cap} roe={roe} debt_to_equity={debt_to_equity}"
            )

            qty_held = self.get_holding_quantity(bot, symbol)

            if qty_held > 0 and self.atr_stop_triggered(bot, symbol, market_data, multiplier=atr_stop_mult):
                signals.append((symbol, "sell", qty_held, price))
                continue

            meets_pe = pe_ratio is not None and min_pe_ratio <= pe_ratio <= pe_ceiling
            meets_cap = market_cap is not None and market_cap >= min_market_cap
            meets_roe = roe is None or roe >= min_roe
            meets_debt = debt_to_equity is None or debt_to_equity <= max_debt_to_equity

            if (
                qty_held == 0 and meets_pe and meets_cap and meets_roe and meets_debt
                and cash > 0 and current_positions < max_positions
            ):
                buy_amount = cash * position_size_pct
                quantity = buy_amount / price
                if quantity > 0:
                    signals.append((symbol, "buy", quantity, price))
                    cash -= buy_amount
                    current_positions += 1

            elif qty_held > 0 and pe_ratio is not None and pe_ratio > pe_ceiling * 2:
                signals.append((symbol, "sell", qty_held, price))

        return signals
