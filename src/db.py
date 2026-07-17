import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trading.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            strategy TEXT NOT NULL,
            capital REAL NOT NULL DEFAULT 10000.0,
            cash REAL NOT NULL,
            config TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER REFERENCES bots(id),
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            avg_price REAL NOT NULL,
            entry_date TEXT,
            UNIQUE(bot_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER REFERENCES bots(id),
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('buy','sell')),
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            total REAL NOT NULL,
            status TEXT DEFAULT 'executed' CHECK(status IN ('pending','executed','cancelled')),
            executed_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER REFERENCES bots(id),
            total_value REAL NOT NULL,
            cash REAL NOT NULL,
            holdings_value REAL NOT NULL,
            pnl_total REAL NOT NULL,
            pnl_percent REAL NOT NULL,
            snapshot_date TEXT NOT NULL,
            UNIQUE(bot_id, snapshot_date)
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER REFERENCES bots(id),
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            pnl_percent REAL,
            entry_date TEXT,
            exit_date TEXT,
            status TEXT DEFAULT 'open' CHECK(status IN ('open','closed'))
        );
    """)
    try:
        c.execute("ALTER TABLE holdings ADD COLUMN entry_date TEXT")
    except sqlite3.OperationalError:
        pass  # already exists
    conn.commit()
    conn.close()


# ── Bots ──────────────────────────────────────────────────────────────────────

def create_bot(name, strategy, capital, config):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO bots (name, strategy, capital, cash, config) VALUES (?,?,?,?,?)",
            (name, strategy, capital, capital, json.dumps(config)),
        )
        conn.commit()
    finally:
        conn.close()


def get_bot(bot_id=None, name=None):
    conn = get_conn()
    try:
        if bot_id is not None:
            row = conn.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM bots WHERE name=?", (name,)).fetchone()
        if row is None:
            return None
        bot = dict(row)
        bot["config"] = json.loads(bot["config"] or "{}")
        bot["holdings"] = get_holdings(bot["id"], conn=conn)
        return bot
    finally:
        conn.close()


def get_all_bots(active_only=True):
    conn = get_conn()
    try:
        if active_only:
            rows = conn.execute("SELECT * FROM bots WHERE active=1").fetchall()
        else:
            rows = conn.execute("SELECT * FROM bots").fetchall()
        bots = []
        for row in rows:
            bot = dict(row)
            bot["config"] = json.loads(bot["config"] or "{}")
            bot["holdings"] = get_holdings(bot["id"], conn=conn)
            bots.append(bot)
        return bots
    finally:
        conn.close()


def update_bot_cash(bot_id, cash, conn=None):
    close = conn is None
    if close:
        conn = get_conn()
    conn.execute("UPDATE bots SET cash=? WHERE id=?", (cash, bot_id))
    if close:
        conn.commit()
        conn.close()


def set_bot_active(bot_id, active):
    conn = get_conn()
    conn.execute("UPDATE bots SET active=? WHERE id=?", (1 if active else 0, bot_id))
    conn.commit()
    conn.close()


def reset_bot(bot_id):
    conn = get_conn()
    try:
        bot = dict(conn.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone())
        conn.execute("UPDATE bots SET cash=? WHERE id=?", (bot["capital"], bot_id))
        conn.execute("DELETE FROM holdings WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM orders WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM portfolio_snapshots WHERE bot_id=?", (bot_id,))
        conn.execute("DELETE FROM trades WHERE bot_id=?", (bot_id,))
        conn.commit()
    finally:
        conn.close()


# ── Holdings ──────────────────────────────────────────────────────────────────

def get_holdings(bot_id, conn=None):
    close = conn is None
    if close:
        conn = get_conn()
    rows = conn.execute("SELECT * FROM holdings WHERE bot_id=?", (bot_id,)).fetchall()
    result = [dict(r) for r in rows]
    if close:
        conn.close()
    return result


def upsert_holding(bot_id, symbol, quantity, avg_price, entry_date=None, conn=None):
    """entry_date is only used on a fresh INSERT (new position) — the
    ON CONFLICT branch deliberately omits it so averaging into an existing
    position never resets when it was originally opened. Needed for
    max-holding-period exits (rsi_mean_reversion)."""
    close = conn is None
    if close:
        conn = get_conn()
    if quantity <= 0:
        conn.execute("DELETE FROM holdings WHERE bot_id=? AND symbol=?", (bot_id, symbol))
    else:
        conn.execute(
            """INSERT INTO holdings (bot_id, symbol, quantity, avg_price, entry_date)
               VALUES (?,?,?,?,COALESCE(?, datetime('now')))
               ON CONFLICT(bot_id, symbol) DO UPDATE SET quantity=excluded.quantity, avg_price=excluded.avg_price""",
            (bot_id, symbol, quantity, avg_price, entry_date),
        )
    if close:
        conn.commit()
        conn.close()


# ── Orders ────────────────────────────────────────────────────────────────────

def insert_order(bot_id, symbol, side, quantity, price, total, conn=None):
    close = conn is None
    if close:
        conn = get_conn()
    conn.execute(
        "INSERT INTO orders (bot_id, symbol, side, quantity, price, total) VALUES (?,?,?,?,?,?)",
        (bot_id, symbol, side, quantity, price, total),
    )
    if close:
        conn.commit()
        conn.close()


def get_orders(bot_id, limit=50):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM orders WHERE bot_id=? ORDER BY executed_at DESC LIMIT ?",
            (bot_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Snapshots ─────────────────────────────────────────────────────────────────

def upsert_snapshot(bot_id, total_value, cash, holdings_value, pnl_total, pnl_percent, snapshot_date):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO portfolio_snapshots
               (bot_id, total_value, cash, holdings_value, pnl_total, pnl_percent, snapshot_date)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(bot_id, snapshot_date) DO UPDATE SET
               total_value=excluded.total_value, cash=excluded.cash,
               holdings_value=excluded.holdings_value, pnl_total=excluded.pnl_total,
               pnl_percent=excluded.pnl_percent""",
            (bot_id, total_value, cash, holdings_value, pnl_total, pnl_percent, snapshot_date),
        )
        conn.commit()
    finally:
        conn.close()


def get_snapshots(bot_id, days=30):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM portfolio_snapshots WHERE bot_id=?
               AND snapshot_date >= date('now', ?)
               ORDER BY snapshot_date ASC""",
            (bot_id, f"-{days} days"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Trades ────────────────────────────────────────────────────────────────────

def open_trade(bot_id, symbol, side, quantity, entry_price, entry_date, conn=None):
    close = conn is None
    if close:
        conn = get_conn()
    conn.execute(
        """INSERT INTO trades (bot_id, symbol, side, quantity, entry_price, entry_date, status)
           VALUES (?,?,?,?,?,?,'open')""",
        (bot_id, symbol, side, quantity, entry_price, entry_date),
    )
    if close:
        conn.commit()
        conn.close()


def close_trade(bot_id, symbol, exit_price, exit_date, conn=None):
    """Close the most recent open buy trade for this symbol and compute P&L."""
    close_conn = conn is None
    if close_conn:
        conn = get_conn()

    row = conn.execute(
        """SELECT * FROM trades WHERE bot_id=? AND symbol=? AND side='buy' AND status='open'
           ORDER BY entry_date DESC LIMIT 1""",
        (bot_id, symbol),
    ).fetchone()

    if row:
        trade = dict(row)
        pnl = (exit_price - trade["entry_price"]) * trade["quantity"]
        pnl_pct = (exit_price - trade["entry_price"]) / trade["entry_price"] * 100
        conn.execute(
            """UPDATE trades SET exit_price=?, exit_date=?, pnl=?, pnl_percent=?, status='closed'
               WHERE id=?""",
            (exit_price, exit_date, pnl, pnl_pct, trade["id"]),
        )

    if close_conn:
        conn.commit()
        conn.close()


def get_trades(bot_id, limit=500, start_date=None, end_date=None):
    conn = get_conn()
    try:
        query = "SELECT * FROM trades WHERE bot_id=?"
        params = [bot_id]
        if start_date:
            query += " AND entry_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND entry_date <= ?" 
            params.append(end_date)
        query += " ORDER BY entry_date DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Leaderboard ───────────────────────────────────────────────────────────────

def get_leaderboard():
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT b.id, b.name, b.strategy, b.capital, b.cash,
                   ps.total_value, ps.pnl_total, ps.pnl_percent, ps.snapshot_date,
                   (SELECT MAX(executed_at) FROM orders WHERE bot_id = b.id) AS last_trade_date
            FROM bots b
            LEFT JOIN portfolio_snapshots ps ON ps.bot_id = b.id
                AND ps.snapshot_date = (
                    SELECT MAX(snapshot_date) FROM portfolio_snapshots WHERE bot_id = b.id
                )
            WHERE b.active=1
            ORDER BY COALESCE(ps.pnl_percent, 0) DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_portfolio_daily_totals(days=7):
    """Sum of every active bot's total_value per snapshot_date, most recent
    `days` calendar days — the input to the portfolio-level circuit breaker
    (aggregate P&L across all bots, not any single bot's drawdown)."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT ps.snapshot_date, SUM(ps.total_value) AS total
            FROM portfolio_snapshots ps
            JOIN bots b ON b.id = ps.bot_id
            WHERE b.active=1 AND ps.snapshot_date >= date('now', ?)
            GROUP BY ps.snapshot_date
            ORDER BY ps.snapshot_date
        """, (f"-{days} days",)).fetchall()
        return [r["total"] for r in rows]
    finally:
        conn.close()


def get_bot_performance(bot_id, days=30):
    return get_snapshots(bot_id, days)


def get_last_run_time():
    conn = get_conn()
    try:
        row = conn.execute("SELECT MAX(snapshot_date) AS last_run FROM portfolio_snapshots").fetchone()
        return row["last_run"] if row else None
    finally:
        conn.close()
