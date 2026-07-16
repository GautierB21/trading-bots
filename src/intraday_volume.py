"""24h USD volume lookups for Kraken WS symbols, backed by the REST Ticker endpoint."""
import time
import urllib.request
import urllib.error
import json

KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"
CACHE_TTL_SECONDS = 300

# Kraken's REST Ticker accepts each pair's "altname" (e.g. XBTUSD, ADAUSD,
# 0GUSD) uniformly for every listing, so WS base + "USD" always resolves —
# no need to special-case the X/Z-prefixed internal pair names
# (XXBTZUSD, XXRPZUSD, ...) that show up in wsname/AssetPairs.
_cache = {}  # symbol -> (expires_at, volume_usd)


def _kraken_pair(symbol: str) -> str:
    base = symbol.split("/")[0]
    return f"{base}USD"


def get_24h_volume(symbol: str) -> float:
    """Returns 24h USD volume for a Kraken WS symbol like XBT/USD or 0G/USD.
    Cached for 5 minutes. Returns 0 if unknown."""
    now = time.time()
    cached = _cache.get(symbol)
    if cached and cached[0] > now:
        return cached[1]

    pair = _kraken_pair(symbol)
    try:
        url = f"{KRAKEN_TICKER_URL}?pair={pair}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return 0.0

    result = data.get("result") or {}
    if not result:
        _cache[symbol] = (now + CACHE_TTL_SECONDS, 0.0)
        return 0.0

    ticker = next(iter(result.values()))
    try:
        vwap_today = float(ticker["p"][0])
        volume_today = float(ticker["v"][0])
    except (KeyError, IndexError, ValueError, TypeError):
        _cache[symbol] = (now + CACHE_TTL_SECONDS, 0.0)
        return 0.0

    volume_usd = vwap_today * volume_today
    _cache[symbol] = (now + CACHE_TTL_SECONDS, volume_usd)
    return volume_usd
