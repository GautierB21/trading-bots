#!/usr/bin/env python3
import sys
import os
import argparse

# Ensure project root on path
sys.path.insert(0, os.path.dirname(__file__))

from src import db
from src import bot_manager, reporter, alerts


def cmd_init(args):
    print("Initializing database...")
    db.init_db()
    print("Creating default bots...")
    bot_manager.init_default_bots()
    print("\nDone. Run `python cli.py run` to execute all bots.")


def cmd_run(args):
    if args.bot:
        bot = db.get_bot(name=args.bot)
        if bot is None:
            print(f"Bot '{args.bot}' not found.")
            sys.exit(1)
        bot_manager.run_bot(bot["id"])
    else:
        results = bot_manager.run_all_bots()
        print(f"\nCompleted: {len(results)} bots run.")

    if alerts.is_configured():
        print("\nChecking alert conditions...")
        alert_results = alerts.check_and_send_all_alerts()
        sent_count = sum(len(v) for v in alert_results.values())
        print(f"  Sent {sent_count} Telegram alert(s).")
    else:
        print("\n(Telegram alerts not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable)")


def cmd_status(args):
    status = bot_manager.get_status()
    if not status:
        print("No bots found. Run `python cli.py init` first.")
        return

    print(f"\n{'Name':<20} {'Strategy':<22} {'Cash':>10} {'Holdings':>10} {'Total':>10} {'P&L':>10} {'P&L%':>8}")
    print("-" * 95)
    for name, s in status.items():
        sign = "+" if s["pnl_total"] >= 0 else ""
        print(
            f"{name:<20} {s['strategy']:<22} "
            f"${s['cash']:>9,.2f} ${s['holdings_value']:>9,.2f} "
            f"${s['total_value']:>9,.2f} {sign}${s['pnl_total']:>8,.2f} "
            f"{sign}{s['pnl_percent']:>6.2f}%"
        )


def cmd_report(args):
    days = args.days
    if args.bot:
        bot = db.get_bot(name=args.bot)
        if bot is None:
            print(f"Bot '{args.bot}' not found.")
            sys.exit(1)
        print(reporter.generate_bot_report(bot["id"], days=days))
    else:
        print(reporter.generate_daily_summary())


def cmd_leaderboard(args):
    print(reporter.generate_leaderboard())


def cmd_history(args):
    if args.bot:
        bot = db.get_bot(name=args.bot)
        if bot is None:
            print(f"Bot '{args.bot}' not found.")
            sys.exit(1)
        trades = db.get_trades(bot["id"], limit=50)
        orders = db.get_orders(bot["id"], limit=50)
        print(f"\n=== Trade History: {args.bot} ===")
        if trades:
            print(f"\n{'ID':<5} {'Symbol':<8} {'Side':<6} {'Qty':>10} {'Entry':>10} {'Exit':>10} {'P&L':>10} {'Status':<8}")
            print("-" * 70)
            for t in trades:
                pnl_str = f"${t['pnl']:.2f}" if t["pnl"] is not None else " open"
                exit_str = f"${t['exit_price']:.2f}" if t["exit_price"] else "   -"
                print(
                    f"{t['id']:<5} {t['symbol']:<8} {t['side']:<6} {t['quantity']:>10.4f} "
                    f"${t['entry_price']:>9.2f} {exit_str:>10} {pnl_str:>10} {t['status']:<8}"
                )
        else:
            print("  No trades found.")

        print(f"\n=== Order History: {args.bot} ===")
        if orders:
            print(f"\n{'ID':<5} {'Symbol':<8} {'Side':<6} {'Qty':>10} {'Price':>10} {'Total':>12} {'Date':<22}")
            print("-" * 75)
            for o in orders:
                print(
                    f"{o['id']:<5} {o['symbol']:<8} {o['side']:<6} {o['quantity']:>10.4f} "
                    f"${o['price']:>9.2f} ${o['total']:>11.2f} {o['executed_at']:<22}"
                )
        else:
            print("  No orders found.")
    else:
        bots = db.get_all_bots(active_only=False)
        for bot in bots:
            orders = db.get_orders(bot["id"], limit=10)
            print(f"\n[{bot['name']}] Last {len(orders)} orders:")
            for o in orders:
                print(f"  {o['side'].upper()} {o['quantity']:.4f} {o['symbol']} @ ${o['price']:.2f} on {o['executed_at']}")


def cmd_reset(args):
    if args.bot:
        ok = bot_manager.reset_bot(name=args.bot)
        if ok:
            print(f"Reset bot '{args.bot}' to initial state.")
        else:
            print(f"Bot '{args.bot}' not found.")
    else:
        confirm = input("Reset ALL bots? This deletes all trades and history. [y/N] ")
        if confirm.lower() == "y":
            bots = db.get_all_bots(active_only=False)
            for bot in bots:
                db.reset_bot(bot["id"])
                print(f"  Reset: {bot['name']}")
        else:
            print("Aborted.")


def cmd_add_bot(args):
    import json
    config = json.loads(args.config) if args.config else {}
    bot = bot_manager.create_bot(args.name, args.strategy, args.capital, config)
    print(f"Created bot '{args.name}' (id={bot['id']}) with strategy '{args.strategy}' and ${args.capital:,.2f} capital.")


def cmd_server(args):
    import server
    server.app.run(host="0.0.0.0", port=args.port, debug=False)


def main():
    parser = argparse.ArgumentParser(prog="cli.py", description="Paper Trading Bot CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize DB and create default bots")

    p_run = sub.add_parser("run", help="Run bots")
    p_run.add_argument("--bot", help="Run a specific bot by name")

    sub.add_parser("status", help="Show current portfolio status")

    p_report = sub.add_parser("report", help="Generate performance report")
    p_report.add_argument("--bot", help="Specific bot name")
    p_report.add_argument("--days", type=int, default=30, help="Days of history")

    sub.add_parser("leaderboard", help="Show bot performance ranking")

    p_history = sub.add_parser("history", help="Show trade/order history")
    p_history.add_argument("--bot", help="Specific bot name")

    p_reset = sub.add_parser("reset", help="Reset bot(s) to initial capital")
    p_reset.add_argument("--bot", help="Specific bot name (omit for all)")

    p_add = sub.add_parser("add-bot", help="Add a new bot")
    p_add.add_argument("name", help="Bot name")
    p_add.add_argument("--strategy", required=True, help="Strategy name")
    p_add.add_argument("--capital", type=float, default=10000.0)
    p_add.add_argument("--config", default="{}", help="JSON config string")

    p_server = sub.add_parser("server", help="Start dashboard API server")
    p_server.add_argument("--port", type=int, default=5000)

    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "run": cmd_run,
        "status": cmd_status,
        "report": cmd_report,
        "leaderboard": cmd_leaderboard,
        "history": cmd_history,
        "reset": cmd_reset,
        "add-bot": cmd_add_bot,
        "server": cmd_server,
    }

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
