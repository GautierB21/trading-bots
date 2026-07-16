import json
from . import db
from .data_fetcher import fetch_historical_data, fetch_current_prices
from .portfolio import execute_order, take_snapshot, get_portfolio_summary
from strategies import get_strategy


DEFAULT_BOTS = [
    {
        "name": "sma_crossover",
        "strategy": "sma_crossover",
        "capital": 10000.0,
        "config": {
            "fast_period": 20,
            "slow_period": 50,
            "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
        },
    },
    {
        "name": "rsi_reversion",
        "strategy": "rsi_mean_reversion",
        "capital": 10000.0,
        "config": {
            "period": 14,
            "oversold": 30,
            "overbought": 70,
            "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
        },
    },
    {
        "name": "momentum",
        "strategy": "momentum",
        "capital": 10000.0,
        "config": {
            "lookback": 20,
            "top_n": 3,
            "symbols": [
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
                "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD",
                "DIS", "NFLX", "ADBE", "CRM", "INTC",
            ],
        },
    },
    {
        "name": "bollinger",
        "strategy": "bollinger_bands",
        "capital": 10000.0,
        "config": {
            "period": 20,
            "std_dev": 2,
            "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"],
        },
    },
    {
        "name": "dca",
        "strategy": "dca",
        "capital": 10000.0,
        "config": {
            "amount_per_period": 100,
            "symbols": ["SPY", "QQQ"],
            "max_position": 10,
        },
    },
    {
        "name": "pairs",
        "strategy": "pairs_trading",
        "capital": 10000.0,
        "config": {
            "pairs": [
                {"symbol_a": "XOM", "symbol_b": "CVX"},
                {"symbol_a": "KO", "symbol_b": "PEP"},
            ],
            "entry_zscore": 2.0,
            "exit_zscore": 0.5,
            "lookback": 20,
        },
    },
    {
        "name": "fundamental",
        "strategy": "fundamental",
        "capital": 10000.0,
        "config": {
            "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "V", "JNJ"],
            "min_market_cap": 10000000000,
            "max_pe_ratio": 25,
            "min_pe_ratio": 5,
            "min_roe": 10,
            "max_debt_to_equity": 1.5,
            "position_size_pct": 0.7,
        },
    },
    {
        "name": "sentiment",
        "strategy": "sentiment",
        "capital": 10000.0,
        "config": {
            "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"],
            "min_positive_ratio": 0.6,
            "max_negative_ratio": 0.4,
            "min_articles": 3,
            "position_size_pct": 0.5,
        },
    },
]


def init_default_bots():
    existing = {b["name"] for b in db.get_all_bots(active_only=False)}
    for spec in DEFAULT_BOTS:
        if spec["name"] not in existing:
            db.create_bot(spec["name"], spec["strategy"], spec["capital"], spec["config"])
            print(f"  Created bot: {spec['name']} ({spec['strategy']})")
        else:
            print(f"  Bot already exists: {spec['name']}")


def _collect_symbols(bot):
    cfg = bot["config"]
    symbols = set()
    # Most strategies have a "symbols" key
    if "symbols" in cfg:
        symbols.update(cfg["symbols"])
    # Pairs trading has "pairs"
    if "pairs" in cfg:
        for pair in cfg["pairs"]:
            symbols.add(pair["symbol_a"])
            symbols.add(pair["symbol_b"])
    return list(symbols)


def run_bot(bot_id):
    bot = db.get_bot(bot_id)
    if bot is None:
        print(f"[bot_manager] Bot {bot_id} not found")
        return {"error": "bot not found"}

    if not bot["active"]:
        return {"skipped": "inactive"}

    print(f"\n[{bot['name']}] Running {bot['strategy']} strategy...")

    symbols = _collect_symbols(bot)
    if not symbols:
        print(f"[{bot['name']}] No symbols configured")
        return {"signals": 0}

    market_data = fetch_historical_data(symbols, period="1y", interval="1d")
    current_prices = {}
    for sym, df in market_data.items():
        if df is None or df.empty:
            continue
        closes = df["Close"].dropna()
        if closes.empty:
            continue
        current_prices[sym] = float(closes.iloc[-1])

    strategy = get_strategy(bot["strategy"])
    signals = strategy.generate_signals(bot, market_data)

    executed = 0
    for signal in signals:
        sym, side, qty, price = signal[:4]
        if qty <= 0:
            continue
        ok = execute_order(bot_id, sym, side, qty, price)
        if ok:
            print(f"  [{bot['name']}] {side.upper()} {qty:.4f} {sym} @ ${price:.2f}")
            executed += 1
        else:
            print(f"  [{bot['name']}] REJECTED {side.upper()} {qty:.4f} {sym} @ ${price:.2f}")

    # Refresh bot state after orders then snapshot
    take_snapshot(bot_id, current_prices)

    summary = get_portfolio_summary(bot_id, current_prices)
    print(f"  [{bot['name']}] Value: ${summary['total_value']:.2f} | P&L: {summary['pnl_percent']:.2f}%")

    return {"signals_generated": len(signals), "signals_executed": executed, "summary": summary}


def run_all_bots():
    bots = db.get_all_bots(active_only=True)
    results = {}
    for bot in bots:
        results[bot["name"]] = run_bot(bot["id"])
    return results


def create_bot(name, strategy, capital, config):
    if isinstance(config, str):
        config = json.loads(config)
    db.create_bot(name, strategy, capital, config)
    return db.get_bot(name=name)


def get_status():
    bots = db.get_all_bots(active_only=False)
    # Collect all symbols for price fetch
    all_symbols = set()
    for bot in bots:
        all_symbols.update(_collect_symbols(bot))

    current_prices = {}
    if all_symbols:
        current_prices = fetch_current_prices(list(all_symbols))

    status = {}
    for bot in bots:
        summary = get_portfolio_summary(bot["id"], current_prices)
        last_order = None
        orders = db.get_orders(bot["id"], limit=1)
        if orders:
            last_order = orders[0]
        summary["last_trade"] = last_order
        status[bot["name"]] = summary
    return status


def reset_bot(bot_id=None, name=None):
    if name:
        bot = db.get_bot(name=name)
        if bot:
            bot_id = bot["id"]
    if bot_id:
        db.reset_bot(bot_id)
        return True
    return False
