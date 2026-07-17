"""Currency normalization — the dashboard and every bot's cash/capital are
denominated in EUR (see dashboard/index.html, intraday budgets in €), but
symbols trade in their local listing currency: BMW.DE in EUR, 7203.T in JPY,
0700.HK in HKD, SHEL.L in GBp (pence, not pounds), AAPL/crypto in USD.

Without conversion, prices in different currencies were being summed and
divided as if they were the same unit — e.g. a JPY price of ~2500 treated as
"2500 EUR-equivalent", overstating a JPY position's booked value by roughly
the JPY/EUR rate (~150x). fetch_historical_data() converts every symbol's
OHLC to EUR before returning, so every downstream consumer (strategies,
portfolio, risk metrics) sees comparable units without needing to know this.
"""
import time
import yfinance as yf

TARGET_CCY = "EUR"

# Listing currency by ticker suffix — static and network-free, since a
# symbol's listing currency essentially never changes. London-listed stocks
# quote in pence (GBp), not pounds — a distinct code from GBP, handled below.
_SUFFIX_CCY = {
    ".PA": "EUR", ".DE": "EUR", ".AS": "EUR", ".MI": "EUR", ".MC": "EUR",
    ".L": "GBp", ".SW": "CHF", ".SIX": "CHF", ".T": "JPY", ".HK": "HKD",
    ".TO": "CAD", ".AX": "AUD",
}

_FX_CACHE_TTL = 3600  # seconds — matches data_fetcher.CACHE_TTL; FX genuinely moves
_fx_rate_cache = {}  # currency -> (fetched_at, rate_to_eur)


def get_symbol_currency(symbol):
    """Native listing currency for a symbol, e.g. 'EUR', 'USD', 'JPY', 'GBp'."""
    if symbol.startswith("^"):
        return TARGET_CCY  # Yahoo index/yield tickers (^TNX, ^IRX, ^GSPC...) are
                            # points or percentages, not currency-denominated
                            # prices — never convert, or a 4.5% yield turns into
                            # a nonsense "3.9%" after an FX multiply.
    if symbol.endswith("-USD"):
        return "USD"  # CoinGecko crypto prices are always USD (vs_currency="usd")
    for suffix, ccy in _SUFFIX_CCY.items():
        if symbol.endswith(suffix):
            return ccy
    return "USD"  # bare ticker (AAPL, MSFT, ...) => US listing


def _fetch_fx_rate(currency):
    """1 unit of `currency` expressed in TARGET_CCY (EUR)."""
    if currency == TARGET_CCY:
        return 1.0
    if currency == "GBp":
        return _fetch_fx_rate("GBP") / 100.0

    pair = f"{currency}{TARGET_CCY}=X"
    try:
        df = yf.download(pair, period="5d", interval="1d", progress=False)
        if df.empty:
            raise ValueError("empty FX series")
        close = df["Close"]
        if hasattr(close, "columns"):  # yf.download can return a MultiIndex column
            close = close.iloc[:, 0]
        rate = float(close.dropna().iloc[-1])
        if rate <= 0:
            raise ValueError(f"non-positive FX rate: {rate}")
        return rate
    except Exception as e:
        print(f"[fx] failed to fetch {pair}, falling back to 1.0 — "
              f"treating {currency} as {TARGET_CCY} is WRONG, check network/ticker: {e}")
        return 1.0


def get_fx_rate(currency):
    """Cached (1h) wrapper around _fetch_fx_rate."""
    cached = _fx_rate_cache.get(currency)
    if cached and time.time() - cached[0] < _FX_CACHE_TTL:
        return cached[1]
    rate = _fetch_fx_rate(currency)
    _fx_rate_cache[currency] = (time.time(), rate)
    return rate


def convert_df_to_eur(df, symbol):
    """Return a copy of df with OHLC columns converted from symbol's native
    currency to EUR. No-op (same object) if already EUR."""
    currency = get_symbol_currency(symbol)
    if currency == TARGET_CCY:
        return df
    rate = get_fx_rate(currency)
    df = df.copy()
    for col in ("Open", "High", "Low", "Close", "Adj Close"):
        if col in df.columns:
            df[col] = df[col] * rate
    return df
