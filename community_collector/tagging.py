"""
Rule-based metadata tagging for collected community/event records.

All keyword maps, scoring constants, and the category map live in
keywords.py (the canonical source). This module applies them.
"""
from __future__ import annotations
from community_collector.keywords import (
    TOPIC_KEYWORDS,
    FORMAT_KEYWORDS,
    AUDIENCE_KEYWORDS,
    VIBE_KEYWORDS,
    LOCATION_KEYWORDS,
    normalize_category,
)
from community_collector.utils.text_utils import safe_text, includes_any


def _build_corpus(*parts: str | None) -> str:
    return " ".join(p for p in parts if p).lower()


def infer_topic_signals(corpus: str) -> list[str]:
    return sorted(tag for tag, kws in TOPIC_KEYWORDS.items()
                  if includes_any(corpus, kws))


def infer_format_signals(corpus: str) -> list[str]:
    return sorted(tag for tag, kws in FORMAT_KEYWORDS.items()
                  if includes_any(corpus, kws))


def infer_audience_signals(corpus: str) -> list[str]:
    return sorted(tag for tag, kws in AUDIENCE_KEYWORDS.items()
                  if includes_any(corpus, kws))


def infer_vibe_signals(corpus: str) -> list[str]:
    return sorted(tag for tag, kws in VIBE_KEYWORDS.items()
                  if includes_any(corpus, kws))


def infer_location_tags(corpus: str, is_online: bool | None) -> list[str]:
    tags = sorted(tag for tag, kws in LOCATION_KEYWORDS.items()
                  if includes_any(corpus, kws))
    if is_online is True and "online" not in tags:
        tags.append("online")
    if is_online is False and "in_person" not in tags:
        tags.append("in_person")
    return tags


def tag_record(
    title: str | None,
    description: str | None,
    organizer_name: str | None,
    community_name: str | None,
    venue_name: str | None,
    cost_text: str | None,
    raw_category: str | None,
    source_url: str | None,
    is_online: bool | None = None,
) -> dict[str, list[str]]:
    """
    Run all tagging passes and return a dict of signal lists.
    Keys: tags, topic_signals, format_signals, audience_signals, vibe_signals
    """
    corpus = _build_corpus(
        title, description, organizer_name, community_name,
        venue_name, cost_text, raw_category, source_url,
    )
    topic    = infer_topic_signals(corpus)
    fmt      = infer_format_signals(corpus)
    audience = infer_audience_signals(corpus)
    vibe     = infer_vibe_signals(corpus)
    loc      = infer_location_tags(corpus, is_online)

    all_tags = sorted(set(topic + fmt + audience + vibe + loc))

    return {
        "tags":             all_tags,
        "topic_signals":    topic,
        "format_signals":   fmt,
        "audience_signals": audience,
        "vibe_signals":     vibe,
    }
