import os
import json
import time
import hashlib
import numpy as np
import pandas as pd
import yfinance as yf

try:
    from src.coingecko_client import (
        get_top_coins, get_coin_id_from_symbol, get_market_chart,
        is_available as cg_available,
    )
    HAS_COINGECKO = True
except ImportError:
    HAS_COINGECKO = False

# periods that need a real indicator/backtest window, not just "the current
# price" — these trigger a historical market_chart fetch per symbol instead
# of the cheap single-snapshot top_coins call.
DEEP_HISTORY_PERIODS = {"3mo", "6mo", "1y", "2y", "max"}
CG_MAX_HISTORY_DAYS = 365  # free tier cap

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cache")
CACHE_TTL = 3600  # seconds — refresh market data after 1 hour
MAX_SYMBOLS_PER_BATCH = 200  # yfinance can download many at once but may time out beyond this


def _cache_path(key):
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.csv")


def _meta_path(key):
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.meta.json")


def _is_cache_valid(key):
    mp = _meta_path(key)
    if not os.path.exists(mp):
        return False
    with open(mp) as f:
        meta = json.load(f)
    return time.time() - meta.get("timestamp", 0) < CACHE_TTL


def _load_cache(key):
    return pd.read_csv(_cache_path(key), index_col=0, parse_dates=True)


def _save_cache(key, df):
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(_cache_path(key))
    with open(_meta_path(key), "w") as f:
        json.dump({"timestamp": time.time()}, f)


def _cg_fetch(symbols):
    """Fetch crypto prices from CoinGecko instead of yfinance.
    Returns dict of symbol -> DataFrame with Close column.
    Falls back to yfinance for non-crypto symbols.
    """
    if not HAS_COINGECKO or not cg_available():
        return {}
    
    result = {}
    # Separate crypto vs non-crypto symbols
    crypto_syms = [s for s in symbols if s.endswith("-USD")] if isinstance(symbols, list) else []
    
    if not crypto_syms:
        return result
    
    # Get top 100 coins from CoinGecko
    try:
        coins = get_top_coins(100)
        coin_by_symbol = {c["symbol"]: c for c in coins if c.get("current_price")}
        
        for sym in crypto_syms:
            if sym in coin_by_symbol:
                c = coin_by_symbol[sym]
                price = c["current_price"]
                if price and price > 0:
                    # Create a minimal DataFrame with Close column
                    df = pd.DataFrame({
                        "Close": [float(price)],
                    }, index=pd.DatetimeIndex([pd.Timestamp.now()]))
                    result[sym] = df
    except Exception as e:
        print(f"[data_fetcher] CoinGecko error: {e}")
    
    return result


def fetch_historical_data(symbols, period="1y", interval="1d", allow_stale=False):
    """Return dict of symbol -> DataFrame with OHLCV columns.

    allow_stale=True serves whatever's on disk regardless of the 1h TTL
    (only symbols with no cache file at all trigger a live fetch) — for
    request paths like the bots list, where a page load blocking on a live
    fetch across hundreds of symbols is worse than showing a price that's a
    few hours old. Backtests and anything accuracy-sensitive should leave
    this False."""
    if isinstance(symbols, str):
        symbols = [symbols]

    result = {}
    to_download = []

    # Separate crypto symbols (use CoinGecko) from the rest (use yfinance)
    crypto_symbols = [s for s in symbols if s.endswith("-USD")]
    non_crypto_symbols = [s for s in symbols if not s.endswith("-USD")]

    def _cached(sym):
        key = f"{sym}_{period}_{interval}"
        has_cache = os.path.exists(_cache_path(key))
        if allow_stale and has_cache:
            try:
                return _load_cache(key)
            except Exception:
                return None
        if not allow_stale and _is_cache_valid(key):
            try:
                return _load_cache(key)
            except Exception:
                return None
        return None

    # Fetch crypto from CoinGecko (cached on disk same as yfinance results)
    crypto_to_fetch = []
    for sym in crypto_symbols:
        cached = _cached(sym)
        if cached is not None:
            result[sym] = cached
        else:
            crypto_to_fetch.append(sym)

    if crypto_to_fetch and period in DEEP_HISTORY_PERIODS:
        # Indicator/backtest callers need an actual daily series (RSI,
        # SMA crossover, momentum lookback, backtest common_index all need
        # >1 row) — the old code cached a single "now" price under the same
        # key every symbol used, which silently made every crypto ticker
        # unusable for any of that (a 1-row df can't satisfy a 14-50 day
        # lookback, and collapses backtest date-intersection to ~0 rows).
        for sym in crypto_to_fetch:
            coin_id = get_coin_id_from_symbol(sym)
            if not coin_id:
                continue
            prices = get_market_chart(coin_id, days=CG_MAX_HISTORY_DAYS)
            if not prices:
                continue
            df = pd.DataFrame(prices, columns=["ts", "Close"])
            df.index = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
            df = df[["Close"]]
            df = df[~df.index.duplicated(keep="last")]
            if not df.empty:
                result[sym] = df
                _save_cache(f"{sym}_{period}_{interval}", df)
    elif crypto_to_fetch:
        try:
            coins = get_top_coins(200)
            coin_by_symbol = {c["symbol"]: c for c in coins if c.get("current_price")}
            now = pd.Timestamp.now()
            for sym in crypto_to_fetch:
                if sym in coin_by_symbol:
                    c = coin_by_symbol[sym]
                    price = c.get("current_price")
                    if price and price > 0:
                        df = pd.DataFrame({"Close": [float(price)]}, index=pd.DatetimeIndex([now]))
                        result[sym] = df
                        _save_cache(f"{sym}_{period}_{interval}", df)
        except Exception as e:
            print(f"[data_fetcher] CoinGecko error: {e}")

    # Fetch non-crypto from yfinance
    for sym in non_crypto_symbols:
        cached = _cached(sym)
        if cached is not None:
            result[sym] = cached
            continue
        to_download.append(sym)

    for i in range(0, len(to_download), MAX_SYMBOLS_PER_BATCH):
        batch = to_download[i:i + MAX_SYMBOLS_PER_BATCH]
        try:
            raw = yf.download(
                batch,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as e:
            print(f"[data_fetcher] yfinance download error: {e}")
            continue

        if raw.empty:
            continue

        if len(batch) == 1:
            sym = batch[0]
            df = raw.copy()
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(-1)
            df = df.dropna(how="all")
            if not df.empty:
                key = f"{sym}_{period}_{interval}"
                _save_cache(key, df)
                result[sym] = df
        else:
            for sym in batch:
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        df = raw.xs(sym, axis=1, level=0).copy()
                    else:
                        df = raw[[sym]].copy()
                    df = df.dropna(how="all")
                    if not df.empty:
                        key = f"{sym}_{period}_{interval}"
                        _save_cache(key, df)
                        result[sym] = df
                except Exception:
                    pass

    # Also try CoinGecko for any crypto symbols that yfinance could not get
    missing_crypto = [s for s in symbols if s.endswith("-USD") and s not in result]
    if missing_crypto:
        cg_data = _cg_fetch(missing_crypto)
        for sym, df in cg_data.items():
            if df is not None and not df.empty:
                result[sym] = df

    return result


def fetch_current_prices(symbols, allow_stale=False):
    """Return dict of symbol -> latest close price."""
    if isinstance(symbols, str):
        symbols = [symbols]

    data = fetch_historical_data(symbols, period="5d", interval="1d", allow_stale=allow_stale)
    prices = {}
    for sym, df in data.items():
        if df is not None and not df.empty:
            prices[sym] = float(df["Close"].dropna().iloc[-1])
    return prices
