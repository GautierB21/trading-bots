"""Interest-rate regime signals from free Treasury yield tickers on
yfinance (^TNX = 10-year, ^IRX = 13-week/~3-month) — the closest free,
reliable proxy this project has to "what does the market expect the Fed to
do." Fed Funds futures (CME FedWatch) would give an actual probability-
weighted rate path, but there's no free, reliable feed for that wired into
this project. Yield levels are blunter — they react to realized data and
Fed communication rather than pricing a clean probability distribution —
but they move ahead of meetings and react immediately to decisions, which
is enough for a regime filter (rising vs falling, inverted vs normal curve).
"""
import time
from src.data_fetcher import fetch_historical_data

_CACHE_TTL = 6 * 3600  # 6h — a regime filter doesn't need per-minute freshness
_cache = {}  # ticker -> (fetched_at, close_series)


def _get_yield_series(ticker, period="6mo"):
    cached = _cache.get(ticker)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    data = fetch_historical_data([ticker], period=period, interval="1d")
    df = data.get(ticker)
    series = df["Close"].dropna() if df is not None and not df.empty else None
    _cache[ticker] = (time.time(), series)
    return series


def get_yield_curve_spread():
    """10-year minus 13-week yield, in percentage points. Negative means the
    curve is inverted — short-term rates paying more than long-term, which
    has historically preceded recessions by 6-18 months. None if data is
    unavailable."""
    tnx = _get_yield_series("^TNX")
    irx = _get_yield_series("^IRX")
    if tnx is None or irx is None or tnx.empty or irx.empty:
        return None
    return float(tnx.iloc[-1]) - float(irx.iloc[-1])


def is_yield_curve_inverted():
    spread = get_yield_curve_spread()
    return spread is not None and spread < 0


def get_rate_trend(lookback_days=20):
    """'rising', 'falling', or None (flat/unavailable) — direction of the
    10-year yield over the last `lookback_days` trading days. A move under
    5bps is treated as noise, not a trend."""
    tnx = _get_yield_series("^TNX")
    if tnx is None or len(tnx) < lookback_days + 1:
        return None
    change = float(tnx.iloc[-1]) - float(tnx.iloc[-(lookback_days + 1)])
    if abs(change) < 0.05:
        return None
    return "rising" if change > 0 else "falling"
