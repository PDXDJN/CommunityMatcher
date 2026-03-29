"""Base adapter interface — adapted from Event_Finder/app/agents/base.py."""
from __future__ import annotations
import asyncio
import re
from abc import ABC, abstractmethod
from playwright.async_api import Browser, BrowserContext, Page
from community_collector.config import CollectorConfig
from community_collector.utils.logging_utils import get_logger
from community_collector.utils.text_utils import clean_scraped_text

_ICON_TEXT    = re.compile(r'\b[a-zA-Z]+(?:[A-Z][a-zA-Z0-9]*)+\s+icon\b')
_WHITESPACE   = re.compile(r'\s+')

log = get_logger("adapter.base")


class BaseSourceAdapter(ABC):
    """
    Abstract base for all source adapters.

    Each adapter is responsible for:
      1. Launching a browser context
      2. Navigating and searching the source site
      3. Extracting raw field dicts (source-native format)
      4. Returning them as a list — normalization happens outside

    Adapters should fail gracefully: catch exceptions, log them, and
    return whatever partial results were collected.
    """

    source_name: str = "base"

    @abstractmethod
    async def collect(
        self, browser: Browser, config: CollectorConfig, search_term: str
    ) -> list[dict]:
        """
        Collect raw records for a single search term.

        Args:
            browser: Shared Playwright Browser instance.
            config:  CollectorConfig with location, limits, etc.
            search_term: Single keyword/phrase to search for.

        Returns:
            List of raw dicts (source-native fields).
            Empty list on failure — never raises.
        """
        raise NotImplementedError

    async def _new_context(self, browser: Browser, config: CollectorConfig) -> BrowserContext:
        """Create a fresh browser context with a realistic User-Agent."""
        from community_collector.config import USER_AGENT
        return await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            timezone_id="Europe/Berlin",
            viewport={"width": 1280, "height": 900},
        )

    async def _safe_text(self, page: Page, selector: str, timeout: int = 4000) -> str:
        """Extract inner text from selector, return '' if not found."""
        try:
            el = await page.wait_for_selector(selector, timeout=timeout)
            if el:
                text = await el.inner_text()
                return clean_scraped_text(text or "")
        except Exception:
            pass
        return ""

    async def _safe_attr(self, page: Page, selector: str, attr: str, timeout: int = 4000) -> str:
        """Extract an attribute from a selector, return '' if not found."""
        try:
            el = await page.wait_for_selector(selector, timeout=timeout)
            if el:
                value = await el.get_attribute(attr)
                return (value or "").strip()
        except Exception:
            pass
        return ""

    async def _delay(self, config: CollectorConfig) -> None:
        """Pause briefly between page interactions — be a polite prototype."""
        await asyncio.sleep(config.page_delay_ms / 1000)
