import sys
sys.path.insert(0, ".")
from src.backtest import backtest_strategy

STRATEGY_TEMPLATES = {
    "sma_crossover": {
        "fast_period": 20, "slow_period": 50,
        "symbols": ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","JNJ","WMT","XOM","PG","KO","PEP",
                    "MC.PA","OR.PA","AIR.PA","BNP.PA","TTE.PA","SAN.PA","SAP.DE","SIE.DE","ALV.DE","BMW.DE",
                    "SHEL.L","HSBA.L","AZN.L","ULVR.L","7203.T","6758.T","9984.T","6861.T","8035.T",
                    "0700.HK","0001.HK","0005.HK"],
    },
    "rsi_mean_reversion": {
        "period": 14, "oversold": 30, "overbought": 70,
        "symbols": ["TSLA","NVDA","META","AMZN","NFLX","GME","COIN","PLTR","AMD","DIS","BA","DAL","UBER","SQ","PYPL","MRNA","BABA","JD",
                    "MC.PA","AIR.PA","BNP.PA","KER.PA","STMPA.PA","DGE.L","SIE.DE","SAP.DE","BMW.DE","VOW3.DE",
                    "SHEL.L","BARC.L","RIO.L","LLOY.L","9984.T","6861.T","8035.T","6758.T","0700.HK","1299.HK","2318.HK","9988.HK"],
    },
    "momentum": {
        "lookback": 20, "top_n": 3,
        "symbols": ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","JNJ","WMT","PG","MA","UNH","HD",
                    "DIS","NFLX","ADBE","CRM","INTC","CSCO","ORCL","IBM","XOM","CVX","KO","PEP","PFE","MRK","ABBV",
                    "BAC","C","GS","MS","AXP","AIG","CAT","GE","MCD","SBUX","NKE","BA","T","VZ","COST","LLY",
                    "NEE","TMO","SPGI","BLK","MC.PA","OR.PA","AIR.PA","BNP.PA","TTE.PA","SAN.PA","CS.PA","SU.PA",
                    "SAP.DE","SIE.DE","ALV.DE","BMW.DE","SHEL.L","HSBA.L","AZN.L","ULVR.L","7203.T","6758.T","9984.T",
                    "0700.HK","1299.HK","0001.HK","SPY","QQQ","EEM","VWO"],
    },
    "bollinger_bands": {
        "period": 20, "std_dev": 2,
        "symbols": ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","BAC","WMT","JNJ","XOM","CVX","KO",
                    "PEP","ORCL","INTC","CSCO","PFE","MRK","MCD","SBUX","NKE","BA","MC.PA","OR.PA","AIR.PA","BNP.PA",
                    "SAP.DE","SIE.DE","SHEL.L","AZN.L","7203.T","9984.T","0700.HK","1299.HK"],
    },
    "dca": {
        "amount_per_period": 100,
        "symbols": ["SPY","QQQ","IWM","EEM","VNQ","GLD","TLT","VWCE.DE","CW8.PA","ESE.PA","2800.HK"],
        "max_position": 10,
    },
    "pairs_trading": {
        "pairs": [
            {"symbol_a": "JPM", "symbol_b": "BAC"},
            {"symbol_a": "GS", "symbol_b": "MS"},
            {"symbol_a": "AAPL", "symbol_b": "MSFT"},
            {"symbol_a": "GOOGL", "symbol_b": "AMZN"},
            {"symbol_a": "XOM", "symbol_b": "CVX"},
            {"symbol_a": "KO", "symbol_b": "PEP"},
            {"symbol_a": "BNP.PA", "symbol_b": "ACA.PA"},
            {"symbol_a": "SAP.DE", "symbol_b": "SIE.DE"},
            {"symbol_a": "SHEL.L", "symbol_b": "BP.L"},
            {"symbol_a": "7203.T", "symbol_b": "7267.T"},
        ],
        "entry_zscore": 2.0, "exit_zscore": 0.5, "lookback": 20,
    },
    "fundamental": {
        "symbols": ["AAPL","MSFT","JPM","V","JNJ","WMT","PG","MA","UNH","HD","COST","LLY","ABBV","MRK","PEP",
                    "KO","MCD","SBUX","NKE","ORCL","CSCO","TXN","LOW","TGT","CAT","UPS","HON","AXP","BLK","SPGI",
                    "VZ","T","MC.PA","OR.PA","AIR.PA","BNP.PA","TTE.PA","SAN.PA","CS.PA","SU.PA","VIE.PA",
                    "SAP.DE","SIE.DE","ALV.DE","DTE.DE","SHEL.L","AZN.L","ULVR.L","HSBA.L","GSK.L","9984.T","9432.T","8058.T"],
        "min_market_cap": 10000000000, "max_pe_ratio": 25, "min_pe_ratio": 5,
        "min_roe": 10, "max_debt_to_equity": 1.5, "position_size_pct": 0.7,
    },
    "sentiment": {
        "symbols": ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","NFLX","DIS","BA","GM","UBER","XYZ",
                    "PYPL","COIN","PLTR","AMD","INTC","CSCO","ORCL","IBM","XOM","CVX","WMT","MCD","NKE","SBUX",
                    "PFE","MRNA","MC.PA","SAP.DE","9984.T","0700.HK"],
        "min_positive_ratio": 0.6, "max_negative_ratio": 0.4, "min_articles": 3, "position_size_pct": 0.5,
    },
}

strategies = ["sma_crossover", "rsi_mean_reversion", "momentum", "bollinger_bands", "dca", "pairs_trading", "fundamental", "sentiment"]

results = []
for name in strategies:
    cfg = STRATEGY_TEMPLATES[name]
    print(f"Running {name}...", file=sys.stderr)
    try:
        r = backtest_strategy(name, cfg, period="1y", capital=10000)
        results.append((name, r))
        print(f"  done: return={r['total_return_pct']}%", file=sys.stderr)
    except Exception as e:
        results.append((name, {"error": str(e)}))
        print(f"  FAILED: {e}", file=sys.stderr)

print("\n\n=== RESULTS TABLE ===")
header = f"{'Strategy':<20}{'Return %':>10}{'Sharpe':>10}{'MaxDD %':>10}{'WinRate %':>11}{'Trades':>8}"
print(header)
print("-" * len(header))
for name, r in results:
    if "error" in r:
        print(f"{name:<20}ERROR: {r['error']}")
    else:
        print(f"{name:<20}{r['total_return_pct']:>10}{r['sharpe_ratio']:>10}{r['max_drawdown_pct']:>10}{r['win_rate']:>11}{r['total_trades']:>8}")
