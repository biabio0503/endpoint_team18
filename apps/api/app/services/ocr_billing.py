"""Cloud billing periods: Pacific calendar months, including IANA DST rules."""
from datetime import datetime
from zoneinfo import ZoneInfo

BILLING_TIMEZONE = 'America/Los_Angeles'


def billing_period(at):
    """Accept an aware timestamp or SQLite ISO timestamp; never infer a timezone."""
    if isinstance(at, str):
        at = datetime.fromisoformat(at)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('OCR usage timestamps must include a timezone')
    return at.astimezone(ZoneInfo(BILLING_TIMEZONE)).strftime('%Y-%m')
