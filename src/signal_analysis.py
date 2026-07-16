"""Explain why a bot's strategy did or didn't generate a signal, per symbol."""
import numpy as np
import yfinance as yf

from .data_fetcher import fetch_historical_data
from strategies.rsi_mean_reversion import compute_rsi
from strategies.sentiment import classify_title


def _round(v, n=4):
    return round(float(v), n) if v is not None else None


def _analyze_sma_crossover(bot, market_data):
    config = bot["config"]
    fast = config.get("fast_period", 20)
    slow = config.get("slow_period", 50)
    symbols = config.get("symbols", [])
    out = []

    for symbol in symbols:
        df = market_data.get(symbol)
        if df is None or len(df) < slow + 1:
            out.append({"symbol": symbol, "status": "insufficient_data",
                        "reason": f"Need {slow + 1} days of history, have {0 if df is None else len(df)}",
                        "indicators": {}})
            continue

        closes = df["Close"].values
        fast_now = float(np.mean(closes[-fast:]))
        fast_prev = float(np.mean(closes[-(fast + 1):-1]))
        slow_now = float(np.mean(closes[-slow:]))
        slow_prev = float(np.mean(closes[-(slow + 1):-1]))

        crossed_above = fast_prev <= slow_prev and fast_now > slow_now
        crossed_below = fast_prev >= slow_prev and fast_now < slow_now

        indicators = {
            "sma_20": round(fast_now, 2),
            "sma_50": round(slow_now, 2),
            "difference": round(fast_now - slow_now, 2),
        }

        if crossed_above:
            out.append({"symbol": symbol, "status": "signal", "reason": "SMA20 just crossed above SMA50 - buy signal", "indicators": indicators})
        elif crossed_below:
            out.append({"symbol": symbol, "status": "signal", "reason": "SMA20 just crossed below SMA50 - sell signal", "indicators": indicators})
        elif fast_now > slow_now:
            out.append({"symbol": symbol, "status": "no_signal", "reason": "SMA20 is already above SMA50 - no crossover needed", "indicators": indicators})
        else:
            out.append({"symbol": symbol, "status": "no_signal", "reason": "SMA20 is already below SMA50 - no crossover needed", "indicators": indicators})

    return out


def _analyze_rsi(bot, market_data):
    config = bot["config"]
    period = config.get("period", 14)
    oversold = config.get("oversold", 30)
    overbought = config.get("overbought", 70)
    symbols = config.get("symbols", [])
    out = []

    for symbol in symbols:
        df = market_data.get(symbol)
        if df is None or len(df) < period + 2:
            out.append({"symbol": symbol, "status": "insufficient_data",
                        "reason": f"Need {period + 2} days of history, have {0 if df is None else len(df)}",
                        "indicators": {}})
            continue

        closes = df["Close"].values.astype(float)
        rsi = compute_rsi(closes, period)
        indicators = {"rsi_14": round(rsi, 2), "oversold_threshold": oversold, "overbought_threshold": overbought}

        if rsi < oversold:
            out.append({"symbol": symbol, "status": "signal", "reason": f"RSI {rsi:.1f} is below oversold threshold {oversold} - buy signal", "indicators": indicators})
        elif rsi > overbought:
            out.append({"symbol": symbol, "status": "signal", "reason": f"RSI {rsi:.1f} is above overbought threshold {overbought} - sell signal", "indicators": indicators})
        else:
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"RSI {rsi:.1f} is within neutral range ({oversold}-{overbought})", "indicators": indicators})

    return out


def _analyze_momentum(bot, market_data):
    config = bot["config"]
    lookback = config.get("lookback", 20)
    top_n = config.get("top_n", 3)
    symbols = config.get("symbols", [])
    held = {h["symbol"] for h in bot.get("holdings", [])}

    returns = {}
    for symbol in symbols:
        df = market_data.get(symbol)
        if df is None or len(df) < lookback + 1:
            continue
        closes = df["Close"].values.astype(float)
        returns[symbol] = (closes[-1] - closes[-(lookback + 1)]) / closes[-(lookback + 1)]

    ranked = sorted(returns.keys(), key=lambda s: returns[s], reverse=True)
    top_symbols = set(ranked[:top_n])

    out = []
    for symbol in symbols:
        if symbol not in returns:
            out.append({"symbol": symbol, "status": "insufficient_data",
                        "reason": f"Need {lookback + 1} days of history", "indicators": {}})
            continue
        rank = ranked.index(symbol) + 1
        indicators = {"return_pct": round(returns[symbol] * 100, 2), "rank": rank, "ranked_symbols": ranked}
        if symbol in top_symbols and symbol not in held:
            out.append({"symbol": symbol, "status": "signal", "reason": f"Ranked #{rank}/{len(ranked)} by {lookback}d return - buy signal (top {top_n})", "indicators": indicators})
        elif symbol in top_symbols:
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"Ranked #{rank}/{len(ranked)}, already held - no action", "indicators": indicators})
        elif symbol in held:
            out.append({"symbol": symbol, "status": "signal", "reason": f"Dropped to rank #{rank}/{len(ranked)}, outside top {top_n} - sell signal", "indicators": indicators})
        else:
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"Ranked #{rank}/{len(ranked)} - outside top {top_n}, not held", "indicators": indicators})

    return out


def _analyze_bollinger(bot, market_data):
    config = bot["config"]
    period = config.get("period", 20)
    std_dev = config.get("std_dev", 2)
    symbols = config.get("symbols", [])
    out = []

    for symbol in symbols:
        df = market_data.get(symbol)
        if df is None or len(df) < period:
            out.append({"symbol": symbol, "status": "insufficient_data",
                        "reason": f"Need {period} days of history, have {0 if df is None else len(df)}",
                        "indicators": {}})
            continue

        closes = df["Close"].values.astype(float)
        window = closes[-period:]
        mid = float(np.mean(window))
        std = float(np.std(window, ddof=1))
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        price = float(closes[-1])

        indicators = {
            "upper_band": round(upper, 2),
            "middle_band": round(mid, 2),
            "lower_band": round(lower, 2),
            "price": round(price, 2),
        }

        if price <= lower:
            out.append({"symbol": symbol, "status": "signal", "reason": f"Price ${price:.2f} touched/broke lower band ${lower:.2f} - buy signal", "indicators": indicators})
        elif price >= upper:
            out.append({"symbol": symbol, "status": "signal", "reason": f"Price ${price:.2f} touched/broke upper band ${upper:.2f} - sell signal", "indicators": indicators})
        else:
            pct_to_band = min(abs(price - upper), abs(price - lower)) / mid * 100
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"Price ${price:.2f} is within bands (${lower:.2f}-${upper:.2f}), {pct_to_band:.1f}% from nearest band", "indicators": indicators})

    return out


def _analyze_dca(bot, market_data):
    config = bot["config"]
    amount_per_period = config.get("amount_per_period", 100)
    symbols = config.get("symbols", [])
    max_position = config.get("max_position", 10)
    cash = bot["cash"]
    out = []

    for symbol in symbols:
        df = market_data.get(symbol)
        qty_held = next((h["quantity"] for h in bot.get("holdings", []) if h["symbol"] == symbol), 0.0)
        indicators = {"current_position": round(qty_held, 4), "max_position": max_position, "cash_available": round(cash, 2)}

        if df is None or df.empty:
            out.append({"symbol": symbol, "status": "insufficient_data", "reason": "No market data", "indicators": indicators})
            continue

        if qty_held >= max_position:
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"Max position of {max_position} already reached", "indicators": indicators})
        elif cash < amount_per_period:
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"Insufficient cash (${cash:.2f} < ${amount_per_period})", "indicators": indicators})
        else:
            out.append({"symbol": symbol, "status": "signal", "reason": f"Buys ${amount_per_period} every run - always trades until max position", "indicators": indicators})

    return out


def _analyze_pairs(bot, market_data):
    config = bot["config"]
    pairs = config.get("pairs", [])
    entry_z = config.get("entry_zscore", 2.0)
    exit_z = config.get("exit_zscore", 0.5)
    lookback = config.get("lookback", 20)
    out = []

    for pair in pairs:
        sym_a, sym_b = pair["symbol_a"], pair["symbol_b"]
        label = f"{sym_a}/{sym_b}"
        df_a, df_b = market_data.get(sym_a), market_data.get(sym_b)
        if df_a is None or df_b is None:
            out.append({"symbol": label, "status": "insufficient_data", "reason": "Missing market data for pair", "indicators": {}})
            continue

        min_len = min(len(df_a), len(df_b))
        if min_len < lookback + 1:
            out.append({"symbol": label, "status": "insufficient_data",
                        "reason": f"Need {lookback + 1} days of history, have {min_len}", "indicators": {}})
            continue

        closes_a = df_a["Close"].values[-min_len:].astype(float)
        closes_b = df_b["Close"].values[-min_len:].astype(float)
        log_a, log_b = np.log(closes_a), np.log(closes_b)
        hedge_ratio = np.polyfit(log_b, log_a, 1)[0]
        spread = log_a - hedge_ratio * log_b
        spread_window = spread[-lookback:]
        mean_spread = float(np.mean(spread_window))
        std_spread = float(np.std(spread_window, ddof=1))

        if std_spread == 0:
            out.append({"symbol": label, "status": "no_signal", "reason": "Zero spread variance - cannot compute z-score", "indicators": {}})
            continue

        current_spread = float(spread[-1])
        z = (current_spread - mean_spread) / std_spread

        indicators = {
            "spread": round(current_spread, 4),
            "z_score": round(z, 2),
            "entry_zscore": entry_z,
            "exit_zscore": exit_z,
        }

        if abs(z) < exit_z:
            out.append({"symbol": label, "status": "no_signal", "reason": f"Z-score {z:.2f} within exit band (|z|<{exit_z}) - no new entry", "indicators": indicators})
        elif z > entry_z:
            out.append({"symbol": label, "status": "signal", "reason": f"Z-score {z:.2f} > entry threshold {entry_z} - spread too high, short {sym_a}/long {sym_b}", "indicators": indicators})
        elif z < -entry_z:
            out.append({"symbol": label, "status": "signal", "reason": f"Z-score {z:.2f} < -{entry_z} - spread too low, long {sym_a}/short {sym_b}", "indicators": indicators})
        else:
            out.append({"symbol": label, "status": "no_signal", "reason": f"Z-score {z:.2f} is only {abs(z) / entry_z * 100:.0f}% of entry threshold {entry_z} - about 2% of days trigger this", "indicators": indicators})

    return out


def _analyze_fundamental(bot, market_data):
    config = bot["config"]
    symbols = config.get("symbols", [])
    min_market_cap = config.get("min_market_cap", 10_000_000_000)
    max_pe_ratio = config.get("max_pe_ratio", 25)
    min_pe_ratio = config.get("min_pe_ratio", 5)
    min_roe = config.get("min_roe", 10)
    max_debt_to_equity = config.get("max_debt_to_equity", 1.5)
    out = []

    for symbol in symbols:
        df = market_data.get(symbol)
        if df is None or df.empty:
            out.append({"symbol": symbol, "status": "insufficient_data", "reason": "No market data", "indicators": {}})
            continue

        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as e:
            out.append({"symbol": symbol, "status": "insufficient_data", "reason": f"Error fetching fundamentals: {e}", "indicators": {}})
            continue

        pe_ratio = info.get("trailingPE")
        market_cap = info.get("marketCap")
        roe = info.get("returnOnEquity")
        roe = roe * 100 if roe is not None else None
        debt_to_equity = info.get("debtToEquity")

        qty_held = next((h["quantity"] for h in bot.get("holdings", []) if h["symbol"] == symbol), 0.0)

        checks = {
            "pe_in_range": pe_ratio is not None and min_pe_ratio <= pe_ratio <= max_pe_ratio,
            "market_cap_ok": market_cap is not None and market_cap >= min_market_cap,
            "roe_ok": roe is None or roe >= min_roe,
            "debt_ok": debt_to_equity is None or debt_to_equity <= max_debt_to_equity,
        }

        indicators = {
            "pe_ratio": _round(pe_ratio, 2),
            "roe": _round(roe, 2),
            "debt_to_equity": _round(debt_to_equity, 2),
            "market_cap": market_cap,
            "checks": checks,
        }

        failing = [k for k, v in checks.items() if not v]

        if qty_held == 0 and not failing:
            out.append({"symbol": symbol, "status": "signal", "reason": "All fundamental conditions pass - buy signal", "indicators": indicators})
        elif qty_held == 0:
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"Failed checks: {', '.join(failing)}", "indicators": indicators})
        elif pe_ratio is not None and pe_ratio > max_pe_ratio * 2:
            out.append({"symbol": symbol, "status": "signal", "reason": f"PE {pe_ratio:.1f} exceeds 2x max ({max_pe_ratio * 2}) - sell signal", "indicators": indicators})
        else:
            out.append({"symbol": symbol, "status": "no_signal", "reason": "Already held, valuation not yet excessive", "indicators": indicators})

    return out


def _analyze_sentiment(bot, market_data):
    config = bot["config"]
    symbols = config.get("symbols", [])
    min_positive_ratio = config.get("min_positive_ratio", 0.6)
    max_negative_ratio = config.get("max_negative_ratio", 0.4)
    min_articles = config.get("min_articles", 3)
    out = []

    for symbol in symbols:
        df = market_data.get(symbol)
        if df is None or df.empty:
            out.append({"symbol": symbol, "status": "insufficient_data", "reason": "No market data", "indicators": {}})
            continue

        try:
            news = yf.Ticker(symbol).news or []
        except Exception as e:
            out.append({"symbol": symbol, "status": "insufficient_data", "reason": f"Error fetching news: {e}", "indicators": {}})
            continue

        titles = [item.get("title") or item.get("content", {}).get("title") for item in news]
        titles = [t for t in titles if t]

        total = len(titles)
        positive = sum(1 for t in titles if classify_title(t) == "positive")
        negative = sum(1 for t in titles if classify_title(t) == "negative")
        pos_ratio = positive / total if total else 0.0
        neg_ratio = negative / total if total else 0.0

        qty_held = next((h["quantity"] for h in bot.get("holdings", []) if h["symbol"] == symbol), 0.0)

        indicators = {
            "total_articles": total,
            "positive_count": positive,
            "negative_count": negative,
            "positive_ratio": round(pos_ratio, 2),
            "negative_ratio": round(neg_ratio, 2),
            "min_positive_ratio": min_positive_ratio,
            "max_negative_ratio": max_negative_ratio,
        }

        if total < min_articles:
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"Only {total} articles, need {min_articles}", "indicators": indicators})
        elif qty_held == 0 and pos_ratio >= min_positive_ratio:
            out.append({"symbol": symbol, "status": "signal", "reason": f"{pos_ratio:.0%} positive news (>= {min_positive_ratio:.0%}) - buy signal", "indicators": indicators})
        elif qty_held > 0 and neg_ratio > max_negative_ratio:
            out.append({"symbol": symbol, "status": "signal", "reason": f"{neg_ratio:.0%} negative news (> {max_negative_ratio:.0%}) - sell signal", "indicators": indicators})
        else:
            out.append({"symbol": symbol, "status": "no_signal", "reason": f"{pos_ratio:.0%} positive / {neg_ratio:.0%} negative - doesn't cross thresholds", "indicators": indicators})

    return out


ANALYZERS = {
    "sma_crossover": _analyze_sma_crossover,
    "rsi_mean_reversion": _analyze_rsi,
    "momentum": _analyze_momentum,
    "bollinger_bands": _analyze_bollinger,
    "dca": _analyze_dca,
    "pairs_trading": _analyze_pairs,
    "fundamental": _analyze_fundamental,
    "sentiment": _analyze_sentiment,
}


def analyze_bot_signals(bot):
    """Given a bot dict (from db.get_bot), return signal-check analysis."""
    from .bot_manager import _collect_symbols

    strategy = bot["strategy"]
    analyzer = ANALYZERS.get(strategy)
    if analyzer is None:
        return {"bot_id": bot["id"], "strategy": strategy, "analysis": [],
                "error": f"No signal analysis available for strategy '{strategy}'"}

    symbols = _collect_symbols(bot)
    market_data = fetch_historical_data(symbols, period="1y", interval="1d") if symbols else {}
    analysis = analyzer(bot, market_data)

    return {"bot_id": bot["id"], "strategy": strategy, "analysis": analysis}
