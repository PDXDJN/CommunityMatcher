"""
Meetup.com adapter.

Uses the same anchor-filtering approach proven in Event_Finder:
navigate to the de--Berlin search URL, scroll to trigger lazy load,
collect all a[href] and keep only those whose href contains "/events/".
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

log = get_logger("adapter.meetup")

_BASE_URL = "https://www.meetup.com"
_WHITESPACE = re.compile(r"\s+")


def _search_url(term: str) -> str:
    return f"{_BASE_URL}/find/?location=de--Berlin&keywords={quote_plus(term)}"


class MeetupAdapter(BaseSourceAdapter):
    source_name = "meetup"

    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        log.info("meetup.collect.start", term=search_term, location=config.location)
        results: list[dict] = []
        seen_urls: set[str] = set()

        ctx = await self._new_context(browser, config)
        page = await ctx.new_page()
        page.set_default_timeout(30_000)

        try:
            url = _search_url(search_term)
            log.info("meetup.fetch", url=url)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except PWTimeout:
                log.warning("meetup.page_timeout", term=search_term)
                return results

            await self._delay(config)

            # Dismiss cookie banner if present
            try:
                await page.click('[data-testid="cookie-consent-accept"]', timeout=2000)
            except Exception:
                pass

            # Scroll 3× to trigger lazy load
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1200)

            # Collect all anchors and filter for event/group links (/events/)
            links = await page.locator("a").all()
            for link in links:
                try:
                    href = await link.get_attribute("href") or ""
                    text = _WHITESPACE.sub(
                        " ", (await link.text_content() or "")
                    ).strip()
                    if "/events/" not in href or len(text) <= 5:
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
                        "group_name":  "",
                        "description": "",
                        "datetime":    "",
                        "venue":       "",
                        "attendees":   "",
                        "is_online":   "online" in title.lower(),
                        "city":        config.location,
                        "country":     config.country,
                        "search_term": search_term,
                        "source":      "meetup",
                    })
                    if len(results) >= config.max_results_per_source:
                        break
                except Exception as exc:
                    log.warning("meetup.link_parse_failed", error=str(exc))

        except Exception as exc:
            log.warning("meetup.error", term=search_term, error=str(exc))
        finally:
            await page.close()
            await ctx.close()

        log.info("meetup.collect.done", term=search_term, count=len(results))
        return results
