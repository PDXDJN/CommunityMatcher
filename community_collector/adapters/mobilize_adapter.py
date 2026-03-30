"""
Mobilize adapter — Mobilizon GraphQL API (no browser required).

Mobilizon is a federated, open-source alternative to Meetup. It exposes a
public GraphQL API at /api on every instance. `mobilize.berlin` is the
primary Berlin instance; it covers arts, culture, activism, tech, and
community events in and around the city.

Key facts:
  - POST https://mobilize.berlin/api
  - No authentication required for public event/group search
  - Cursor-based pagination via `page` integer parameter
  - Berlin geohash: u33d9 (center, ~5km cell)
  - Also searches groups (recurring communities, not one-off events)
  - 1.2 s polite delay between pages

Reference:
  https://docs.mobilizon.org/5.%20Interoperability/3.graphql_api/
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

log = get_logger("adapter.mobilize")

_API_URL = "https://mobilize.berlin/api"

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "CommunityMatcher/1.0 (+https://github.com/community-matcher)"
    ),
}

_PAGE_SIZE = 20
_PAGE_DELAY_SECONDS = 1.2

# --------------------------------------------------------------------------
# GraphQL queries
# Note: searchEvents returns EventSearchResult which requires inline fragment
# on "Event" to access event-specific fields like description.
# The location/geohash filter is omitted — mobilize.berlin returns 0 results
# when filtered by geohash; the instance is Berlin-specific anyway.
# --------------------------------------------------------------------------

_SEARCH_EVENTS_QUERY = """
query SearchEvents($term: String, $page: Int, $limit: Int) {
  searchEvents(term: $term, page: $page, limit: $limit) {
    total
    elements {
      __typename
      ... on Event {
        id
        title
        url
        beginsOn
        endsOn
        status
        tags { title }
        physicalAddress {
          description
          locality
          region
          country
        }
        attributedTo { name url }
        organizerActor { name url }
        options { isOnline }
      }
    }
  }
}
"""

_SEARCH_GROUPS_QUERY = """
query SearchGroups($term: String, $page: Int, $limit: Int) {
  searchGroups(term: $term, page: $page, limit: $limit) {
    total
    elements {
      id
      name
      preferredUsername
      url
      summary
      physicalAddress { locality }
    }
  }
}
"""


class MobilizeAdapter(BaseSourceAdapter):
    """
    Mobilizon source adapter using the mobilize.berlin GraphQL API.

    Searches both events and groups so recurring communities appear
    alongside one-off events.
    """
    source_name = "mobilize"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("mobilize.collect.start", term=search_term)
        results: list[dict] = []

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            # 1. Search events
            event_results = await _search_events(
                client, search_term, config.max_results_per_source
            )
            results.extend(event_results)

            # 2. Search groups (recurring communities)
            if len(results) < config.max_results_per_source:
                group_results = await _search_groups(
                    client, search_term,
                    config.max_results_per_source - len(results)
                )
                results.extend(group_results)

        log.info("mobilize.collect.done", term=search_term, count=len(results))
        return results


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

async def _search_events(
    client: httpx.AsyncClient, term: str, limit: int
) -> list[dict]:
    results: list[dict] = []
    page = 1

    while len(results) < limit:
        want = min(_PAGE_SIZE, limit - len(results))
        variables = {
            "term": term,
            "page": page,
            "limit": want,
        }

        t0 = time.time()
        try:
            resp = await client.post(
                _API_URL,
                json={"query": _SEARCH_EVENTS_QUERY, "variables": variables},
                headers=_HEADERS,
            )
        except httpx.RequestError as exc:
            log.warning("mobilize.events.request_error", error=str(exc))
            break

        if resp.status_code != 200:
            log.warning("mobilize.events.http_error", status=resp.status_code,
                        body=resp.text[:200])
            break

        data = resp.json()
        if "errors" in data:
            log.warning("mobilize.events.gql_errors", errors=data["errors"][:1])
            break

        search = (data.get("data") or {}).get("searchEvents") or {}
        elements = search.get("elements") or []
        total = search.get("total", 0)
        elapsed = round(time.time() - t0, 2)

        page_hits = 0
        for elem in elements:
            raw = _event_to_raw(elem, term)
            if raw:
                results.append(raw)
                page_hits += 1

        log.info("mobilize.events.page", page=page, hits=page_hits,
                 total_so_far=len(results), server_total=total, elapsed_s=elapsed)

        if page_hits == 0 or len(elements) < want or len(results) >= total:
            break

        page += 1
        await asyncio.sleep(_PAGE_DELAY_SECONDS)

    return results


async def _search_groups(
    client: httpx.AsyncClient, term: str, limit: int
) -> list[dict]:
    results: list[dict] = []
    page = 1

    while len(results) < limit:
        want = min(_PAGE_SIZE, limit - len(results))
        variables = {
            "term": term,
            "page": page,
            "limit": want,
        }

        try:
            resp = await client.post(
                _API_URL,
                json={"query": _SEARCH_GROUPS_QUERY, "variables": variables},
                headers=_HEADERS,
            )
        except httpx.RequestError as exc:
            log.warning("mobilize.groups.request_error", error=str(exc))
            break

        if resp.status_code != 200:
            break

        data = resp.json()
        search = (data.get("data") or {}).get("searchGroups") or {}
        elements = search.get("elements") or []
        total = search.get("total", 0)

        page_hits = 0
        for elem in elements:
            raw = _group_to_raw(elem, term)
            if raw:
                results.append(raw)
                page_hits += 1

        log.info("mobilize.groups.page", page=page, hits=page_hits,
                 total_so_far=len(results), server_total=total)

        if page_hits == 0 or len(elements) < want or len(results) >= total:
            break

        page += 1
        await asyncio.sleep(_PAGE_DELAY_SECONDS)

    return results


def _event_to_raw(elem: dict, search_term: str) -> dict | None:
    url = elem.get("url") or ""
    title = (elem.get("title") or "").strip()
    if not url or not title:
        return None

    addr = elem.get("physicalAddress") or {}
    opts = elem.get("options") or {}
    organizer = (
        (elem.get("organizerActor") or {}).get("name")
        or (elem.get("attributedTo") or {}).get("name")
        or ""
    )
    tags = [t["title"] for t in (elem.get("tags") or []) if t.get("title")]

    return {
        "url":             url,
        "title":           title,
        "description":     elem.get("description") or "",
        "organizer":       organizer,
        "venue":           addr.get("description") or "",
        "address":         addr.get("description") or "",
        "city":            addr.get("locality") or "Berlin",
        "country":         addr.get("country") or "de",
        "is_online":       bool(opts.get("isOnline")),
        "cost_text":       None,
        "source_record_id": str(elem.get("id") or ""),
        "search_term":     search_term,
        "source":          "mobilize",
        "datetime_start":  elem.get("beginsOn"),
        "datetime_end":    elem.get("endsOn"),
        "tags":            tags,
        "status":          elem.get("status") or "",
    }


def _group_to_raw(elem: dict, search_term: str) -> dict | None:
    url = elem.get("url") or ""
    name = (elem.get("name") or "").strip()
    if not url or not name:
        return None

    addr = elem.get("physicalAddress") or {}

    return {
        "url":             url,
        "title":           name,
        "description":     elem.get("summary") or "",
        "organizer":       name,
        "community_name":  name,
        "city":            addr.get("locality") or "Berlin",
        "country":         "de",
        "is_online":       False,
        "cost_text":       None,
        "source_record_id": str(elem.get("id") or ""),
        "search_term":     search_term,
        "source":          "mobilize",
        "activity":        "recurring",   # groups are recurring by nature
    }
