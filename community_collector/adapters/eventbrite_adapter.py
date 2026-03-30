"""
Eventbrite adapter — httpx-based (no browser required).

Replaces the previous Playwright approach (~30-40s per term, title-only).

Strategy (tried in order per page):
  1. JSON-LD Event schemas  — stable SEO markup, richest data
  2. __NEXT_DATA__ JSON     — Next.js server payload, good fallback
  3. Anchor extraction      — last resort, title-only like the old adapter

Key facts:
  - GET https://www.eventbrite.com/d/germany--berlin/{term}--events/
  - No authentication needed for public search results
  - 1.2 s polite inter-page delay
  - Up to 3 pages per search term
  - browser param kept for BaseSourceAdapter compat but not used
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Optional
from urllib.parse import quote_plus

import httpx
from playwright.async_api import Browser  # base class compat only

from community_collector.adapters.base import BaseSourceAdapter
from community_collector.config import CollectorConfig
from community_collector.utils.logging_utils import get_logger
from community_collector.utils.url_utils import normalize_url

log = get_logger("adapter.eventbrite")

_BASE_URL = "https://www.eventbrite.com"
_PAGE_DELAY_SECONDS = 1.2
_HTTP_TIMEOUT = 20.0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.eventbrite.com/",
}

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_NEXTDATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)
_ANCHOR_HREF_RE = re.compile(r'href=["\']([^"\']*?/e/[^"\']+)["\']')


def _search_url(term: str, page: int = 1) -> str:
    slug = quote_plus(term.lower().replace(" ", "-"))
    base = f"{_BASE_URL}/d/germany--berlin/{slug}--events/"
    return f"{base}?page={page}" if page > 1 else base


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _parse_offers(offers) -> tuple[str, Optional[float]]:
    if not offers:
        return "free", 0.0
    if isinstance(offers, dict):
        offers = [offers]
    offer = offers[0] if offers else {}
    try:
        amount = float(str(offer.get("price", "0")).strip() or "0")
    except ValueError:
        amount = 0.0
    currency = offer.get("priceCurrency", "EUR")
    if amount == 0:
        return "free", 0.0
    return f"{currency} {amount:.2f}", amount


def _parse_location(location: dict) -> tuple[str, str, str, Optional[float], Optional[float]]:
    if not isinstance(location, dict):
        return "", "", "Berlin", None, None
    name = location.get("name", "")
    addr = location.get("address") or {}
    if isinstance(addr, str):
        return name, addr, "Berlin", None, None
    street   = addr.get("streetAddress", "")
    locality = addr.get("addressLocality", "") or "Berlin"
    country  = addr.get("addressCountry", "DE")
    full_addr = ", ".join(filter(None, [street, locality, country]))
    geo = location.get("geo") or {}
    try:
        lat = float(geo["latitude"])  if geo.get("latitude")  is not None else None
        lon = float(geo["longitude"]) if geo.get("longitude") is not None else None
    except (ValueError, TypeError):
        lat = lon = None
    return name, full_addr, locality, lat, lon


def _events_from_jsonld(html: str, search_term: str, config: CollectorConfig) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    _EVENT_TYPES = {"Event", "SocialEvent", "BusinessEvent", "EducationEvent", "MusicEvent"}

    for m in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue

        items = data.get("@graph", [data]) if isinstance(data, dict) else []
        if isinstance(data, list):
            items = data

        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") not in _EVENT_TYPES:
                continue
            url = item.get("url", "")
            if not url or "/e/" not in url:
                continue
            norm_url = normalize_url(url)
            if norm_url in seen:
                continue
            seen.add(norm_url)

            title = (item.get("name") or "").strip()
            if not title or len(title) < 4:
                continue

            desc = (item.get("description") or "").strip()
            start = item.get("startDate") or item.get("starttime") or ""
            end   = item.get("endDate")   or item.get("endtime")   or ""

            organizer = item.get("organizer") or {}
            org_name = organizer.get("name", "") if isinstance(organizer, dict) else ""

            venue_name, venue_addr, city, lat, lon = _parse_location(
                item.get("location") or {}
            )
            cost_text, _ = _parse_offers(item.get("offers"))

            results.append({
                "url":            norm_url,
                "title":          title,
                "description":    desc,
                "organizer":      org_name,
                "venue":          venue_name,
                "address":        venue_addr,
                "city":           city or config.location,
                "country":        config.country,
                "datetime_start": start,
                "datetime_end":   end,
                "cost_text":      cost_text,
                "is_online":      "online" in title.lower() or "online" in venue_name.lower(),
                "latitude":       lat,
                "longitude":      lon,
                "search_term":    search_term,
                "source":         "eventbrite",
            })

    return results


def _events_from_nextdata(html: str, search_term: str, config: CollectorConfig) -> list[dict]:
    m = _NEXTDATA_RE.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return []

    # Recursively locate the first list of dicts that looks like events
    def _find_events(obj, depth: int = 0):
        if depth > 9 or not isinstance(obj, (dict, list)):
            return []
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict) and any(
                k in obj[0] for k in ("url", "eventUrl", "absolute_url", "name", "title")
            ):
                return obj
            for item in obj[:4]:
                found = _find_events(item, depth + 1)
                if found:
                    return found
            return []
        for key in ("events", "results", "eventCollection", "search_data"):
            val = obj.get(key)
            if val:
                found = _find_events(val, depth + 1)
                if found:
                    return found
        for val in obj.values():
            if isinstance(val, (dict, list)):
                found = _find_events(val, depth + 1)
                if found:
                    return found
        return []

    raw_events = _find_events(data)
    results: list[dict] = []
    seen: set[str] = set()

    for ev in raw_events:
        url = ev.get("url") or ev.get("eventUrl") or ev.get("absolute_url", "")
        if not url or "/e/" not in url:
            continue
        norm_url = normalize_url(url)
        if norm_url in seen:
            continue
        seen.add(norm_url)
        title = (ev.get("name") or ev.get("title") or "").strip()
        if not title or len(title) < 4:
            continue
        results.append({
            "url":         norm_url,
            "title":       title,
            "description": (ev.get("description") or ev.get("summary") or "").strip(),
            "city":        config.location,
            "country":     config.country,
            "is_online":   "online" in title.lower(),
            "search_term": search_term,
            "source":      "eventbrite",
        })

    return results


def _events_from_anchors(html: str, search_term: str, config: CollectorConfig) -> list[dict]:
    """Last-resort fallback: extract /e/ links with their anchor text."""
    results: list[dict] = []
    seen: set[str] = set()
    for m in _ANCHOR_HREF_RE.finditer(html):
        href = m.group(1)
        if not href.startswith("http"):
            href = _BASE_URL + href
        norm_url = normalize_url(href)
        if norm_url in seen:
            continue
        seen.add(norm_url)
        # Title is not reliably extractable from anchors without a DOM parser;
        # use the URL slug as a title hint
        slug = href.rstrip("/").rsplit("/e/", 1)[-1]
        title = slug.replace("-", " ").rsplit("-", 1)[0].strip().title()
        if not title or len(title) < 4:
            continue
        results.append({
            "url":         norm_url,
            "title":       title,
            "city":        config.location,
            "country":     config.country,
            "is_online":   False,
            "search_term": search_term,
            "source":      "eventbrite",
        })

    return results


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class EventbriteAdapter(BaseSourceAdapter):
    """
    Eventbrite adapter using httpx (no browser required).

    The `browser` argument accepted by `collect()` is ignored — this adapter
    uses httpx directly and requires no browser.
    """
    source_name = "eventbrite"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("eventbrite.collect.start", term=search_term)
        results: list[dict] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            for page_num in range(1, 4):
                url = _search_url(search_term, page_num)
                log.info("eventbrite.fetch", url=url, page=page_num)

                try:
                    resp = await client.get(url)
                except httpx.RequestError as exc:
                    log.warning("eventbrite.request_error", page=page_num, error=str(exc))
                    break

                if resp.status_code == 404:
                    break  # No results page
                if resp.status_code != 200:
                    log.warning("eventbrite.http_error", status=resp.status_code, page=page_num)
                    break

                html = resp.text

                # Try extraction methods in order of richness
                page_events = _events_from_jsonld(html, search_term, config)
                if not page_events:
                    page_events = _events_from_nextdata(html, search_term, config)
                if not page_events:
                    page_events = _events_from_anchors(html, search_term, config)

                page_hits = 0
                for ev in page_events:
                    norm_url = ev.get("url", "")
                    if norm_url in seen_urls:
                        continue
                    seen_urls.add(norm_url)
                    results.append(ev)
                    page_hits += 1
                    if page_hits >= config.max_results_per_source:
                        break

                log.info(
                    "eventbrite.page_done",
                    page=page_num,
                    hits=page_hits,
                    total=len(results),
                    method="jsonld" if _JSONLD_RE.search(html) else "nextdata/anchor",
                )

                if page_hits == 0:
                    break

                if page_num < 3 and len(results) < config.max_results_per_source:
                    await asyncio.sleep(_PAGE_DELAY_SECONDS)

        log.info("eventbrite.collect.done", term=search_term, count=len(results))
        return results
