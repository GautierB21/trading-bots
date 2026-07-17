#!/usr/bin/env python3
"""One-time migration: convert existing open positions' avg_price from
native listing currency to EUR, to match the fx.py fix in data_fetcher.py
and intraday/scheduler.py. Run once after deploying that fix.

Backs up both DBs before writing. Safe to re-run (a position already in
EUR — currency == "EUR" — is a no-op; but running it TWICE on a position
already migrated would double-convert, so only run this once per deploy).
"""
import shutil
import sqlite3
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src import fx

TRADING_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trading.db")
INTRADAY_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "intraday.db")


def backup(path):
    stamp = time.strftime("%Y%m%d%H%M%S")
    dst = f"{path}.backup-fx-migration-{stamp}"
    shutil.copy2(path, dst)
    print(f"backed up {path} -> {dst}")


def migrate_trading_db():
    conn = sqlite3.connect(TRADING_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, symbol, avg_price FROM holdings WHERE quantity > 0").fetchall()
    updated = 0
    for r in rows:
        ccy = fx.get_symbol_currency(r["symbol"])
        if ccy == "EUR":
            continue
        rate = fx.get_fx_rate(ccy)
        new_price = r["avg_price"] * rate
        conn.execute("UPDATE holdings SET avg_price=? WHERE id=?", (new_price, r["id"]))
        print(f"trading.db  {r['symbol']:15} {ccy:4} avg_price {r['avg_price']:12.4f} -> {new_price:12.4f}")
        updated += 1
    conn.commit()
    conn.close()
    print(f"trading.db: {updated} holdings migrated\n")


def migrate_intraday_db():
    conn = sqlite3.connect(INTRADAY_DB)
    conn.row_factory = sqlite3.Row
    usd_rate = fx.get_fx_rate("USD")
    rows = conn.execute("SELECT id, bot_name, symbol, avg_price FROM intraday_positions WHERE quantity > 0").fetchall()
    for r in rows:
        new_price = r["avg_price"] * usd_rate
        conn.execute("UPDATE intraday_positions SET avg_price=? WHERE id=?", (new_price, r["id"]))
    conn.commit()
    conn.close()
    print(f"intraday.db: {len(rows)} positions migrated (USD->EUR rate={usd_rate:.6f})")


if __name__ == "__main__":
    backup(TRADING_DB)
    backup(INTRADAY_DB)
    migrate_trading_db()
    migrate_intraday_db()
    print("\nDone. Restart server.py / the intraday scheduler process now — "
          "strat.cash and strat.positions are only reloaded from DB on startup.")
