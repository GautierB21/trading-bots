"""Historical backtesting engine — replays a strategy day by day over past data."""
import numpy as np
import pandas as pd
from .data_fetcher import fetch_historical_data
from .risk_metrics import calc_sharpe, calc_max_drawdown, calc_win_rate

COMMISSION = 0.0026  # 0.26% taker fee (Kraken réel)
SLIPPAGE = 0.0005


def _collect_symbols(config):
    symbols = list(config.get("symbols", []))
    for pair in config.get("pairs", []):
        symbols.append(pair["symbol_a"])
        symbols.append(pair["symbol_b"])
    return list(dict.fromkeys(symbols))


def backtest_strategy(strategy_name, config, period="2y", capital=10000):
    from strategies import get_strategy
    strategy = get_strategy(strategy_name)
    symbols = _collect_symbols(config)
    if not symbols:
        raise ValueError("No symbols configured for backtest")
    raw_data = fetch_historical_data(symbols, period=period, interval="1d")
    market_data = {s: df for s, df in raw_data.items() if df is not None and not df.empty}
    if not market_data:
        raise ValueError("No historical data available for these symbols")
    return _run_backtest(strategy, strategy_name, config, market_data, period, capital)


def backtest_compare(configs_by_strategy, period="1y", capital=10000):
    """Run backtests for multiple strategies sharing one data download."""
    from strategies import get_strategy

    # Collect ALL unique symbols across all strategies
    all_symbols = set()
    for strat_name, config in configs_by_strategy.items():
        all_symbols.update(_collect_symbols(config or {}))

    # Download once, in batches to avoid yfinance timeout
    max_batch = 50
    sym_list = list(all_symbols)
    master_data = {}
    for i in range(0, len(sym_list), max_batch):
        batch = sym_list[i:i+max_batch]
        raw = fetch_historical_data(batch, period=period, interval="1d")
        for s, df in raw.items():
            if df is not None and not df.empty:
                master_data[s] = df

    results = []
    for strat_name, config in configs_by_strategy.items():
        strategy = get_strategy(strat_name)
        syms = _collect_symbols(config or {})
        strat_data = {s: master_data[s] for s in syms if s in master_data}
        if not strat_data:
            continue
        result = _run_backtest(strategy, strat_name, config, strat_data, period, capital)
        results.append(result)

    return results


def _run_backtest(strategy, strategy_name, config, market_data, period, capital):
    """Run backtest with pre-fetched market_data."""
    # Filter out symbols with too little data before computing intersection
    market_data = {s: df for s, df in market_data.items() if df is not None and not df.empty and len(df) >= 20}
    if not market_data:
        raise ValueError("No symbols with sufficient historical data")

    # Also drop symbols whose date range is drastically shorter than the median
    lengths = [len(df) for df in market_data.values()]
    median_len = sorted(lengths)[len(lengths) // 2]
    min_required = max(20, median_len * 0.6)  # 60% of median or 20, whichever is larger
    market_data = {s: df for s, df in market_data.items() if len(df) >= min_required}

    common_index = None
    for df in market_data.values():
        idx = df.index
        common_index = idx if common_index is None else common_index.intersection(idx)
    common_index = common_index.sort_values()
    if len(common_index) < 5:
        raise ValueError("Not enough overlapping history to backtest")

    aligned = {s: df.reindex(common_index) for s, df in market_data.items()}

    cash = capital
    holdings = {}
    open_trades = {}
    closed_trades = []
    pnl_history = []

    for i, date in enumerate(common_index):
        sliced = {s: df.iloc[:i + 1] for s, df in aligned.items()}
        current_prices = {}
        for s, df in aligned.items():
            val = df["Close"].iloc[i]
            if pd.isna(val) or val <= 0:
                continue
            current_prices[s] = float(val)

        bot_state = {
            "id": None, "name": strategy_name, "strategy": strategy_name,
            "capital": capital, "cash": cash, "config": config,
            "holdings": [{"symbol": s, "quantity": h["quantity"], "avg_price": h["avg_price"],
                          "entry_date": h["entry_date"]}
                         for s, h in holdings.items()],
            # Alpha Vantage's free-tier rate limit (5 calls/min, 25/day) makes
            # it unusable for a strategy looping over dozens of symbols once
            # per simulated day — fundamental/sentiment use this to skip
            # straight to their (fast, parallelized) yfinance path instead.
            "is_backtest": True,
        }

        try:
            signals = strategy.generate_signals(bot_state, sliced)
        except Exception:
            signals = []

        for sig in signals:
            sym, side, qty, price = sig[:4]
            if qty <= 0:
                continue
            if side == "buy":
                exec_price = price * (1 + SLIPPAGE)
                gross = exec_price * qty
                commission = gross * COMMISSION
                total_cost = gross + commission
                if cash < total_cost:
                    max_gross = cash / (1 + COMMISSION + SLIPPAGE)
                    qty = max_gross / exec_price
                    if qty <= 1e-8:
                        continue
                    gross = exec_price * qty
                    commission = gross * COMMISSION
                    total_cost = gross + commission
                cash -= total_cost
                h = holdings.get(sym, {"quantity": 0.0, "avg_price": 0.0, "entry_date": date})
                new_qty = h["quantity"] + qty
                new_avg = (h["quantity"] * h["avg_price"] + qty * exec_price) / new_qty
                holdings[sym] = {"quantity": new_qty, "avg_price": new_avg, "entry_date": h["entry_date"]}
                open_trades.setdefault(sym, []).append({"quantity": qty, "entry_price": exec_price})
            else:
                h = holdings.get(sym)
                if not h or h["quantity"] <= 0:
                    continue
                exec_price = price * (1 - SLIPPAGE)
                qty = min(qty, h["quantity"])
                gross = exec_price * qty
                commission = gross * COMMISSION
                cash += gross - commission
                new_qty = h["quantity"] - qty
                if new_qty <= 1e-8:
                    del holdings[sym]
                else:
                    holdings[sym] = {"quantity": new_qty, "avg_price": h["avg_price"], "entry_date": h["entry_date"]}
                trades_list = open_trades.get(sym)
                if trades_list:
                    entry = trades_list.pop()
                    pnl = (exec_price - entry["entry_price"]) * entry["quantity"]
                    closed_trades.append({"symbol": sym, "pnl": pnl})

        holdings_value = sum(h["quantity"] * current_prices.get(s, h["avg_price"]) for s, h in holdings.items())
        tv = cash + holdings_value
        pnl_history.append({"date": str(date.date()), "value": round(tv, 2) if not pd.isna(tv) else pnl_history[-1]["value"] if pnl_history else capital})

    values = [p["value"] for p in pnl_history]
    values_arr = np.asarray(values, dtype=float)
    daily_returns = np.diff(values_arr) / values_arr[:-1] if len(values_arr) > 1 else np.array([])
    final_value = values[-1] if values else capital
    final_value = final_value if not pd.isna(final_value) else capital
    total_return_pct = (final_value - capital) / capital * 100 if capital else 0.0

    return {
        "strategy": strategy_name, "period": period,
        "start_date": str(common_index[0].date()), "end_date": str(common_index[-1].date()),
        "initial_capital": capital, "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "sharpe_ratio": calc_sharpe(daily_returns),
        "max_drawdown_pct": calc_max_drawdown(values),
        "win_rate": calc_win_rate(closed_trades),
        "total_trades": len(closed_trades),
        "pnl_history": pnl_history,
    }