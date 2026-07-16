import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf
from .base import BaseStrategy
from src import data_fetcher_alpha as alpha

AV_BUY_THRESHOLD = 0.2
AV_SELL_THRESHOLD = -0.2

_NEWS_CACHE_TTL = 3600  # seconds
_news_cache = {}  # symbol -> (fetched_at, news list)
_PREFETCH_WORKERS = 8


def _fetch_news(symbol):
    try:
        return yf.Ticker(symbol).news or []
    except Exception:
        return []


def _get_news(symbol):
    """yf.Ticker(...).news is a live snapshot, not a historical time series —
    a backtest calls generate_signals once per simulated day (~250x/year),
    which without caching means ~250 identical network calls per symbol and
    reliably times out. Cache it; a live daily cron run naturally spaces
    calls far enough apart that the TTL still refreshes."""
    cached = _news_cache.get(symbol)
    if cached and time.time() - cached[0] < _NEWS_CACHE_TTL:
        return cached[1]
    news = _fetch_news(symbol)
    _news_cache[symbol] = (time.time(), news)
    return news


def _prefetch_news(symbols):
    """Fill the cache for every symbol not already warm, concurrently — see
    fundamental.py:_prefetch_infos for why this matters (cold cache = one
    real network call per symbol, sequential = past any reverse-proxy
    timeout for a few dozen symbols)."""
    now = time.time()
    missing = [s for s in symbols if not (
        (c := _news_cache.get(s)) and now - c[0] < _NEWS_CACHE_TTL
    )]
    if not missing:
        return
    with ThreadPoolExecutor(max_workers=_PREFETCH_WORKERS) as pool:
        futures = {pool.submit(_fetch_news, s): s for s in missing}
        for fut in as_completed(futures):
            symbol = futures[fut]
            _news_cache[symbol] = (time.time(), fut.result())

POSITIVE_KEYWORDS = [
    "upgrade", "beat", "surge", "soar", "rally", "growth", "profit",
    "record", "dividend", "buyback", "partnership", "expansion", "bullish",
]
NEGATIVE_KEYWORDS = [
    "downgrade", "miss", "plunge", "decline", "loss", "lawsuit", "layoff",
    "cut", "warning", "fraud", "scandal", "bearish",
]


def classify_title(title):
    text = (title or "").lower()
    positive = any(kw in text for kw in POSITIVE_KEYWORDS)
    negative = any(kw in text for kw in NEGATIVE_KEYWORDS)
    if positive and not negative:
        return "positive"
    if negative and not positive:
        return "negative"
    return "neutral"


class SentimentStrategy(BaseStrategy):
    """Trade on news sentiment derived from keyword matching."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        symbols = config.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"])
        min_positive_ratio = config.get("min_positive_ratio", 0.4)
        max_negative_ratio = config.get("max_negative_ratio", 0.6)
        min_articles = config.get("min_articles", 1)
        position_size_pct = config.get("position_size_pct", 0.5)
        cash = bot["cash"]
        signals = []
        use_alpha = alpha.is_available() and not bot.get("is_backtest")

        if not use_alpha:
            _prefetch_news(symbols)

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or df.empty:
                print(f"[sentiment] {symbol}: no market data, skipping")
                continue
            price = float(df["Close"].dropna().values[-1])

            qty_held = self.get_holding_quantity(bot, symbol)
            should_buy = should_sell = False

            av_result = alpha.fetch_news_sentiment(symbol) if use_alpha else None

            if av_result is not None:
                score = av_result["average_score"]
                print(
                    f"[sentiment] {symbol}: source=alpha_vantage articles={len(av_result['articles'])} "
                    f"avg_score={score:.2f}"
                )
                should_buy = qty_held == 0 and score > AV_BUY_THRESHOLD and cash > 0
                should_sell = qty_held > 0 and score < AV_SELL_THRESHOLD
            else:
                news = _get_news(symbol)
                titles = [item.get("title") or item.get("content", {}).get("title") for item in news]
                titles = [t for t in titles if t]

                total_articles = len(titles)
                positive_count = negative_count = neutral_count = 0
                for title in titles:
                    label = classify_title(title)
                    if label == "positive":
                        positive_count += 1
                    elif label == "negative":
                        negative_count += 1
                    else:
                        neutral_count += 1

                positive_ratio = positive_count / total_articles if total_articles else 0.0
                negative_ratio = negative_count / total_articles if total_articles else 0.0

                print(
                    f"[sentiment] {symbol}: source=yfinance total={total_articles} positive={positive_count} "
                    f"negative={negative_count} neutral={neutral_count} "
                    f"positive_ratio={positive_ratio:.2f} negative_ratio={negative_ratio:.2f}"
                )

                should_buy = (
                    qty_held == 0
                    and total_articles >= min_articles
                    and positive_ratio >= min_positive_ratio
                    and cash > 0
                )
                should_sell = qty_held > 0 and negative_ratio > max_negative_ratio

            if should_buy:
                buy_amount = cash * position_size_pct
                quantity = buy_amount / price
                if quantity > 0:
                    signals.append((symbol, "buy", quantity, price))
                    cash -= buy_amount

            elif should_sell:
                signals.append((symbol, "sell", qty_held, price))

        return signals
