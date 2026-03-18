from datetime import datetime
from zoneinfo import ZoneInfo

# Define West Africa Time (WAT) / Africa/Lagos
WAT = ZoneInfo("Africa/Lagos")

def get_now_wat() -> datetime:
    """Returns the current time in WAT."""
    return datetime.now(WAT)

def get_today_wat_str() -> str:
    """Returns current date in WAT as YYYY-MM-DD."""
    return get_now_wat().strftime("%Y-%m-%d")

def to_wat(dt_utc: datetime) -> datetime:
    """Converts a UTC datetime to WAT."""
    if dt_utc.tzinfo is None:
        # Assume naive datetime is UTC
        dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
    return dt_utc.astimezone(WAT)
