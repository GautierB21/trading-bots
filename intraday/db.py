import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "intraday.db")


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS intraday_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            interval_seconds INTEGER NOT NULL,
            open_time TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            UNIQUE(symbol, interval_seconds, open_time)
        );

        CREATE TABLE IF NOT EXISTS intraday_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            total REAL NOT NULL,
            commission REAL NOT NULL DEFAULT 0,
            reason TEXT,
            executed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS intraday_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            avg_price REAL NOT NULL,
            current_value REAL,
            unrealized_pnl REAL,
            UNIQUE(bot_name, symbol)
        );

        CREATE TABLE IF NOT EXISTS intraday_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL,
            total_value REAL NOT NULL,
            cash REAL NOT NULL,
            holdings_value REAL NOT NULL,
            pnl REAL NOT NULL,
            snapshot_time TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_candles_lookup
            ON intraday_candles(symbol, interval_seconds, open_time);
        CREATE INDEX IF NOT EXISTS idx_trades_bot
            ON intraday_trades(bot_name, executed_at);
        CREATE INDEX IF NOT EXISTS idx_snapshots_bot
            ON intraday_snapshots(bot_name, snapshot_time);
    """)
    conn.commit()
    try:
        conn.execute("ALTER TABLE intraday_trades ADD COLUMN commission REAL NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.close()


# ── Candles ──────────────────────────────────────────────────────────────────

def insert_candle(symbol, interval_seconds, open_time, open_, high, low, close, volume):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO intraday_candles (symbol, interval_seconds, open_time, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, interval_seconds, open_time) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume
        """, (symbol, interval_seconds, open_time, open_, high, low, close, volume))
        conn.commit()
    finally:
        conn.close()


def get_candles(symbol, interval_seconds, limit=100):
    """Ascending list of candle dicts (oldest first)."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM (
                SELECT open_time, open, high, low, close, volume
                FROM intraday_candles
                WHERE symbol=? AND interval_seconds=?
                ORDER BY open_time DESC
                LIMIT ?
            ) ORDER BY open_time ASC
        """, (symbol, interval_seconds, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def aggregate_candles(symbol, source_seconds, target_seconds, count):
    """Build one target-interval candle from the last `count` source-interval
    candles and upsert it. No-op if fewer than `count` source candles exist."""
    source = get_candles(symbol, source_seconds, limit=count)
    if len(source) < count:
        return None

    open_ = source[0]["open"]
    close = source[-1]["close"]
    high = max(c["high"] for c in source)
    low = min(c["low"] for c in source)
    volume = sum(c["volume"] for c in source)
    open_time = source[0]["open_time"]

    insert_candle(symbol, target_seconds, open_time, open_, high, low, close, volume)
    return open_time


# ── Trades ───────────────────────────────────────────────────────────────────

def insert_trade(bot_name, symbol, side, quantity, price, total, commission=0.0, reason=""):
    conn = get_conn()
    try:
        # Dedup: skip if same trade was inserted in the last 60 seconds.
        # ROUND() on both sides — stored quantity/price are full-precision
        # floats, so comparing them raw against pre-rounded parameters never
        # matched and this check silently never caught anything.
        dup = conn.execute(
            "SELECT id FROM intraday_trades WHERE bot_name=? AND symbol=? AND side=? "
            "AND ROUND(quantity, 6)=? AND ROUND(price, 2)=? AND executed_at > datetime('now','-60 seconds')",
            (bot_name, symbol, side, round(quantity, 6), round(price, 2))
        ).fetchone()
        if dup:
            conn.close()
            return

        conn.execute("""
            INSERT INTO intraday_trades (bot_name, symbol, side, quantity, price, total, commission, reason, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (bot_name, symbol, side, quantity, price, total, commission, reason, _utcnow()))
        conn.commit()
    finally:
        conn.close()


def get_trades(bot_name, limit=20):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM intraday_trades WHERE bot_name=?
            ORDER BY executed_at DESC LIMIT ?
        """, (bot_name, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_last_trade_time(bot_name):
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT executed_at FROM intraday_trades WHERE bot_name=?
            ORDER BY executed_at DESC LIMIT 1
        """, (bot_name,)).fetchone()
        return row["executed_at"] if row else None
    finally:
        conn.close()


def get_trade_total(bot_name, side):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(total), 0) FROM intraday_trades WHERE bot_name=? AND side=?",
            (bot_name, side),
        ).fetchone()
        return row[0] if row else 0.0
    finally:
        conn.close()


def get_commission_total(bot_name):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(commission), 0) FROM intraday_trades WHERE bot_name=?",
            (bot_name,),
        ).fetchone()
        return row[0] if row else 0.0
    finally:
        conn.close()


# ── Positions ────────────────────────────────────────────────────────────────

def upsert_position(bot_name, symbol, quantity, avg_price, current_value, unrealized_pnl):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO intraday_positions (bot_name, symbol, quantity, avg_price, current_value, unrealized_pnl)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(bot_name, symbol) DO UPDATE SET
                quantity=excluded.quantity, avg_price=excluded.avg_price,
                current_value=excluded.current_value, unrealized_pnl=excluded.unrealized_pnl
        """, (bot_name, symbol, quantity, avg_price, current_value, unrealized_pnl))
        conn.commit()
    finally:
        conn.close()


def get_positions(bot_name):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM intraday_positions WHERE bot_name=? AND quantity > 1e-9
        """, (bot_name,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Snapshots ────────────────────────────────────────────────────────────────

def insert_snapshot(bot_name, total_value, cash, holdings_value, pnl):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO intraday_snapshots (bot_name, total_value, cash, holdings_value, pnl, snapshot_time)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (bot_name, total_value, cash, holdings_value, pnl, _utcnow()))
        conn.commit()
    finally:
        conn.close()


def get_latest_snapshot(bot_name):
    conn = get_conn()
    try:
        row = conn.execute("""
            SELECT * FROM intraday_snapshots WHERE bot_name=?
            ORDER BY snapshot_time DESC LIMIT 1
        """, (bot_name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_snapshots(bot_name, limit=200):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM (
                SELECT * FROM intraday_snapshots WHERE bot_name=?
                ORDER BY snapshot_time DESC LIMIT ?
            ) ORDER BY snapshot_time ASC
        """, (bot_name, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
