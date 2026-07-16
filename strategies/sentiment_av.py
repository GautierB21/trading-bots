"""News sentiment strategy backed by Alpha Vantage NEWS_SENTIMENT — unlike
strategies/sentiment.py (yfinance .news, a live-only snapshot with no
historical archive), this fetches a symbol's full dated news history in one
call and buckets it by day, so a backtest sees the sentiment that actually
existed on each simulated date instead of replaying today's headlines
across every day of the replay.

Alpha Vantage free tier = 25 requests/day total, shared with fundamental.py
and sentiment.py's own Alpha Vantage fallback. Keep this bot's symbol list
short (~15 names) — one request per symbol backfills its whole history, then
live runs only need a small incremental top-up.
"""
from datetime import datetime, timedelta, timezone

from .base import BaseStrategy
from src import data_fetcher_alpha as alpha

BUY_THRESHOLD = 0.2
SELL_THRESHOLD = -0.2
LOOKBACK_DAYS = 5  # was 3 — a 15-symbol US large-cap universe doesn't have
                   # enough daily news flow for a 3-day window to be anything
                   # but noisy; 5 days trades a bit of staleness for more
                   # articles per score
FULL_HISTORY_DAYS = 730  # ~2y, matches the equity bots' usual backtest window
LIVE_REFRESH_TTL = 6 * 3600  # seconds — don't re-hit AV more than every 6h live

_news_cache = {}  # symbol -> {"articles": [...], "covered_to": datetime, "fetched_at": float}


def _parse_av_time(ts):
    # "YYYYMMDDTHHMMSS" -> aware UTC datetime
    return datetime.strptime(ts, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)


def _ensure_history(symbol, as_of):
    """Populate/refresh the cache for symbol so it covers up to `as_of`.

    Backtest calls arrive with as_of far in the past relative to wall-clock
    now — those are served entirely from one bulk fetch done on the first
    call and never re-fetched. Live calls arrive with as_of ≈ now — those get
    a cheap incremental top-up instead of repeating the full-history pull.
    """
    now = datetime.now(timezone.utc)
    cached = _news_cache.get(symbol)

    if cached is None:
        time_from = (now - timedelta(days=FULL_HISTORY_DAYS)).strftime("%Y%m%dT%H%M")
        result = alpha.fetch_news_sentiment(symbol, limit=1000, time_from=time_from)
        articles = result["articles"] if result else []
        _news_cache[symbol] = {"articles": articles, "covered_to": now, "fetched_at": now.timestamp()}
        return _news_cache[symbol]["articles"]

    # Only refresh if the caller actually needs news newer than what we have,
    # and we're not spamming AV faster than the TTL (live mode).
    stale = now.timestamp() - cached["fetched_at"] > LIVE_REFRESH_TTL
    needs_more = as_of > cached["covered_to"]
    if needs_more and stale:
        time_from = cached["covered_to"].strftime("%Y%m%dT%H%M")
        result = alpha.fetch_news_sentiment(symbol, limit=200, time_from=time_from)
        if result:
            cached["articles"].extend(result["articles"])
        cached["covered_to"] = now
        cached["fetched_at"] = now.timestamp()

    return cached["articles"]


def _current_sim_date(market_data):
    latest = None
    for df in market_data.values():
        if df is None or df.empty:
            continue
        d = df.index[-1]
        if latest is None or d > latest:
            latest = d
    if latest is None:
        return datetime.now(timezone.utc)
    return latest.to_pydatetime().replace(tzinfo=timezone.utc)


class SentimentAVStrategy(BaseStrategy):
    """Buy on positive dated news sentiment, sell on negative — Alpha Vantage backed."""

    def generate_signals(self, bot, market_data):
        config = bot["config"]
        symbols = config.get("symbols", [])
        min_articles = config.get("min_articles", 3)
        max_positions = config.get("max_positions", 5)
        atr_stop_mult = config.get("atr_stop_mult", 2.0)
        cash = bot["cash"]
        signals = []

        if not alpha.is_available():
            print("[sentiment_av] no ALPHA_VANTAGE_API_KEY, skipping")
            return []

        as_of = _current_sim_date(market_data)
        window_start = as_of - timedelta(days=LOOKBACK_DAYS)
        current_positions = len(bot.get("holdings", []))

        for symbol in symbols:
            df = market_data.get(symbol)
            if df is None or df.empty:
                continue
            price = float(df["Close"].dropna().values[-1])
            qty_held = self.get_holding_quantity(bot, symbol)

            if qty_held > 0 and self.atr_stop_triggered(bot, symbol, market_data, multiplier=atr_stop_mult):
                signals.append((symbol, "sell", qty_held, price))
                continue

            articles = _ensure_history(symbol, as_of)
            window = [a for a in articles if a.get("time_published")
                      and window_start <= _parse_av_time(a["time_published"]) <= as_of]

            if len(window) < min_articles:
                continue

            scores = [a["ticker_sentiment_score"] if a["ticker_sentiment_score"] is not None else a["overall_sentiment_score"]
                      for a in window]
            scores = [s for s in scores if s is not None]
            if not scores:
                continue
            avg_score = sum(scores) / len(scores)

            print(f"[sentiment_av] {symbol}: {as_of.date()} score={avg_score:+.2f} ({len(window)} articles)")

            if qty_held == 0 and avg_score > BUY_THRESHOLD and current_positions < max_positions and cash > 0:
                # conviction scales with how far above threshold the score is
                conviction = max(0.0, min(1.0, (avg_score - BUY_THRESHOLD) / (1.0 - BUY_THRESHOLD)))
                alloc = min(self.sized_allocation(bot, market_data, max_positions, conviction), cash)
                quantity = alloc / price
                if quantity > 0:
                    signals.append((symbol, "buy", quantity, price))
                    cash -= alloc
                    current_positions += 1
            elif qty_held > 0 and avg_score < SELL_THRESHOLD:
                signals.append((symbol, "sell", qty_held, price))

        return signals
