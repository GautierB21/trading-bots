"""Risk/performance metrics for bots and backtests."""
import numpy as np

TRADING_DAYS = 252


def calc_sharpe(daily_returns, risk_free_rate=0.05):
    """Annualized Sharpe ratio from a daily return series."""
    daily_returns = np.asarray(daily_returns, dtype=float)
    daily_returns = daily_returns[~np.isnan(daily_returns)]
    if len(daily_returns) < 2:
        return 0.0
    std = np.std(daily_returns, ddof=1)
    if std == 0:
        return 0.0
    mean_annual = np.mean(daily_returns) * TRADING_DAYS
    vol_annual = std * np.sqrt(TRADING_DAYS)
    return round(float((mean_annual - risk_free_rate) / vol_annual), 4)


def calc_max_drawdown(values):
    """Maximum drawdown (%) from a portfolio value series."""
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) < 2:
        return 0.0
    running_peak = np.maximum.accumulate(values)
    running_peak[running_peak == 0] = np.nan
    drawdowns = (values - running_peak) / running_peak
    drawdowns = drawdowns[~np.isnan(drawdowns)]
    if len(drawdowns) == 0:
        return 0.0
    return round(float(np.min(drawdowns) * 100), 2)


def calc_win_rate(trades):
    """Percentage of closed trades with positive P&L."""
    closed = [t for t in trades if t.get("pnl") is not None]
    if not closed:
        return 0.0
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return round(wins / len(closed) * 100, 2)


def calc_volatility(daily_returns):
    """Annualized volatility (%) from daily returns."""
    daily_returns = np.asarray(daily_returns, dtype=float)
    daily_returns = daily_returns[~np.isnan(daily_returns)]
    if len(daily_returns) < 2:
        return 0.0
    std = np.std(daily_returns, ddof=1)
    return round(float(std * np.sqrt(TRADING_DAYS) * 100), 2)


def calc_var(daily_returns, confidence=0.95):
    """Historical Value at Risk (%) at the given confidence level."""
    daily_returns = np.asarray(daily_returns, dtype=float)
    daily_returns = daily_returns[~np.isnan(daily_returns)]
    if len(daily_returns) == 0:
        return 0.0
    percentile = (1 - confidence) * 100
    var = np.percentile(daily_returns, percentile)
    return round(float(-var * 100), 2)


def bot_metrics(bot_id):
    """All risk metrics for a bot.

    Returns dict with sharpe, max_drawdown, win_rate, volatility, var_95,
    total_trades, win_count, loss_count.
    """
    from . import db

    snapshots = db.get_snapshots(bot_id, days=36500)
    values = [s["total_value"] for s in snapshots]
    if len(values) > 1:
        values_arr = np.asarray(values, dtype=float)
        daily_returns = np.diff(values_arr) / values_arr[:-1]
    else:
        daily_returns = np.array([])

    trades = db.get_trades(bot_id, limit=100000)
    closed = [t for t in trades if t.get("pnl") is not None]
    win_count = sum(1 for t in closed if t["pnl"] > 0)
    loss_count = len(closed) - win_count

    return {
        "sharpe": calc_sharpe(daily_returns),
        "max_drawdown": calc_max_drawdown(values),
        "win_rate": calc_win_rate(trades),
        "volatility": calc_volatility(daily_returns),
        "var_95": calc_var(daily_returns, 0.95),
        "total_trades": len(trades),
        "win_count": win_count,
        "loss_count": loss_count,
    }
