"""Telegram alerting for bot performance events."""
import os
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def is_configured():
    return bool(BOT_TOKEN and CHAT_ID)


def send_alert(message):
    """Send a Telegram message. Returns True if sent, False otherwise."""
    if not is_configured():
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.ok
    except requests.RequestException as e:
        print(f"[alerts] Failed to send Telegram alert: {e}")
        return False


def check_and_send_bot_alerts(bot_id):
    """Check a bot's recent performance and send alerts for notable conditions.

    Conditions:
      - P&L moved > 5% (in absolute terms) since yesterday's snapshot
      - Drawdown from peak > 3%
      - No trade in 7+ days
    """
    if not is_configured():
        return []

    from . import db
    from .time_utils import days_since

    bot = db.get_bot(bot_id)
    if bot is None:
        return []

    sent = []
    snapshots = db.get_snapshots(bot_id, days=30)

    if len(snapshots) >= 2:
        today_pct = snapshots[-1]["pnl_percent"]
        yesterday_pct = snapshots[-2]["pnl_percent"]
        move = today_pct - yesterday_pct
        if abs(move) > 5:
            direction = "up" if move > 0 else "down"
            msg = f"📈 *{bot['name']}*: P&L moved {direction} {abs(move):.2f}% since yesterday (now {today_pct:+.2f}%)"
            if send_alert(msg):
                sent.append(msg)

    if snapshots:
        values = [s["total_value"] for s in snapshots]
        peak = max(values)
        current = values[-1]
        drawdown = (current - peak) / peak * 100 if peak > 0 else 0.0
        if drawdown < -3:
            msg = f"⚠️ *{bot['name']}*: Drawdown of {drawdown:.2f}% from peak (${peak:,.2f} → ${current:,.2f})"
            if send_alert(msg):
                sent.append(msg)

    orders = db.get_orders(bot_id, limit=1)
    last_order_date = orders[0]["executed_at"] if orders else None
    d = days_since(last_order_date)
    if d is None or d >= 7:
        since_str = "never" if d is None else f"{d} days"
        msg = f"💤 *{bot['name']}*: No trade in {since_str}"
        if send_alert(msg):
            sent.append(msg)

    return sent


def check_and_send_all_alerts():
    """Run alert checks across all active bots."""
    if not is_configured():
        return {}

    from . import db

    results = {}
    for bot in db.get_all_bots(active_only=True):
        results[bot["name"]] = check_and_send_bot_alerts(bot["id"])
    return results
