"""
Eventbrite adapter.

Uses the same anchor-filtering approach proven in Event_Finder:
iterate all a[href] on the search page, keep only those whose href
contains "/e/" (event detail pages), and treat the anchor text as title.
Paginates up to 3 pages per search term.
"""
from __future__ import annotations
import re
from urllib.parse import quote_plus
from playwright.async_api import Browser, TimeoutError as PWTimeout
from community_collector.adapters.base import BaseSourceAdapter
from community_collector.config import CollectorConfig
from community_collector.keywords import clean_title
from community_collector.utils.logging_utils import get_logger
from community_collector.utils.url_utils import normalize_url

log = get_logger("adapter.eventbrite")

_BASE_URL = "https://www.eventbrite.com"
_INLINE_WS = re.compile(r"[ \t]+")


def _search_url(location_slug: str, term: str, page_num: int = 1) -> str:
    term_slug = quote_plus(term.lower())
    base = f"{_BASE_URL}/d/germany--{location_slug}/{term_slug}/"
    return base if page_num == 1 else f"{base}?page={page_num}"


class EventbriteAdapter(BaseSourceAdapter):
    source_name = "eventbrite"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("eventbrite.collect.start", term=search_term, location=config.location)
        results: list[dict] = []
        seen_urls: set[str] = set()

        loc_slug = config.location.lower().replace(" ", "-")
        ctx = await self._new_context(browser, config)
        page = await ctx.new_page()
        page.set_default_timeout(40_000)

        try:
            for page_num in range(1, 4):  # up to 3 pages
                url = _search_url(loc_slug, search_term, page_num)
                log.info("eventbrite.fetch", url=url, page=page_num)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=40_000)
                except PWTimeout:
                    log.warning("eventbrite.page_timeout", page=page_num, url=url)
                    break

                await self._delay(config)

                # Accept cookies on first page if present
                if page_num == 1:
                    try:
                        await page.click(
                            '[data-spec="gdpr-accept-all-btn"], #onetrust-accept-btn-handler',
                            timeout=2000,
                        )
                    except Exception:
                        pass

                # Collect all anchors and filter for event detail links (/e/)
                # Cap per-page (not per-run) so all 3 pages are attempted.
                anchors = await page.locator("a[href]").all()
                page_hits = 0
                for a in anchors:
                    try:
                        href = await a.get_attribute("href") or ""
                        text = _INLINE_WS.sub(
                            " ", (await a.text_content() or "")
                        ).strip()
                        if "/e/" not in href or not text or len(text) < 5:
                            continue
                        if not href.startswith("http"):
                            href = _BASE_URL + href
                        norm = normalize_url(href)
                        if norm in seen_urls:
                            continue
                        seen_urls.add(norm)
                        title = clean_title(text)
                        if not title:
                            continue
                        results.append({
                            "url":         norm,
                            "title":       title,
                            "organizer":   "",
                            "description": "",
                            "datetime":    "",
                            "venue":       "",
                            "price":       "",
                            "is_online":   "online" in title.lower(),
                            "city":        config.location,
                            "country":     config.country,
                            "search_term": search_term,
                            "source":      "eventbrite",
                        })
                        page_hits += 1
                        # Per-page cap: allow each page to contribute up to
                        # max_results_per_source new events before moving on.
                        if page_hits >= config.max_results_per_source:
                            break
                    except Exception as exc:
                        log.warning("eventbrite.anchor_parse_failed", error=str(exc))

                log.info("eventbrite.page_done", page=page_num, hits=page_hits, total=len(results))
                if page_hits == 0:
                    break  # no results on this page — stop paginating

        except Exception as exc:
            log.warning("eventbrite.error", term=search_term, error=str(exc))
        finally:
            await page.close()
            await ctx.close()

        log.info("eventbrite.collect.done", term=search_term, count=len(results))
        return results
