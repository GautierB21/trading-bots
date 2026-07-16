"""Alpha Vantage data source. Optional complement to yfinance.

Everything here is a no-op (returns None / is_available() == False) when
ALPHA_VANTAGE_API_KEY is not set, so callers can always fall back to yfinance.
"""
import os
import time
import requests

AV_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY")
AV_BASE_URL = "https://www.alphavantage.co/query"
MIN_CALL_INTERVAL = 12  # 5 calls/min free tier = 12s between calls
MAX_WAIT = 30  # never block the trading run more than this for rate limiting

_LAST_CALL_TIME = 0


def is_available():
    return bool(AV_API_KEY)


def _rate_limit():
    """Sleep until safe to call again, or bail out if the wait would be too long."""
    global _LAST_CALL_TIME
    elapsed = time.time() - _LAST_CALL_TIME
    wait = MIN_CALL_INTERVAL - elapsed
    if wait <= 0:
        return True
    if wait > MAX_WAIT:
        print(f"[data_fetcher_alpha] rate limit wait ({wait:.0f}s) exceeds max, skipping AV call")
        return False
    time.sleep(wait)
    return True


def _call(params):
    if not AV_API_KEY:
        return None
    if not _rate_limit():
        return None
    global _LAST_CALL_TIME
    try:
        resp = requests.get(AV_BASE_URL, params={**params, "apikey": AV_API_KEY}, timeout=15)
        _LAST_CALL_TIME = time.time()
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[data_fetcher_alpha] request error: {e}")
        return None

    if not data or "Error Message" in data or "Note" in data or "Information" in data:
        return None
    return data


def fetch_fundamentals(symbol):
    """OVERVIEW endpoint. Returns dict of key fundamentals or None."""
    data = _call({"function": "OVERVIEW", "symbol": symbol})
    if not data or "Symbol" not in data:
        return None

    def _num(key):
        val = data.get(key)
        if val in (None, "", "None", "-"):
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    return {
        "symbol": data.get("Symbol"),
        "sector": data.get("Sector"),
        "industry": data.get("Industry"),
        "pe_ratio": _num("PERatio"),
        "roe": _num("ReturnOnEquityTTM"),
        "debt_to_equity": _num("DebtToEquity"),
        "market_cap": _num("MarketCapitalization"),
        "revenue_ttm": _num("RevenueTTM"),
        "gross_profit_ttm": _num("GrossProfitTTM"),
        "eps": _num("EarningsPerShare"),
        "book_value": _num("BookValue"),
        "price_to_book": _num("PriceToBook"),
        "dividend_yield": _num("DividendYield"),
        "beta": _num("Beta"),
    }


def fetch_income_statement(symbol):
    """INCOME_STATEMENT endpoint. Returns last 4 quarterly reports or None."""
    data = _call({"function": "INCOME_STATEMENT", "symbol": symbol})
    if not data or "quarterlyReports" not in data:
        return None

    quarters = []
    for report in data["quarterlyReports"][:4]:
        quarters.append({
            "fiscal_date_ending": report.get("fiscalDateEnding"),
            "total_revenue": report.get("totalRevenue"),
            "gross_profit": report.get("grossProfit"),
            "net_income": report.get("netIncome"),
            "eps": report.get("reportedEPS"),
        })
    return {"symbol": symbol, "quarterly": quarters}


def fetch_balance_sheet(symbol):
    """BALANCE_SHEET endpoint. Returns latest quarterly totals or None."""
    data = _call({"function": "BALANCE_SHEET", "symbol": symbol})
    if not data or "quarterlyReports" not in data or not data["quarterlyReports"]:
        return None

    latest = data["quarterlyReports"][0]
    return {
        "symbol": symbol,
        "fiscal_date_ending": latest.get("fiscalDateEnding"),
        "total_assets": latest.get("totalAssets"),
        "total_liabilities": latest.get("totalLiabilities"),
        "total_equity": latest.get("totalShareholderEquity"),
        "total_debt": latest.get("shortLongTermDebtTotal"),
        "cash": latest.get("cashAndCashEquivalentsAtCarryingValue"),
    }


def fetch_news_sentiment(symbol, limit=10, time_from=None, time_to=None):
    """NEWS_SENTIMENT endpoint. Returns list of scored, dated articles or None.

    time_from/time_to (format YYYYMMDDTHHMM) scope the query to a historical
    window in a single call — pass them to bulk-fetch a symbol's full news
    history once for backtesting, instead of relying on "latest" news repeated
    across every simulated day (see strategies/sentiment_av.py)."""
    params = {"function": "NEWS_SENTIMENT", "tickers": symbol, "limit": limit, "sort": "EARLIEST"}
    if time_from:
        params["time_from"] = time_from
    if time_to:
        params["time_to"] = time_to
    data = _call(params)
    if not data or "feed" not in data:
        return None

    articles = []
    for item in data["feed"][:limit]:
        ticker_score = None
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker") == symbol:
                try:
                    ticker_score = float(ts.get("ticker_sentiment_score"))
                except (TypeError, ValueError):
                    ticker_score = None
                break

        try:
            overall_score = float(item.get("overall_sentiment_score"))
        except (TypeError, ValueError):
            overall_score = None

        articles.append({
            "title": item.get("title"),
            "summary": item.get("summary"),
            "url": item.get("url"),
            "source": item.get("source"),
            "time_published": item.get("time_published"),  # "YYYYMMDDTHHMMSS"
            "overall_sentiment_score": overall_score,
            "ticker_sentiment_score": ticker_score,
            "topics": [t.get("topic") for t in item.get("topics", [])],
        })

    if not articles:
        return None

    scores = [a["ticker_sentiment_score"] if a["ticker_sentiment_score"] is not None else a["overall_sentiment_score"]
              for a in articles]
    scores = [s for s in scores if s is not None]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    return {"symbol": symbol, "articles": articles, "average_score": avg_score}


def fetch_quote(symbol):
    """GLOBAL_QUOTE endpoint. Fallback for when yfinance fails."""
    data = _call({"function": "GLOBAL_QUOTE", "symbol": symbol})
    if not data or "Global Quote" not in data or not data["Global Quote"]:
        return None

    quote = data["Global Quote"]
    try:
        return {
            "symbol": quote.get("01. symbol"),
            "price": float(quote.get("05. price")),
            "change": float(quote.get("09. change")),
            "change_percent": quote.get("10. change percent"),
            "volume": int(quote.get("06. volume")),
        }
    except (TypeError, ValueError):
        return None
