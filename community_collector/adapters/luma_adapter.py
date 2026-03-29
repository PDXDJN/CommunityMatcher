"""
Lu.ma adapter.

Scrapes two sources:
  1. Named Berlin community calendars (known slugs)
  2. Lu.ma discover page filtered for Berlin

For each page, scrolls deeply to load lazy content, then harvests all
lu.ma event/calendar links. Results from all sources are deduplicated by slug.
"""
from __future__ import annotations
import re
from playwright.async_api import Browser, TimeoutError as PWTimeout
from community_collector.adapters.base import BaseSourceAdapter
from community_collector.config import CollectorConfig
from community_collector.keywords import clean_title
from community_collector.utils.logging_utils import get_logger
from community_collector.utils.url_utils import normalize_url

log = get_logger("adapter.luma")

_BASE_URL = "https://lu.ma"

# Extended Berlin community calendars — named slugs collected from public listings
_BERLIN_CALENDARS = [
    # Proven (original)
    "https://lu.ma/fomoberlin",
    "https://lu.ma/gezellig",
    "https://lu.ma/berlin",
    # Tech & AI
    "https://lu.ma/ai-berlin",
    "https://lu.ma/tech-berlin",
    "https://lu.ma/berlinhacks",
    "https://lu.ma/pyberlin",
    "https://lu.ma/mlberlin",
    # Startup & networking
    "https://lu.ma/startup-berlin",
    "https://lu.ma/founders-berlin",
    "https://lu.ma/berlin-startup",
    # Community & expat
    "https://lu.ma/expat-berlin",
    "https://lu.ma/english-berlin",
    "https://lu.ma/berlin-social",
    # Creative & maker
    "https://lu.ma/berlin-maker",
    "https://lu.ma/creative-berlin",
]

# Luma discover pages — scrape search results for Berlin
_DISCOVER_URLS = [
    "https://lu.ma/discover?city=Berlin",
]

# Navigation / static slugs to skip (not event pages)
_NAV_SLUGS = {
    "discover", "signin", "signup", "pricing", "blog", "create",
    "home", "about", "contact", "help", "terms", "privacy",
    "dashboard", "settings", "notifications", "calendar",
    "user", "host", "embed", "ical", "rss",
}

_WHITESPACE = re.compile(r"\s+")

# How many times to scroll per page to load lazy content
_SCROLL_ROUNDS = 6
# Max events to collect per calendar (no global cap during per-calendar iteration)
_PER_CALENDAR_MAX = 60


async def _harvest_luma_links(page, config: CollectorConfig, seen_slugs: set[str]) -> list[dict]:
    """
    Extract all unique lu.ma event links from the current page state.
    Does not navigate; caller is responsible for page.goto().
    """
    anchors = await page.locator("a[href]").all()
    hits: list[dict] = []

    for a in anchors:
        try:
            href = (await a.get_attribute("href") or "").strip()
            if not href:
                continue

            # Resolve relative URLs
            if href.startswith("/"):
                href = _BASE_URL + href
            elif not href.startswith("https://lu.ma"):
                continue

            # Extract slug
            path = href.replace("https://lu.ma", "").strip("/")
            slug = path.split("/")[0] if path else ""
            if not slug or slug in _NAV_SLUGS:
                continue
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            text = _WHITESPACE.sub(" ", (await a.text_content() or "")).strip()
            title = clean_title(text) if text else slug.replace("-", " ").title()
            if not title:
                continue

            norm = normalize_url(href)
            hits.append({
                "url":         norm,
                "title":       title,
                "organizer":   "",
                "description": "",
                "datetime":    "",
                "venue":       "",
                "is_online":   "online" in title.lower() or "virtual" in title.lower(),
                "city":        config.location,
                "country":     config.country,
                "search_term": "",
                "source":      "luma",
            })
        except Exception as exc:
            log.warning("luma.anchor_parse_failed", error=str(exc))

    return hits


class LumaAdapter(BaseSourceAdapter):
    source_name = "luma"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("luma.collect.start", term=search_term, location=config.location)
        results: list[dict] = []
        seen_slugs: set[str] = set()

        ctx = await self._new_context(browser, config)
        page = await ctx.new_page()
        page.set_default_timeout(30_000)

        try:
            # ── Named community calendars ─────────────────────────────────────
            for calendar_url in _BERLIN_CALENDARS:
                log.info("luma.fetch_calendar", url=calendar_url)
                try:
                    await page.goto(calendar_url, wait_until="networkidle", timeout=30_000)
                except PWTimeout:
                    log.warning("luma.calendar_timeout", url=calendar_url)
                    continue

                await self._delay(config)

                # Scroll repeatedly to trigger lazy loading
                for _ in range(_SCROLL_ROUNDS):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(800)

                hits = await _harvest_luma_links(page, config, seen_slugs)
                # Tag with search term
                for h in hits:
                    h["search_term"] = search_term
                results.extend(hits[:_PER_CALENDAR_MAX])
                log.info("luma.calendar_done", url=calendar_url, hits=len(hits), total=len(results))

            # ── Discover / search pages ───────────────────────────────────────
            for discover_url in _DISCOVER_URLS:
                log.info("luma.fetch_discover", url=discover_url)
                try:
                    await page.goto(discover_url, wait_until="networkidle", timeout=30_000)
                except PWTimeout:
                    log.warning("luma.discover_timeout", url=discover_url)
                    continue

                await self._delay(config)

                for _ in range(_SCROLL_ROUNDS):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(800)

                hits = await _harvest_luma_links(page, config, seen_slugs)
                for h in hits:
                    h["search_term"] = search_term
                results.extend(hits)
                log.info("luma.discover_done", url=discover_url, hits=len(hits), total=len(results))

        except Exception as exc:
            log.warning("luma.error", term=search_term, error=str(exc))
        finally:
            await page.close()
            await ctx.close()

        log.info("luma.collect.done", term=search_term, count=len(results))
        # No hard cap on return — let the orchestrator deduplicate across terms
        return results
