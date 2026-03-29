"""Date parsing utilities — adapted from Event_Finder/app/utils/date_parse.py."""
from __future__ import annotations
import re
from datetime import datetime
from typing import Optional

_TIME_ONLY = re.compile(r'^\d{1,2}:\d{2}(:\d{2})?(\s*[ap]m)?$', re.IGNORECASE)

_ACTIVITY_PATTERNS: list[tuple[str, list[str]]] = [
    ("weekly",    ["weekly", "every week", "every monday", "every tuesday",
                   "every wednesday", "every thursday", "every friday"]),
    ("monthly",   ["monthly", "every month", "first tuesday", "last thursday",
                   "once a month"]),
    ("recurring", ["regular", "recurring", "ongoing", "standing",
                   "bi-weekly", "biweekly", "fortnightly"]),
    ("one-off",   ["one-off", "single event", "one time", "special edition"]),
]


def parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    """Return a naive datetime from a raw string, or None if unparseable."""
    if not raw:
        return None
    raw = raw.strip()
    if not raw or _TIME_ONLY.match(raw):
        return None
    try:
        from dateutil import parser as _du
        return _du.parse(raw, fuzzy=True, dayfirst=False).replace(tzinfo=None)
    except Exception:
        return None


def infer_activity(text: str) -> Optional[str]:
    """Infer recurrence pattern from freeform text. Returns None if unclear."""
    t = text.lower()
    for activity, keywords in _ACTIVITY_PATTERNS:
        if any(kw in t for kw in keywords):
            return activity
    return None


def parse_cost_factor(cost_text: Optional[str]) -> Optional[float]:
    """
    Parse freeform cost text to a float.
      "Free" / "Kostenlos" → 0.0
      "€10"                → 10.0
      "€5 – €20"           → 12.5  (midpoint)
      Unknown              → None
    """
    if not cost_text:
        return None
    t = cost_text.strip().lower()
    if any(w in t for w in ("free", "kostenlos", "€0", "0 eur", "0€", "gratis")):
        return 0.0
    amounts = re.findall(r'[\d]+(?:[.,]\d+)?', t)
    if not amounts:
        return None
    floats = [float(a.replace(",", ".")) for a in amounts]
    return round(sum(floats) / len(floats), 2)
