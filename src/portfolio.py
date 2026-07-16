import sqlite3
from datetime import datetime, timezone
from . import db

COMMISSION = 0.001   # 0.1%
SLIPPAGE   = 0.0005  # 0.05%


def _utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def calculate_value(bot_id, current_prices):
    """Return (total_value, holdings_value) given current_prices dict."""
    bot = db.get_bot(bot_id)
    if bot is None:
        return 0.0, 0.0

    cash = bot["cash"]
    holdings_value = 0.0
    for h in bot["holdings"]:
        price = current_prices.get(h["symbol"], h["avg_price"])
        holdings_value += h["quantity"] * price

    return cash + holdings_value, holdings_value


def execute_order(bot_id, symbol, side, quantity, signal_price):
    """
    Execute a paper trade with commission and slippage.
    Returns True if executed, False if rejected (insufficient funds).
    """
    conn = db.get_conn()
    try:
        # Apply slippage
        if side == "buy":
            exec_price = signal_price * (1 + SLIPPAGE)
        else:
            exec_price = signal_price * (1 - SLIPPAGE)

        gross = exec_price * quantity
        commission = gross * COMMISSION

        if side == "buy":
            total_cost = gross + commission
        else:
            total_cost = gross - commission  # proceeds after commission

        bot_row = conn.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
        if bot_row is None:
            return False

        cash = bot_row["cash"]

        if side == "buy":
            if cash < total_cost:
                # Scale down quantity to fit available cash
                max_gross = cash / (1 + COMMISSION + SLIPPAGE)
                quantity = max_gross / exec_price
                if quantity <= 1e-8:
                    return False
                gross = exec_price * quantity
                commission = gross * COMMISSION
                total_cost = gross + commission

            new_cash = cash - total_cost

            # Update holding
            h_row = conn.execute(
                "SELECT * FROM holdings WHERE bot_id=? AND symbol=?", (bot_id, symbol)
            ).fetchone()

            if h_row:
                old_qty = h_row["quantity"]
                old_avg = h_row["avg_price"]
                new_qty = old_qty + quantity
                new_avg = (old_qty * old_avg + quantity * exec_price) / new_qty
            else:
                new_qty = quantity
                new_avg = exec_price

            db.upsert_holding(bot_id, symbol, new_qty, new_avg, conn=conn)

            # Record open trade
            db.open_trade(bot_id, symbol, "buy", quantity, exec_price, _utcnow(), conn=conn)

        else:  # sell
            h_row = conn.execute(
                "SELECT * FROM holdings WHERE bot_id=? AND symbol=?", (bot_id, symbol)
            ).fetchone()

            if h_row is None or h_row["quantity"] < quantity:
                if h_row:
                    quantity = h_row["quantity"]
                else:
                    return False

            gross = exec_price * quantity
            commission = gross * COMMISSION
            total_cost = gross - commission

            new_cash = cash + total_cost
            new_qty = h_row["quantity"] - quantity
            new_avg = h_row["avg_price"] if new_qty > 0 else 0.0
            db.upsert_holding(bot_id, symbol, new_qty, new_avg, conn=conn)

            # Close the trade
            db.close_trade(bot_id, symbol, exec_price, _utcnow(), conn=conn)

        # Record order
        db.insert_order(bot_id, symbol, side, quantity, exec_price, gross, conn=conn)

        # Update cash
        db.update_bot_cash(bot_id, new_cash, conn=conn)

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        print(f"[portfolio] execute_order error: {e}")
        return False
    finally:
        conn.close()


def take_snapshot(bot_id, current_prices):
    """Record today's portfolio value snapshot."""
    total_value, holdings_value = calculate_value(bot_id, current_prices)
    bot = db.get_bot(bot_id)
    if bot is None:
        return

    cash = bot["cash"]
    capital = bot["capital"]
    pnl_total = total_value - capital
    pnl_percent = (pnl_total / capital) * 100 if capital > 0 else 0.0

    db.upsert_snapshot(
        bot_id,
        total_value,
        cash,
        holdings_value,
        pnl_total,
        pnl_percent,
        _today(),
    )


def get_portfolio_summary(bot_id, current_prices):
    """Return dict with full portfolio summary."""
    bot = db.get_bot(bot_id)
    if bot is None:
        return {}

    total_value, holdings_value = calculate_value(bot_id, current_prices)
    capital = bot["capital"]
    pnl_total = total_value - capital
    pnl_percent = (pnl_total / capital) * 100 if capital > 0 else 0.0

    holdings_detail = []
    for h in bot["holdings"]:
        price = current_prices.get(h["symbol"], h["avg_price"])
        market_value = h["quantity"] * price
        unrealized_pnl = (price - h["avg_price"]) * h["quantity"]
        unrealized_pct = (price - h["avg_price"]) / h["avg_price"] * 100 if h["avg_price"] else 0
        holdings_detail.append({
            "symbol": h["symbol"],
            "quantity": round(h["quantity"], 4),
            "avg_price": round(h["avg_price"], 4),
            "current_price": round(price, 4),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pct": round(unrealized_pct, 2),
        })

    return {
        "bot_id": bot_id,
        "name": bot["name"],
        "strategy": bot["strategy"],
        "capital": capital,
        "cash": round(bot["cash"], 2),
        "holdings_value": round(holdings_value, 2),
        "total_value": round(total_value, 2),
        "pnl_total": round(pnl_total, 2),
        "pnl_percent": round(pnl_percent, 2),
        "holdings": holdings_detail,
    }
