"""Fail-closed freshness checks for trading state."""
from datetime import date, datetime, timedelta


def trading_days_old(data_date, today=None):
    """Number of weekdays elapsed since *data_date* (NSE holiday-safe enough)."""
    if not data_date:
        return None
    try:
        start = datetime.fromisoformat(str(data_date)[:10]).date()
    except ValueError:
        return None
    end = today or date.today()
    if start >= end:
        return 0
    return sum((start + timedelta(days=i)).weekday() < 5
               for i in range(1, (end - start).days + 1))


def freshness(data_date, today=None):
    age = trading_days_old(data_date, today)
    return {"data_date": str(data_date)[:10] if data_date else None,
            "trading_days_old": age,
            "stale": age is None or age > 1,
            "actionable": age is not None and age <= 1}
