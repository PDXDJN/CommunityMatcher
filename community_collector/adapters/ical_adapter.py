"""
iCal adapter — parses ICS calendar feeds from Berlin community spaces.

Covers two landmark Berlin tech/hacker organisations whose events are
otherwise invisible to the Meetup/Luma adapters:

  c-base    — Berlin's legendary hackerspace (Mitte / Treptow waterfront)
              https://c-base.org
              Feed: https://www.c-base.org/calendar/exported/c-base-events.ics

  CCC       — Chaos Computer Club (events linked from events.ccc.de)
              https://events.ccc.de
              Feed: https://events.ccc.de/calendar/events.ics

Both feeds are publicly accessible, no auth required. The adapter parses
VEVENT components and normalises them to the standard raw-dict format.

Usage note: Unlike Meetup/Luma, this adapter ignores `search_term` — it
returns the full feed regardless. Deduplication at the persistence layer
(source_url UNIQUE) prevents duplicates across runs.

Adding more ICS feeds: extend `_ICS_FEEDS` with (name, url, city) tuples.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from playwright.async_api import Browser  # kept for base class compat, not used

from community_collector.adapters.base import BaseSourceAdapter
from community_collector.config import CollectorConfig
from community_collector.utils.logging_utils import get_logger

log = get_logger("adapter.ical")

# (label, feed_url, city)  — add more Berlin community ICS feeds here
_ICS_FEEDS: list[tuple[str, str, str]] = [
    (
        "c-base",
        "https://www.c-base.org/calendar/exported/c-base-events.ics",
        "Berlin",
    ),
    (
        "ccc",
        "https://events.ccc.de/calendar/events.ics",
        "Berlin",
    ),
]

_HEADERS = {
    "User-Agent": "CommunityMatcher/1.0 (+https://github.com/community-matcher)",
    "Accept": "text/calendar, */*",
}


class ICalAdapter(BaseSourceAdapter):
    """
    ICS calendar feed adapter for Berlin community spaces.

    Each configured feed is fetched once per collection run. The `search_term`
    argument is stored on records (for provenance) but does not filter results —
    the full calendar is ingested and deduplication happens at the DB level.
    """
    source_name = "ical"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("ical.collect.start", term=search_term, feeds=len(_ICS_FEEDS))
        results: list[dict] = []

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            tasks = [
                _fetch_and_parse(client, label, url, city, search_term)
                for label, url, city in _ICS_FEEDS
            ]
            batches = await asyncio.gather(*tasks, return_exceptions=True)

        for i, batch in enumerate(batches):
            label = _ICS_FEEDS[i][0]
            if isinstance(batch, Exception):
                log.warning("ical.feed_failed", feed=label, error=str(batch))
            else:
                results.extend(batch)

        log.info("ical.collect.done", term=search_term, count=len(results))
        return results


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

async def _fetch_and_parse(
    client: httpx.AsyncClient,
    label: str,
    url: str,
    city: str,
    search_term: str,
) -> list[dict]:
    try:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("ical.fetch_failed", feed=label, url=url, error=str(exc))
        return []

    raw_text = resp.text
    records = _parse_ics(raw_text, label, city, search_term)
    log.info("ical.feed_ok", feed=label, count=len(records))
    return records


def _parse_ics(ics_text: str, label: str, city: str, search_term: str) -> list[dict]:
    """Parse ICS text and return a list of raw dicts."""
    try:
        from icalendar import Calendar
    except ImportError:
        log.error("ical.missing_dep", msg="pip install icalendar")
        return []

    try:
        cal = Calendar.from_ical(ics_text)
    except Exception as exc:
        log.warning("ical.parse_error", feed=label, error=str(exc))
        return []

    records: list[dict] = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        raw = _vevent_to_raw(component, label, city, search_term)
        if raw:
            records.append(raw)

    return records


def _vevent_to_raw(
    component, label: str, city: str, search_term: str
) -> Optional[dict]:
    """Convert a VEVENT icalendar component to a normaliser-compatible dict."""
    uid = str(component.get("UID") or "")
    summary = _ical_str(component.get("SUMMARY"))
    if not summary:
        return None

    # Build a stable source URL from UID (ICS events often lack a URL)
    url_raw = _ical_str(component.get("URL"))
    if not url_raw:
        # Construct a pseudo-URL so source_url is unique and stable
        safe_uid = uid.replace("/", "_").replace(":", "_").replace("@", "_")
        url_raw = f"https://{label}.org/event/{safe_uid}"

    # Datetimes — convert to ISO strings
    dtstart = component.get("DTSTART")
    dtend   = component.get("DTEND")
    dt_start_iso = _dt_to_iso(dtstart.dt if dtstart else None)
    dt_end_iso   = _dt_to_iso(dtend.dt   if dtend   else None)

    # Location / venue
    location_str = _ical_str(component.get("LOCATION"))
    description  = _ical_str(component.get("DESCRIPTION"))

    # Organizer
    organizer_raw = component.get("ORGANIZER")
    organizer_str = ""
    if organizer_raw:
        org = str(organizer_raw)
        # ORGANIZER is often "mailto:..." or CN=Name
        if "CN=" in org:
            organizer_str = org.split("CN=")[-1].split(";")[0].strip()
        elif org.startswith("mailto:"):
            organizer_str = org[7:]

    # Tags from CATEGORIES
    categories_raw = component.get("CATEGORIES")
    tags: list[str] = []
    if categories_raw:
        cats = categories_raw if isinstance(categories_raw, list) else [categories_raw]
        for cat in cats:
            for item in str(cat).split(","):
                t = item.strip().lower()
                if t:
                    tags.append(t)

    return {
        "url":             url_raw,
        "title":           summary,
        "description":     description or "",
        "organizer":       organizer_str or label,
        "community_name":  label,
        "venue":           location_str or "",
        "address":         location_str or "",
        "city":            city,
        "country":         "de",
        "is_online":       False,
        "cost_text":       None,
        "source_record_id": uid,
        "search_term":     search_term,
        "source":          "ical",
        "datetime_start":  dt_start_iso,
        "datetime_end":    dt_end_iso,
        "tags":            tags,
        # community_name drives the activity inference in normalization
        "activity":        "recurring" if not dt_start_iso else None,
    }


def _ical_str(val) -> str:
    """Safely convert an icalendar property value to a plain string."""
    if val is None:
        return ""
    return str(val).strip()


def _dt_to_iso(dt) -> Optional[str]:
    """Convert a date or datetime to an ISO 8601 string."""
    if dt is None:
        return None
    try:
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                # Assume Europe/Berlin for naive datetimes in German feeds
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        # date (not datetime) — convert to midnight UTC
        return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).isoformat()
    except Exception:
        return None
