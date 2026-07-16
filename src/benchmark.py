import numpy as np
import yfinance as yf
import pandas as pd

def fetch_spy_returns(period="6mo"):
    """Download SPY daily returns for benchmarking."""
    spy = yf.download("SPY", period=period, interval="1d", progress=False)
    spy["return"] = spy["Close"].pct_change().dropna()
    return spy[["return"]]

def alpha_beta(bot_returns, benchmark_returns):
    """Calculate alpha (Jensens) and beta vs benchmark."""
    merged = pd.concat([bot_returns, benchmark_returns], axis=1).dropna()
    merged.columns = ["bot", "benchmark"]
    cov = np.cov(merged["bot"], merged["benchmark"])
    beta = cov[0][1] / cov[1][1]
    alpha = np.mean(merged["bot"]) - beta * np.mean(merged["benchmark"])
    # Information ratio
    tracking_error = np.std(merged["bot"] - beta * merged["benchmark"])
    ir = alpha / tracking_error if tracking_error > 0 else 0
    return {"alpha_daily": alpha, "beta": beta, "information_ratio": ir, "tracking_error": tracking_error}

def correlation_matrix(bot_histories):
    """Calculate correlation matrix between all bots.
    bot_histories: {strategy_name: {"date1": value, "date2": value, ...}}
    Returns DataFrame of correlation matrix.
    """
    dfs = {}
    for name, pnl in bot_histories.items():
        dfs[name] = pd.Series(pnl).pct_change().dropna()
    return pd.DataFrame(dfs).corr()
