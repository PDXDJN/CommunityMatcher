"""
Meetup adapter — GraphQL API (no browser required).

Uses Meetup's internal GraphQL endpoint (gql2) which accepts unauthenticated
POST requests. Reverse-engineered from the Meetup web app's Apollo client cache
and cross-referenced with the OpenMates open-source reference implementation
(https://github.com/glowingkitty/OpenMates).

Replaces the previous Playwright-based anchor-scraping approach:
  OLD: launch browser → navigate → scroll 3× → harvest <a href="/events/"> anchors
         → title only, no description, no datetime, no venue, ~20 events
  NEW: httpx POST to /gql2 → full structured data in one request
         → title + description + datetime + venue + attendees + fee, up to 50/page

Key facts about the endpoint:
  - POST https://www.meetup.com/gql2
  - No authentication needed
  - Header apollographql-client-name: nextjs-web required
  - Cursor-based pagination via pageInfo.endCursor / hasNextPage
  - 1.2 s polite delay between paginated pages
  - lat/lon required in filter (city/country are optional display hints)
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx
from playwright.async_api import Browser  # kept for base class compat, not used

from community_collector.adapters.base import BaseSourceAdapter
from community_collector.config import CollectorConfig
from community_collector.utils.logging_utils import get_logger

log = get_logger("adapter.meetup")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GQL_URL = "https://www.meetup.com/gql2"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://www.meetup.com/find/",
    "apollographql-client-name": "nextjs-web",
}

_EVENT_SEARCH_QUERY = """
query eventSearch(
    $filter: EventSearchFilter!,
    $sort: KeywordSort,
    $first: Int,
    $after: String
) {
    eventSearch(filter: $filter, sort: $sort, first: $first, after: $after) {
        pageInfo {
            hasNextPage
            endCursor
        }
        totalCount
        edges {
            node {
                id
                title
                dateTime
                endTime
                eventType
                eventUrl
                description
                rsvps { totalCount }
                venue {
                    name
                    address
                    city
                    state
                    country
                    lat
                    lon
                }
                group {
                    id
                    name
                    urlname
                    timezone
                }
                feeSettings {
                    amount
                    currency
                }
            }
        }
    }
}
"""

# Lat/lon for known cities — avoids a round-trip geocoder call.
_CITY_COORDS: dict[str, tuple[float, float, str, str]] = {
    "berlin":    (52.52, 13.38, "Berlin",    "de"),
    "hamburg":   (53.55, 10.00, "Hamburg",   "de"),
    "munich":    (48.14, 11.58, "Munich",    "de"),
    "frankfurt": (50.11,  8.68, "Frankfurt", "de"),
    "cologne":   (50.94,  6.96, "Cologne",   "de"),
}

_PAGE_DELAY_SECONDS = 1.2
_MAX_PER_PAGE = 50  # Meetup API hard cap


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class MeetupAdapter(BaseSourceAdapter):
    """
    Meetup source adapter using the gql2 GraphQL endpoint.

    The `browser` argument accepted by `collect()` is ignored — this adapter
    uses httpx directly and requires no browser.
    """
    source_name = "meetup"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("meetup.collect.start", term=search_term, location=config.location)

        lat, lon, city, country = _resolve_coords(config)
        target = config.max_results_per_source

        results: list[dict] = []
        cursor: Optional[str] = None
        page_num = 0

        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            while len(results) < target:
                page_num += 1
                want = min(_MAX_PER_PAGE, target - len(results))

                gql_filter = {
                    "lat": lat,
                    "lon": lon,
                    "query": search_term,
                    "radius": 25.0,
                    "doConsolidateEvents": False,
                    "city": city,
                    "country": country,
                }

                variables: dict = {
                    "filter": gql_filter,
                    "sort": {"sortField": "RELEVANCE"},
                    "first": want,
                }
                if cursor:
                    variables["after"] = cursor

                payload = {
                    "operationName": "eventSearch",
                    "variables": variables,
                    "query": _EVENT_SEARCH_QUERY,
                }

                t0 = time.time()
                try:
                    resp = await client.post(_GQL_URL, json=payload, headers=_HEADERS)
                except httpx.RequestError as exc:
                    log.warning("meetup.request_error", term=search_term, error=str(exc))
                    break

                if resp.status_code != 200:
                    log.warning("meetup.http_error", status=resp.status_code,
                                body=resp.text[:200])
                    break

                data = resp.json()
                if "errors" in data:
                    log.warning("meetup.gql_errors", errors=data["errors"][:1])
                    break

                event_search = (data.get("data") or {}).get("eventSearch")
                if not event_search:
                    log.warning("meetup.no_event_search", keys=list((data.get("data") or {}).keys()))
                    break

                edges = event_search.get("edges", [])
                page_info = event_search.get("pageInfo", {})
                total_count = event_search.get("totalCount", 0)
                elapsed = round(time.time() - t0, 2)

                page_hits = 0
                for edge in edges:
                    node = edge.get("node") or {}
                    raw = _to_raw_dict(node, search_term, config)
                    if raw:
                        results.append(raw)
                        page_hits += 1

                log.info(
                    "meetup.page_done",
                    page=page_num,
                    hits=page_hits,
                    total=len(results),
                    server_total=total_count,
                    elapsed_s=elapsed,
                )

                if not page_info.get("hasNextPage") or page_hits == 0:
                    break

                cursor = page_info.get("endCursor")
                if not cursor:
                    break

                # Polite delay between paginated requests
                if len(results) < target:
                    await asyncio.sleep(_PAGE_DELAY_SECONDS)

        log.info("meetup.collect.done", term=search_term, count=len(results))
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_coords(config: CollectorConfig) -> tuple[float, float, str, str]:
    """Return (lat, lon, city, country) for the configured location."""
    key = config.location.lower().split(",")[0].strip()
    if key in _CITY_COORDS:
        return _CITY_COORDS[key]
    # Generic fallback — add more cities to _CITY_COORDS as needed
    log.warning("meetup.unknown_city", city=config.location,
                hint="Add to _CITY_COORDS in meetup_adapter.py")
    # Default to Berlin if city unknown
    return _CITY_COORDS["berlin"]


def _to_raw_dict(node: dict, search_term: str, config: CollectorConfig) -> dict | None:
    """Map a GraphQL event node to the raw dict format the normalizer expects."""
    event_url = node.get("eventUrl", "")
    title = (node.get("title") or "").strip()
    if not event_url or not title:
        return None

    group = node.get("group") or {}
    venue = node.get("venue") or {}
    fee = node.get("feeSettings")
    rsvps = node.get("rsvps") or {}
    event_type = node.get("eventType", "")
    is_online = event_type == "ONLINE"

    # Cost
    cost_text: Optional[str] = None
    currency: Optional[str] = None
    if fee and fee.get("amount") is not None:
        amount = fee["amount"]
        currency = fee.get("currency", "")
        cost_text = f"{currency} {amount}".strip() if amount else "free"
    else:
        cost_text = "free"

    # Venue
    venue_city = venue.get("city") or ""
    venue_country = venue.get("country") or ""

    return {
        # Normalizer fields
        "url":             event_url,
        "title":           title,
        "description":     node.get("description") or "",
        "group_name":      group.get("name") or "",
        "organizer":       group.get("name") or "",
        "venue":           "Online event" if is_online else (venue.get("name") or ""),
        "address":         venue.get("address") or "",
        "city":            venue_city or config.location,
        "country":         venue_country or config.country,
        "is_online":       is_online,
        "cost_text":       cost_text,
        "currency":        currency,
        "source_record_id": str(node.get("id") or ""),
        "search_term":     search_term,
        "source":          "meetup",
        # Raw payload fields used by _enrich() for datetime parsing
        "datetime_start":  node.get("dateTime"),
        "datetime_end":    node.get("endTime"),
        "timezone":        group.get("timezone"),
        # Extra richness stored in raw_payload
        "attendees_count": rsvps.get("totalCount", 0),
        "event_type":      event_type,
        "group_urlname":   group.get("urlname") or "",
        "group_id":        group.get("id") or "",
        "latitude":        venue.get("lat"),
        "longitude":       venue.get("lon"),
    }
