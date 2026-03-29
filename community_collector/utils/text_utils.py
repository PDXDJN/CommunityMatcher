"""
Text utilities.
Adapted from Event_Finder/app/utils/text.py and Event_Finder/app/agents/meetup.py.
"""
from __future__ import annotations
import re
from typing import Iterable

_ICON_TEXT = re.compile(r'\b[a-zA-Z]+(?:[A-Z][a-zA-Z0-9]*)+\s+icon\b')
_INLINE_PRICE = re.compile(r'(?:ab|from)?\s*€\s*[\d.,]+(?:\s*EUR)?', re.IGNORECASE)
_WHITESPACE = re.compile(r'\s+')


def safe_text(value: str | None) -> str:
    """Lowercase and strip a string; empty string for None."""
    return (value or "").strip().lower()


def includes_any(text: str, terms: Iterable[str]) -> bool:
    """Return True if any term appears in text (case-insensitive)."""
    t = safe_text(text)
    return any(term.lower() in t for term in terms)


def clean_scraped_text(text: str) -> str:
    """Strip SVG icon accessibility text, inline prices, and excess whitespace."""
    text = _ICON_TEXT.sub("", text)
    text = _INLINE_PRICE.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


def clean_title(raw: str) -> str:
    """
    Clean a raw scraped title.
    Copied from Event_Finder/app/agents/meetup.py :: _clean_title().
    Delegates to keywords.clean_title() — kept here as a convenience re-export.
    """
    from community_collector.keywords import clean_title as _ct
    return _ct(raw)


def truncate(text: str | None, max_len: int = 1000) -> str | None:
    """Truncate a string to max_len characters, appending '…' if cut."""
    if not text:
        return text
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"
