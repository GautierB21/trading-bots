"""Major central bank decision dates (FOMC, ECB Governing Council monetary
policy meetings) — used to skip opening *new* positions right around events
that move every asset at once for reasons no per-symbol technical/fundamental
signal can see coming. Existing positions are never touched by this: sells,
stops, and exits always still fire on an event day.

These lists are hand-maintained public data, not fetched from an API (no
free, reliable real-time source is wired into this project). Both central
banks publish their meeting calendar roughly a year ahead — refresh this
list from federalreserve.gov/monetarypolicy and ecb.europa.eu/press/calendars
whenever it runs short, ideally once a year.
"""
import datetime

# FOMC decision dates (second day of each 2-day meeting, when the rate
# decision is announced).
FOMC_DATES = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

# ECB Governing Council monetary policy meeting dates (decision announcement day).
ECB_DATES = [
    "2025-01-30", "2025-03-06", "2025-04-17", "2025-06-05",
    "2025-07-24", "2025-09-11", "2025-10-30", "2025-12-18",
    "2026-01-29", "2026-03-05", "2026-04-16", "2026-06-04",
    "2026-07-23", "2026-09-10", "2026-10-29", "2026-12-17",
]

_ALL_EVENT_DATES = sorted(set(
    datetime.date.fromisoformat(d) for d in FOMC_DATES + ECB_DATES
))


def is_macro_event_day(as_of=None, window_days=0):
    """True if `as_of` (default: today) falls on, or within `window_days` of,
    a major central bank decision date. window_days=0 means "the event day
    itself only" — the decision and the immediate volatility spike, not the
    run-up to it."""
    if as_of is None:
        as_of = datetime.date.today()
    elif isinstance(as_of, str):
        as_of = datetime.date.fromisoformat(as_of[:10])
    elif hasattr(as_of, "date"):
        as_of = as_of.date()

    for event_date in _ALL_EVENT_DATES:
        if abs((as_of - event_date).days) <= window_days:
            return True
    return False


def next_macro_event(as_of=None):
    """Next event date at/after `as_of` (default: today), or None if the
    hardcoded calendar hasn't been refreshed far enough ahead."""
    if as_of is None:
        as_of = datetime.date.today()
    elif isinstance(as_of, str):
        as_of = datetime.date.fromisoformat(as_of[:10])
    upcoming = [d for d in _ALL_EVENT_DATES if d >= as_of]
    return upcoming[0] if upcoming else None
