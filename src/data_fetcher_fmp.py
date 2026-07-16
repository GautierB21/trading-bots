"""Financial Modeling Prep data source. Replaces Alpha Vantage for fundamentals.

Why swap: Alpha Vantage's OVERVIEW endpoint barely covers non-US tickers
(FR/DE/UK symbols routinely return empty), and its free tier caps at 25
calls/day with a 12s-per-call throttle. FMP's free tier is 250 calls/day,
no artificial per-call delay, and covers Euronext/Xetra/LSE tickers used
across fundamental/lesechos_news/pairs_trading.

Everything here is a no-op (returns None / is_available() == False) when
FMP_API_KEY is not set, so callers can always fall back to Alpha Vantage or
yfinance.
"""
import os
import time
import requests

FMP_API_KEY = os.environ.get("FMP_API_KEY")
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
MIN_CALL_INTERVAL = 0.25  # free tier has no documented per-second cap; stay polite
MAX_WAIT = 10

_LAST_CALL_TIME = 0


def is_available():
    return bool(FMP_API_KEY)


def _rate_limit():
    global _LAST_CALL_TIME
    elapsed = time.time() - _LAST_CALL_TIME
    wait = MIN_CALL_INTERVAL - elapsed
    if wait <= 0:
        return True
    if wait > MAX_WAIT:
        return False
    time.sleep(wait)
    return True


def _get(path, params=None):
    if not FMP_API_KEY:
        return None
    if not _rate_limit():
        return None
    global _LAST_CALL_TIME
    try:
        resp = requests.get(
            f"{FMP_BASE_URL}/{path}",
            params={**(params or {}), "apikey": FMP_API_KEY},
            timeout=15,
        )
        _LAST_CALL_TIME = time.time()
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[data_fetcher_fmp] request error: {e}")
        return None
    if not data or (isinstance(data, dict) and "Error Message" in data):
        return None
    return data


def fetch_fundamentals(symbol):
    """Combines /profile (market cap) + /ratios-ttm (PE, ROE, debt/equity).
    Returns dict matching data_fetcher_alpha.fetch_fundamentals's shape, or None.
    """
    profile = _get(f"profile/{symbol}")
    if not profile or not isinstance(profile, list) or not profile:
        return None
    p = profile[0]
    market_cap = p.get("mktCap")
    sector = p.get("sector")

    ratios = _get(f"ratios-ttm/{symbol}")
    pe_ratio = roe = debt_to_equity = None
    if ratios and isinstance(ratios, list) and ratios:
        r = ratios[0]
        pe_ratio = r.get("peRatioTTM")
        roe = r.get("returnOnEquityTTM")
        debt_to_equity = r.get("debtEquityRatioTTM")

    if market_cap is None and pe_ratio is None:
        return None

    return {
        "pe_ratio": pe_ratio,
        "market_cap": market_cap,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "sector": sector,
    }
