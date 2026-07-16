from datetime import datetime, timezone
from . import db
from .data_fetcher import fetch_current_prices
from .portfolio import get_portfolio_summary
from .signal_analysis import analyze_bot_signals
from .time_utils import days_since
from .risk_metrics import bot_metrics


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def generate_leaderboard():
    rows = db.get_leaderboard()
    if not rows:
        return "No bots found.\n"

    lines = [
        "# Bot Leaderboard\n",
        f"*Generated: {_utcnow()}*\n",
        "",
        f"{'Rank':<5} {'Name':<20} {'Strategy':<22} {'Capital':>10} {'Value':>10} {'P&L':>10} {'P&L %':>8} {'Last Snapshot':<14}",
        "-" * 105,
    ]

    for i, row in enumerate(rows, 1):
        pnl = row["pnl_total"] or 0.0
        pnl_pct = row["pnl_percent"] or 0.0
        total_val = row["total_value"] or row["cash"]
        sign = "+" if pnl >= 0 else ""
        lines.append(
            f"{i:<5} {row['name']:<20} {row['strategy']:<22} "
            f"${row['capital']:>9,.2f} ${total_val:>9,.2f} "
            f"{sign}${pnl:>8,.2f} {sign}{pnl_pct:>6.2f}%  "
            f"{row['snapshot_date'] or 'never':<14}"
        )

    return "\n".join(lines)


def generate_bot_report(bot_id, days=30):
    bot = db.get_bot(bot_id)
    if bot is None:
        return f"Bot {bot_id} not found.\n"

    # Get current prices
    from .bot_manager import _collect_symbols
    symbols = _collect_symbols(bot)
    prices = fetch_current_prices(symbols) if symbols else {}

    summary = get_portfolio_summary(bot_id, prices)
    snapshots = db.get_snapshots(bot_id, days)
    trades = db.get_trades(bot_id, limit=20)

    lines = [
        f"# Bot Report: {bot['name']}",
        f"*Strategy: {bot['strategy']} | Generated: {_utcnow()}*\n",
        "## Portfolio Summary",
        f"- **Capital**: ${summary['capital']:,.2f}",
        f"- **Cash**: ${summary['cash']:,.2f}",
        f"- **Holdings Value**: ${summary['holdings_value']:,.2f}",
        f"- **Total Value**: ${summary['total_value']:,.2f}",
        f"- **P&L**: ${summary['pnl_total']:,.2f} ({summary['pnl_percent']:+.2f}%)",
        "",
        "## Holdings",
    ]

    if summary["holdings"]:
        lines.append(
            f"{'Symbol':<8} {'Qty':>10} {'Avg Price':>12} {'Current':>12} {'Value':>12} {'Unreal P&L':>14} {'%':>8}"
        )
        lines.append("-" * 80)
        for h in summary["holdings"]:
            sign = "+" if h["unrealized_pnl"] >= 0 else ""
            lines.append(
                f"{h['symbol']:<8} {h['quantity']:>10.4f} "
                f"${h['avg_price']:>11.2f} ${h['current_price']:>11.2f} "
                f"${h['market_value']:>11.2f} {sign}${h['unrealized_pnl']:>11.2f} "
                f"{sign}{h['unrealized_pct']:>6.2f}%"
            )
    else:
        lines.append("  No open holdings.")

    lines += ["", f"## Performance History (last {days} days)"]
    if snapshots:
        lines.append(f"{'Date':<12} {'Total Value':>12} {'Cash':>10} {'P&L':>10} {'P&L %':>8}")
        lines.append("-" * 55)
        for s in snapshots[-20:]:
            sign = "+" if s["pnl_total"] >= 0 else ""
            lines.append(
                f"{s['snapshot_date']:<12} ${s['total_value']:>11,.2f} "
                f"${s['cash']:>9,.2f} {sign}${s['pnl_total']:>8,.2f} "
                f"{sign}{s['pnl_percent']:>6.2f}%"
            )
    else:
        lines.append("  No snapshots yet.")

    metrics = bot_metrics(bot_id)
    lines += [
        "",
        "## Risk Metrics",
        f"- **Sharpe Ratio**: {metrics['sharpe']:.2f}",
        f"- **Max Drawdown**: {metrics['max_drawdown']:.2f}%",
        f"- **Win Rate**: {metrics['win_rate']:.2f}% ({metrics['win_count']}W / {metrics['loss_count']}L)",
        f"- **Volatility (annualized)**: {metrics['volatility']:.2f}%",
        f"- **VaR (95%)**: {metrics['var_95']:.2f}%",
        f"- **Total Trades**: {metrics['total_trades']}",
    ]

    lines += ["", "## Recent Trades (last 20)"]
    if trades:
        lines.append(
            f"{'Symbol':<8} {'Side':<6} {'Qty':>10} {'Entry':>10} {'Exit':>10} {'P&L':>10} {'Status':<8}"
        )
        lines.append("-" * 70)
        for t in trades:
            pnl_str = f"${t['pnl']:,.2f}" if t["pnl"] is not None else "  open"
            exit_str = f"${t['exit_price']:.2f}" if t["exit_price"] else "  -"
            sign = "+" if (t["pnl"] or 0) >= 0 else ""
            lines.append(
                f"{t['symbol']:<8} {t['side']:<6} {t['quantity']:>10.4f} "
                f"${t['entry_price']:>9.2f} {exit_str:>10} "
                f"{sign}{pnl_str:>10} {t['status']:<8}"
            )
    else:
        lines.append("  No trades yet.")

    return "\n".join(lines)


def _bot_no_trade_reason(bot):
    """Pick the most relevant reason a bot generated no signal today."""
    try:
        result = analyze_bot_signals(bot)
    except Exception as e:
        return f"signal analysis failed ({e})"

    analysis = result.get("analysis", [])
    if not analysis:
        return "no symbols configured"

    signals = [a for a in analysis if a["status"] == "signal"]
    if signals:
        return "signal generated but not executed (insufficient cash/holdings)"

    reasons = [a["reason"] for a in analysis if a["status"] == "no_signal"]
    if reasons:
        return reasons[0]

    return "insufficient market data"


def generate_daily_summary():
    rows = db.get_leaderboard()
    total_capital = sum(r["capital"] for r in rows)
    total_value = sum(r["total_value"] or r["cash"] for r in rows)
    total_pnl = total_value - total_capital

    traded_today, not_traded = [], []
    for r in rows:
        d = days_since(r.get("last_trade_date"))
        r["_days_since_trade"] = d
        if d == 0:
            traded_today.append(r)
        else:
            not_traded.append(r)

    movers = sorted(
        [r for r in rows if r.get("pnl_percent") is not None],
        key=lambda r: r["pnl_percent"],
        reverse=True,
    )

    lines = [
        f"# Daily Trading Summary — {_utcnow()}",
        "",
        f"**Total Capital**: ${total_capital:,.2f}",
        f"**Total Portfolio Value**: ${total_value:,.2f}",
        f"**Total P&L**: ${total_pnl:+,.2f} ({total_pnl / total_capital * 100:+.2f}%)",
        "",
        "## Traded Today",
    ]
    if traded_today:
        for r in traded_today:
            lines.append(f"  - {r['name']} ({r['strategy']})")
    else:
        lines.append("  - No bots traded today.")

    lines += ["", "## Did NOT Trade Today"]
    if not_traded:
        for r in not_traded:
            bot = db.get_bot(r["id"])
            reason = _bot_no_trade_reason(bot) if bot else "unknown"
            lines.append(f"  - {r['name']} ({r['strategy']}): {reason}")
    else:
        lines.append("  - All bots traded today.")

    lines += ["", "## Biggest P&L Movers"]
    if movers:
        best, worst = movers[0], movers[-1]
        lines.append(
            f"  - Best: {best['name']} {best['pnl_percent']:+.2f}% "
            f"(${(best['pnl_total'] or 0):+,.2f})"
        )
        lines.append(
            f"  - Worst: {worst['name']} {worst['pnl_percent']:+.2f}% "
            f"(${(worst['pnl_total'] or 0):+,.2f})"
        )
    else:
        lines.append("  - No snapshot data yet.")

    lines += ["", "## Days Since Last Trade"]
    for r in rows:
        d = r["_days_since_trade"]
        d_str = "never" if d is None else f"{d}d ago"
        lines.append(f"  - {r['name']}: {d_str}")

    lines += ["", generate_leaderboard()]
    return "\n".join(lines)
