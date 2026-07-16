"""Intraday backtesting engine — replays a strategy candle by candle using
Kraken's public OHLC REST endpoint (no API key needed)."""
import time

import numpy as np
import requests

from intraday.strategies import STRATEGY_CLASSES
from .risk_metrics import calc_max_drawdown, calc_win_rate

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
ALLOWED_INTERVALS = {1, 5, 15, 30, 60, 240, 1440, 10080, 21600}
MAX_CANDLES_PER_CALL = 720
COMMISSION = 0.0026  # 0.26% taker fee (Kraken réel)
MINUTES_PER_YEAR = 365 * 24 * 60

# Kraken's REST pair names diverge from the plain "BASEUSD" pattern for
# legacy assets that predate its ISO 4217-style X/Z prefixing scheme.
KNOWN_PAIRS = {
    "BTC": "XXBTZUSD", "XBT": "XXBTZUSD",
    "ETH": "XETHZUSD",
    "XRP": "XXRPZUSD",
    "LTC": "XLTCZUSD",
    "XLM": "XXLMZUSD",
    "XMR": "XXMRZUSD",
    "ETC": "XETCZUSD",
    "ZEC": "XZECZUSD",
    "REP": "XREPZUSD",
    "MLN": "XMLNZUSD",
    "DOGE": "XDGUSD", "XDG": "XDGUSD",
    "USDT": "USDTZUSD",
}


def map_symbol_to_kraken_pair(ws_symbol):
    """'XBT/USD' -> 'XXBTZUSD', 'SOL/USD' -> 'SOLUSD'."""
    base = ws_symbol.split("/")[0].upper()
    if base in KNOWN_PAIRS:
        return KNOWN_PAIRS[base]
    return base + "USD"


def _fetch_ohlc(pair, interval_minutes, since_ts):
    """Fetch all candles for `pair` since `since_ts`, paginating past Kraken's
    720-candle-per-call cap using the API's own `last` cursor."""
    candles = []
    since = since_ts
    for _ in range(50):  # hard cap so a misbehaving API can't loop forever
        resp = requests.get(KRAKEN_OHLC_URL, params={
            "pair": pair, "interval": interval_minutes, "since": since,
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ValueError(f"Kraken API error for {pair}: {data['error']}")

        result = data.get("result", {})
        rows_key = next((k for k in result if k != "last"), None)
        rows = result.get(rows_key, []) if rows_key else []
        candles.extend(rows)

        last = result.get("last")
        if not rows or last is None or last == since or len(rows) < MAX_CANDLES_PER_CALL:
            break
        since = last
        time.sleep(0.2)  # be polite to the public API

    return candles


def _candle_dict(row):
    return {
        "open_time": int(row[0]),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[6]),
    }


def _align_symbols(candles_by_symbol):
    """Intersect timestamps across symbols, same approach as the daily
    backtest — drop symbols with drastically shorter history first."""
    lengths = [len(c) for c in candles_by_symbol.values()]
    median_len = sorted(lengths)[len(lengths) // 2]
    min_required = max(5, median_len * 0.6)
    candles_by_symbol = {s: c for s, c in candles_by_symbol.items() if len(c) >= min_required}

    common_ts = None
    for candles in candles_by_symbol.values():
        ts = set(c["open_time"] for c in candles)
        common_ts = ts if common_ts is None else common_ts & ts
    common_ts = sorted(common_ts or [])

    aligned = {}
    for s, candles in candles_by_symbol.items():
        by_ts = {c["open_time"]: c for c in candles}
        aligned[s] = [by_ts[ts] for ts in common_ts]
    return aligned, common_ts


def run_intraday_backtest(strategy_name, symbols, timeframe_minutes, period_hours=168, capital=1000):
    # Accept both bot names (crypto_social_momentum) and strategy keys (social_momentum)
    if strategy_name not in STRATEGY_CLASSES:
        # Try stripping 'crypto_' prefix
        alt = strategy_name.replace("crypto_", "", 1) if strategy_name.startswith("crypto_") else None
        if alt and alt in STRATEGY_CLASSES:
            strategy_name = alt
        else:
            raise ValueError(f"unknown strategy '{strategy_name}'")
    if timeframe_minutes not in ALLOWED_INTERVALS:
        raise ValueError(f"timeframe_minutes must be one of {sorted(ALLOWED_INTERVALS)}")
    if not symbols:
        raise ValueError("No symbols configured for backtest")

    since_ts = int(time.time() - period_hours * 3600)

    raw_by_symbol = {}
    for symbol in symbols:
        pair = map_symbol_to_kraken_pair(symbol)
        rows = _fetch_ohlc(pair, timeframe_minutes, since_ts)
        if rows:
            raw_by_symbol[symbol] = [_candle_dict(r) for r in rows]

    if not raw_by_symbol:
        raise ValueError("No historical OHLC data available for these symbols")

    aligned, common_ts = _align_symbols(raw_by_symbol)
    if len(common_ts) < 5:
        raise ValueError("Not enough overlapping candle history to backtest")

    cls = STRATEGY_CLASSES[strategy_name]
    strat = cls(strategy_name, capital, list(aligned.keys()), timeframe_minutes)

    open_trades = {}
    closed_trades = []
    pnl_history = []
    WINDOW = 100  # same lookback window the live scheduler feeds strategies

    for i, ts in enumerate(common_ts):
        window_start = max(0, i + 1 - WINDOW)
        candles_by_symbol = {s: candles[window_start:i + 1] for s, candles in aligned.items()}
        current_prices = {s: candles[i]["close"] for s, candles in aligned.items()}

        try:
            signals = strat.analyze(candles_by_symbol)
        except Exception:
            signals = []

        seen = set()
        for sig in signals:
            symbol, side, qty, price, reason = sig
            key = (symbol, side, round(qty, 6))
            if key in seen or qty <= 0:
                continue
            seen.add(key)

            fill = strat.execute(symbol, side, qty, price, COMMISSION)
            if fill is None:
                continue
            filled_qty, _commission = fill

            if side == "buy":
                open_trades.setdefault(symbol, []).append({"quantity": filled_qty, "entry_price": price})
            else:
                trades_list = open_trades.get(symbol, [])
                qty_to_close = filled_qty
                pnl = 0.0
                while qty_to_close > 1e-9 and trades_list:
                    entry = trades_list[0]
                    matched = min(qty_to_close, entry["quantity"])
                    pnl += (price - entry["entry_price"]) * matched
                    qty_to_close -= matched
                    if entry["quantity"] <= matched + 1e-9:
                        trades_list.pop(0)
                    else:
                        entry["quantity"] -= matched
                closed_trades.append({"symbol": symbol, "pnl": pnl})

        total_value = strat.portfolio_value(current_prices)
        pnl_history.append({
            "date": time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)),
            "value": round(total_value, 2),
        })

    values = [p["value"] for p in pnl_history]
    values_arr = np.asarray(values, dtype=float)
    period_returns = np.diff(values_arr) / values_arr[:-1] if len(values_arr) > 1 else np.array([])
    final_value = values[-1] if values else capital
    total_return_pct = (final_value - capital) / capital * 100 if capital else 0.0

    periods_per_year = MINUTES_PER_YEAR / timeframe_minutes
    sharpe = _calc_intraday_sharpe(period_returns, periods_per_year)

    return {
        "strategy": strategy_name,
        "period": f"{period_hours}h",
        "start_date": pnl_history[0]["date"] if pnl_history else None,
        "end_date": pnl_history[-1]["date"] if pnl_history else None,
        "initial_capital": capital,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": calc_max_drawdown(values),
        "win_rate": calc_win_rate(closed_trades),
        "total_trades": len(closed_trades),
        "pnl_history": pnl_history,
    }


def _calc_intraday_sharpe(period_returns, periods_per_year, risk_free_rate=0.05):
    """Same formula as risk_metrics.calc_sharpe but annualized off the
    candle interval instead of a fixed 252 trading days."""
    period_returns = np.asarray(period_returns, dtype=float)
    period_returns = period_returns[~np.isnan(period_returns)]
    if len(period_returns) < 2:
        return 0.0
    std = np.std(period_returns, ddof=1)
    if std == 0:
        return 0.0
    mean_annual = np.mean(period_returns) * periods_per_year
    vol_annual = std * np.sqrt(periods_per_year)
    return round(float((mean_annual - risk_free_rate) / vol_annual), 4)
