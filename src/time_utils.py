from datetime import datetime, timezone


def days_since(date_str):
    """date_str like 'YYYY-MM-DD HH:MM:SS' (UTC) or None. Returns int days or None."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).days
