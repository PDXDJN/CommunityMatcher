"""
Lu.ma adapter — API-based (no browser required).

Uses Luma's internal api2.luma.com endpoint discovered by intercepting browser
network traffic. No API key or authentication required.

Replaces the previous Playwright-based approach:
  OLD: launch browser → navigate calendars/discover → scroll 6× → harvest <a> anchors
         → title only, no description, no datetime, no venue, slow (~30s+)
  NEW: httpx GET to api2.luma.com → full structured data with pagination
         → title + description + datetime + venue + organizer + RSVP count, fast

Architecture follows the Meetup adapter pattern (same project).
Reference: github.com/glowingkitty/OpenMates/blob/main/backend/apps/events/providers/luma.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

import httpx
from playwright.async_api import Browser  # kept for base class compat, not used

from community_collector.adapters.base import BaseSourceAdapter
from community_collector.config import CollectorConfig
from community_collector.utils.logging_utils import get_logger

log = get_logger("adapter.luma")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_BASE = "https://api2.luma.com"
_EVENTS_ENDPOINT = f"{_API_BASE}/discover/get-paginated-events"

_MAX_PAGE_SIZE = 40       # Luma's max per-page (empirically confirmed)
_PAGE_DELAY_SECONDS = 1.2 # Polite inter-page delay
_HTTP_TIMEOUT = 20.0
_MAX_DESCRIPTION_CHARS = 2000

_HEADERS_JSON = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://luma.com",
    "Referer": "https://luma.com/discover",
}

_HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# City slug → discover_place_api_id mapping.
# Source: GET api2.luma.com/discover/bootstrap-page (scraped March 2026, 78 cities).
_CITY_PLACE_IDS: dict[str, str] = {
    "berlin":        "discplace-gCfX0s3E9Hgo3rG",
    "hamburg":       "discplace-kFH1oo7VN0HmF4E",
    "munich":        "discplace-4bTrg3iQ3rfv3a9",
    "vienna":        "discplace-v9JQWP1l4KJGfOZ",
    "amsterdam":     "discplace-R1gEkZRLUTG3bBX",
    "london":        "discplace-AQ5IMCGOOTyNRue",
    "paris":         "discplace-IK8LsBfq0oRHKTj",
    "zurich":        "discplace-1HZTRY0ZijTqV2c",
    "barcelona":     "discplace-H3dAFV5WDGCjJZ7",
    "madrid":        "discplace-03jiEcS4mvwJuDa",
    "lisbon":        "discplace-mgGFFo5EDdyekyE",
    "stockholm":     "discplace-e7EG0Ef6S2aQnvN",
    "copenhagen":    "discplace-CmmHAjPdBSsqmJf",
    "prague":        "discplace-jWzqmfVkPFSf2vB",
    "warsaw":        "discplace-BSpBjLlnFdGp6E5",
    "brussels":      "discplace-jlBIvqwnuCzJM3c",
    "milan":         "discplace-dRAGxr11HCxJnO0",
    "rome":          "discplace-YfRz2KSnQ7xhcJu",
    "dublin":        "discplace-bRGm0QsXOl5Kk3b",
    "istanbul":      "discplace-QNBFkOSR6m7OjpH",
    "dubai":         "discplace-d3kg1aLIJ5ROF6S",
    "singapore":     "discplace-mUbtdfNjfWaLQ72",
    "tokyo":         "discplace-9H7asQEvWiv6DA9",
    "sydney":        "discplace-TPdKGPI56hGfOdi",
    "nyc":           "discplace-Izx1rQVSh8njYpP",
    "new-york":      "discplace-Izx1rQVSh8njYpP",
    "san-francisco": "discplace-BDj7GNbGlsF7Cka",
    "sf":            "discplace-BDj7GNbGlsF7Cka",
    "london":        "discplace-AQ5IMCGOOTyNRue",
    "chicago":       "discplace-NdGm35qFD0vaXNF",
    "los-angeles":   "discplace-OgfEAh5KgfMzise",
    "la":            "discplace-OgfEAh5KgfMzise",
    "toronto":       "discplace-Cx3JMS6vXKAbhV5",
    "boston":        "discplace-VWeZ1zUvnawYHMj",
    "seattle":       "discplace-FQ4E58PeBMHGTKK",
    "austin":        "discplace-0tPy8KGz3xMycnt",
    "miami":         "discplace-fSrrRYurTwydAGK",
    "tel-aviv":      "discplace-fHkSoyCyugTZSbr",
    "bengaluru":     "discplace-G0tGUVYwl7T17Sb",
    "bangalore":     "discplace-G0tGUVYwl7T17Sb",
    "seoul":         "discplace-eQieweHXBFCWbCj",
    "nairobi":       "discplace-YSx1DPerjjIyq7M",
    "montreal":      "discplace-CXKKcJmNkbj6ikW",
    "vancouver":     "discplace-4fa7ldlAkBTTivm",
}


def _resolve_place_id(location: str) -> tuple[str, str]:
    """
    Return (place_api_id, display_name) for a location string.
    Raises ValueError if not a known Luma city.
    """
    slug = location.lower().strip().replace(" ", "-").replace("_", "-")
    place_id = _CITY_PLACE_IDS.get(slug)
    if not place_id:
        raise ValueError(
            f"Location {location!r} is not a known Luma city. "
            f"Supported: {', '.join(sorted(_CITY_PLACE_IDS))}"
        )
    display = slug.replace("-", " ").title()
    return place_id, display


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class LumaAdapter(BaseSourceAdapter):
    """
    Luma source adapter using api2.luma.com directly.

    The `browser` argument accepted by `collect()` is ignored — this adapter
    uses httpx and requires no browser.
    """
    source_name = "luma"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("luma.collect.start", term=search_term, location=config.location)

        try:
            place_id, city_name = _resolve_place_id(config.location)
        except ValueError as exc:
            log.warning("luma.unsupported_city", location=config.location, error=str(exc))
            return []

        target = config.max_results_per_source
        raw_entries: list[dict] = []
        cursor: Optional[str] = None
        has_more = False

        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
        ) as client:
            # ── Paginate through API results ──────────────────────────────────
            while len(raw_entries) < target:
                page_limit = min(_MAX_PAGE_SIZE, target - len(raw_entries))
                params: dict[str, Any] = {
                    "discover_place_api_id": place_id,
                    "pagination_limit": page_limit,
                }
                if search_term:
                    params["query"] = search_term
                if cursor:
                    params["pagination_cursor"] = cursor
                    await asyncio.sleep(_PAGE_DELAY_SECONDS)

                t0 = time.time()
                try:
                    resp = await client.get(
                        _EVENTS_ENDPOINT, params=params, headers=_HEADERS_JSON
                    )
                except httpx.RequestError as exc:
                    log.warning("luma.request_error", term=search_term, error=str(exc))
                    break

                elapsed = round(time.time() - t0, 2)

                if resp.status_code != 200:
                    log.warning("luma.http_error", status=resp.status_code,
                                body=resp.text[:200])
                    break

                data = resp.json()
                entries = data.get("entries", [])
                has_more = data.get("has_more", False)
                cursor = data.get("next_cursor")

                log.info(
                    "luma.page_done",
                    term=search_term,
                    hits=len(entries),
                    total=len(raw_entries) + len(entries),
                    has_more=has_more,
                    elapsed_s=elapsed,
                )

                raw_entries.extend(entries)

                if not has_more or not cursor:
                    break

            raw_entries = raw_entries[:target]

            # ── Fetch full descriptions in parallel ───────────────────────────
            slugs = [
                (e.get("event") or {}).get("url") for e in raw_entries
            ]
            descriptions = await _fetch_descriptions_parallel(client, slugs)

        results = []
        for entry, desc in zip(raw_entries, descriptions):
            raw = _to_raw_dict(entry, desc, search_term, config)
            if raw:
                results.append(raw)

        log.info("luma.collect.done", term=search_term, count=len(results))
        return results


# ---------------------------------------------------------------------------
# Description fetching
# ---------------------------------------------------------------------------

async def _fetch_descriptions_parallel(
    client: httpx.AsyncClient,
    slugs: list[Optional[str]],
) -> list[Optional[str]]:
    tasks = [_fetch_single_description(client, slug) for slug in slugs]
    return list(await asyncio.gather(*tasks))


async def _fetch_single_description(
    client: httpx.AsyncClient,
    slug: Optional[str],
) -> Optional[str]:
    if not slug:
        return None
    url = f"https://lu.ma/{slug}"
    try:
        resp = await client.get(url, headers=_HEADERS_HTML)
        if resp.status_code == 200:
            return _extract_description_from_html(resp.text)
    except httpx.RequestError as exc:
        log.debug("luma.desc_fetch_failed", slug=slug, error=str(exc))
    return None


def _extract_description_from_html(html: str) -> Optional[str]:
    """
    Extract event description from a lu.ma event page HTML.

    Primary:  __NEXT_DATA__ JSON → description_mirror (ProseMirror AST).
    Fallback: og:description meta tag (~155 chars, truncated by Luma).
    """
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if m:
        try:
            nd = json.loads(m.group(1))
            dm = (
                nd.get("props", {})
                .get("pageProps", {})
                .get("initialData", {})
                .get("data", {})
                .get("description_mirror")
            )
            if dm and isinstance(dm, dict):
                text = _prosemirror_to_text(dm).strip()
                if text:
                    return text[:_MAX_DESCRIPTION_CHARS]
        except (json.JSONDecodeError, AttributeError):
            pass

    m2 = re.search(
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']',
        html,
    )
    if m2:
        text = m2.group(1).strip()
        if text:
            return text

    return None


def _prosemirror_to_text(node: Any, _depth: int = 0) -> str:
    """Recursively convert a ProseMirror JSON document to plain text."""
    if not isinstance(node, dict) or _depth > 50:
        return ""

    node_type = node.get("type", "")
    if node_type == "text":
        return node.get("text", "")

    children = node.get("content") or []
    text = "".join(_prosemirror_to_text(c, _depth + 1) for c in children)

    _BLOCK_TYPES = {
        "paragraph", "heading", "blockquote", "listItem",
        "bulletList", "orderedList", "codeBlock", "horizontalRule",
    }
    if node_type in _BLOCK_TYPES:
        text = text.rstrip() + "\n"

    return text


# ---------------------------------------------------------------------------
# Raw dict mapping
# ---------------------------------------------------------------------------

def _to_raw_dict(
    entry: dict,
    description: Optional[str],
    search_term: str,
    config: CollectorConfig,
) -> dict | None:
    """Map a raw Luma API entry to the normalizer's expected raw dict format."""
    ev = entry.get("event") or {}
    geo = ev.get("geo_address_info") or {}
    cal = entry.get("calendar") or {}
    ticket_info = entry.get("ticket_info") or {}

    url_slug = ev.get("url", "")
    full_url = f"https://lu.ma/{url_slug}" if url_slug else None
    title = (ev.get("name") or "").strip()

    if not full_url or not title:
        return None

    location_type = ev.get("location_type", "")
    is_online = location_type == "online"

    # Venue string for display
    venue_parts = [p for p in [geo.get("address"), geo.get("city")] if p]
    venue_str = ", ".join(venue_parts) if venue_parts else ("Online event" if is_online else "")

    # RSVP count
    show_guest_list = ev.get("show_guest_list", True)
    rsvp_count: Optional[int] = entry.get("guest_count") if show_guest_list else None

    cal_slug = cal.get("slug") or ""
    organizer_url = f"https://lu.ma/{cal_slug}" if cal_slug else None

    return {
        "url":              full_url,
        "title":            title,
        "description":      description or "",
        "organizer":        cal.get("name") or "",
        "organizer_url":    organizer_url,
        "group_name":       cal.get("name") or "",   # normalizer uses group_name → community_name
        "venue":            venue_str,
        "address":          geo.get("full_address") or geo.get("short_address") or "",
        "city":             geo.get("city") or config.location,
        "country":          geo.get("country") or config.country,
        "is_online":        is_online,
        "cost_text":        "paid" if ticket_info.get("is_paid") else "free",
        "source_record_id": ev.get("api_id") or "",
        "search_term":      search_term,
        "source":           "luma",
        # Datetime fields for normalizer
        "datetime_start":   ev.get("start_at"),
        "datetime_end":     ev.get("end_at"),
        "timezone":         ev.get("timezone"),
        # Extra richness
        "attendees_count":  rsvp_count,
        "event_type":       location_type,
        "cover_url":        ev.get("cover_url"),
    }
