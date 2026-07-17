#!/usr/bin/env python3
"""One-time reset: every bot was affected by the pre-fx-fix currency bug
(every bot holds at least some non-EUR symbol — USD stocks, USD ETFs, or
crypto), so partial migration of open positions isn't enough to trust the
historical P&L/Sharpe/drawdown numbers. This wipes all trading history and
resets capital/budget to 500EUR per bot (was 10000EUR daily / 300-400EUR
intraday), matching the code defaults already updated in
src/bot_manager.py:DEFAULT_BOTS and intraday/config.py:BOTS.

Backs up both DBs before writing. Irreversible without the backup.
"""
import shutil
import sqlite3
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

TRADING_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trading.db")
INTRADAY_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "intraday.db")

NEW_CAPITAL = 500.0


def backup(path):
    stamp = time.strftime("%Y%m%d%H%M%S")
    dst = f"{path}.backup-reset500-{stamp}"
    shutil.copy2(path, dst)
    print(f"backed up {path} -> {dst}")


def reset_trading_db():
    conn = sqlite3.connect(TRADING_DB)
    bots = conn.execute("SELECT id, name FROM bots").fetchall()
    for bot_id, name in bots:
        conn.execute("UPDATE bots SET capital=?, cash=? WHERE id=?", (NEW_CAPITAL, NEW_CAPITAL, bot_id))
        conn.execute("DELETE FROM holdings WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM orders WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM portfolio_snapshots WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM trades WHERE bot_id=?", (bot_id,))
        print(f"trading.db  reset {name} -> capital=cash={NEW_CAPITAL}, history cleared")
    conn.commit()
    conn.close()
    print(f"trading.db: {len(bots)} bots reset\n")


def reset_intraday_db():
    conn = sqlite3.connect(INTRADAY_DB)
    conn.execute("DELETE FROM intraday_trades")
    conn.execute("DELETE FROM intraday_positions")
    conn.execute("DELETE FROM intraday_snapshots")
    conn.commit()
    conn.close()
    print("intraday.db: trades/positions/snapshots cleared "
          "(cash resets to the new 500EUR budget on next scheduler restart, "
          "via _restore_state() recomputing from an empty trade history)")


if __name__ == "__main__":
    backup(TRADING_DB)
    backup(INTRADAY_DB)
    reset_trading_db()
    reset_intraday_db()
    print("\nDone. Restart server.py (and the intraday scheduler it runs) now.")
