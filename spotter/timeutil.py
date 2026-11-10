from __future__ import annotations
import re
from datetime import datetime, timezone

_RX = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$")


def parse_ts(s) -> datetime | None:
    """Parse an ISO timestamp (any fractional precision) into an aware UTC datetime."""
    if isinstance(s, (int, float)):
        return datetime.fromtimestamp(s if s < 1e11 else s / 1000, timezone.utc)
    if not s or not isinstance(s, str):
        return None
    m = _RX.match(s.strip())
    if not m:
        return None
    head, frac, tz = m.groups()
    tz = "+00:00" if tz in (None, "Z") else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
    try:
        return datetime.fromisoformat(f"{head}.{(frac or '0')[:6].ljust(6, '0')}{tz}").astimezone(timezone.utc)
    except ValueError:
        return None
