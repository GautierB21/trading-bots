"""Earnings surprise data for strategies/pead.py.

yfinance first — free, no key, already a hard dependency of this whole
project, and Ticker.get_earnings_dates() already returns EPS estimate,
reported EPS, and surprise % pre-computed, with decent US/EU/Asia coverage
(verified against AAPL, MC.PA, SAP.DE, 7203.T, 005930.KS, 0700.HK).

Finnhub as a fallback (needs FINNHUB_API_KEY, free tier 60 calls/min) for
whatever yfinance doesn't have earnings history for.

FMP's /earnings-surprises endpoint (the original source here) returns 403
on this project's current FMP plan for every symbol tested, including
AAPL — not a coverage gap, the whole endpoint is blocked regardless of
symbol, hence the swap away from it.
"""
import os
import time
import requests
import yfinance as yf

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
FINNHUB_URL = "https://finnhub.io/api/v1/stock/earnings"

_CACHE_TTL = 86400  # 1 day — earnings surprises only change quarterly
_cache = {}  # symbol -> (fetched_at, result)


def _fetch_yfinance(symbol, limit):
    try:
        df = yf.Ticker(symbol).get_earnings_dates(limit=limit + 4)
    except Exception as e:
        print(f"[earnings] yfinance error for {symbol}: {e}")
        return None
    if df is None or df.empty:
        return None
    df = df.dropna(subset=["Reported EPS", "EPS Estimate"])
    if df.empty:
        return None

    rows = []
    for date, row in df.iterrows():
        estimate = float(row["EPS Estimate"])
        actual = float(row["Reported EPS"])
        surprise = row.get("Surprise(%)")
        surprise_pct = float(surprise) if surprise == surprise else (  # NaN check
            (actual - estimate) / abs(estimate) * 100 if estimate else None
        )
        rows.append({
            "date": date.date().isoformat(), "actual": actual,
            "estimate": estimate, "surprise_pct": surprise_pct,
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:limit] if rows else None


def _fetch_finnhub(symbol, limit):
    if not FINNHUB_API_KEY:
        return None
    try:
        resp = requests.get(
            FINNHUB_URL, params={"symbol": symbol, "token": FINNHUB_API_KEY}, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[earnings] Finnhub error for {symbol}: {e}")
        return None
    if not data or not isinstance(data, list):
        return None

    rows = []
    for r in data:
        actual = r.get("actual")
        estimate = r.get("estimate")
        date = r.get("period")
        if actual is None or estimate is None or not date:
            continue
        surprise_pct = r.get("surprisePercent")
        if surprise_pct is None and estimate:
            surprise_pct = (actual - estimate) / abs(estimate) * 100
        rows.append({"date": date, "actual": actual, "estimate": estimate, "surprise_pct": surprise_pct})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:limit] if rows else None


def fetch_earnings_surprises(symbol, limit=1):
    """Most recent earnings surprise(s), most recent first: list of
    {date, actual, estimate, surprise_pct}, or None if neither source has
    anything. Cached 1 day per symbol."""
    cached = _cache.get(symbol)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    result = _fetch_yfinance(symbol, limit)
    if not result:
        result = _fetch_finnhub(symbol, limit)

    _cache[symbol] = (time.time(), result)
    return result
