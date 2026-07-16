"""Marketaux news-sentiment source. Candidate replacement for Les Echos scraper
and a second dated-news source alongside Alpha Vantage.

Why: Les Echos' client only scrapes the current front page — no date filter,
so a backtest replays today's headlines on every simulated day (fake signal).
Marketaux's /news/all endpoint takes published_after/published_before and
covers French + European sources (not just US, unlike Alpha Vantage's
NEWS_SENTIMENT), so it can genuinely backtest FR/EU sentiment bots.

Everything here is a no-op (returns None / is_available() == False) when
MARKETAUX_API_KEY is not set.
"""
import os
import time
import requests

MARKETAUX_API_KEY = os.environ.get("MARKETAUX_API_KEY")
MARKETAUX_BASE_URL = "https://api.marketaux.com/v1/news/all"
MIN_CALL_INTERVAL = 1.0  # free tier: 100 req/day, no documented per-second cap
MAX_WAIT = 10

_LAST_CALL_TIME = 0


def is_available():
    return bool(MARKETAUX_API_KEY)


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


def fetch_news_sentiment(symbol, limit=10, time_from=None, time_to=None):
    """Returns {"average_score": float, "articles": [...]} or None.

    time_from/time_to: datetime objects (UTC) — passed through as
    published_after/published_before for genuine date-scoped backtesting,
    same contract as data_fetcher_alpha.fetch_news_sentiment.
    """
    if not MARKETAUX_API_KEY:
        return None
    if not _rate_limit():
        return None
    global _LAST_CALL_TIME

    params = {
        "symbols": symbol,
        "filter_entities": "true",
        "language": "en,fr",
        "limit": limit,
        "api_token": MARKETAUX_API_KEY,
    }
    if time_from is not None:
        params["published_after"] = time_from.strftime("%Y-%m-%dT%H:%M")
    if time_to is not None:
        params["published_before"] = time_to.strftime("%Y-%m-%dT%H:%M")

    try:
        resp = requests.get(MARKETAUX_BASE_URL, params=params, timeout=15)
        _LAST_CALL_TIME = time.time()
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[data_fetcher_marketaux] request error: {e}")
        return None

    articles = data.get("data") or []
    if not articles:
        return None

    scores = []
    parsed = []
    for item in articles:
        for entity in item.get("entities", []):
            if entity.get("symbol") == symbol and entity.get("sentiment_score") is not None:
                score = float(entity["sentiment_score"])
                scores.append(score)
                parsed.append({
                    "title": item.get("title"),
                    "time_published": item.get("published_at"),
                    "sentiment_score": score,
                    "source": item.get("source"),
                })
                break

    if not scores:
        return None

    return {
        "average_score": sum(scores) / len(scores),
        "articles": parsed,
    }
