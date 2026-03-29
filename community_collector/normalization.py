"""
Normalization pipeline: maps raw adapter dicts → CommunityEventRecord.

Each source has its own normalize_* function; a dispatcher routes by source name.
Normalization is separate from tagging (tagging happens after normalization).
"""
from __future__ import annotations
from datetime import datetime, UTC
from community_collector.models import CommunityEventRecord
from community_collector.utils.text_utils import clean_scraped_text, truncate
from community_collector.utils.url_utils import normalize_url
from community_collector.utils.date_utils import (
    parse_datetime, infer_activity, parse_cost_factor
)
from community_collector.tagging import tag_record


def _base_record(raw: dict, source: str) -> dict:
    """Extract common fields present in every raw dict."""
    return {
        "source":           source,
        "source_record_id": raw.get("source_record_id"),
        "source_url":       normalize_url(raw.get("url", "")) or raw.get("url", ""),
        "canonical_url":    normalize_url(raw.get("canonical_url") or raw.get("url")),
        "title":            clean_scraped_text(raw.get("title", "Untitled")),
        "description":      truncate(clean_scraped_text(raw.get("description", "") or "")),
        "organizer_name":   clean_scraped_text(raw.get("organizer") or ""),
        "community_name":   clean_scraped_text(raw.get("group_name") or raw.get("community_name") or ""),
        "venue_name":       clean_scraped_text(raw.get("venue") or raw.get("venue_name") or ""),
        "venue_address":    clean_scraped_text(raw.get("address") or ""),
        "city":             raw.get("city"),
        "country":          raw.get("country"),
        "is_online":        raw.get("is_online"),
        "cost_text":        raw.get("price") or raw.get("cost_text"),
        "currency":         raw.get("currency"),
        "raw_category":     raw.get("category") or raw.get("raw_category"),
        "language":         raw.get("language"),
        "search_term":      raw.get("search_term"),
        "raw_payload":      raw,
        "extraction_timestamp": datetime.now(UTC).isoformat(),
    }


def _enrich(fields: dict) -> dict:
    """Add derived fields: cost_factor, activity, and all tag signals."""
    fields["cost_factor"] = parse_cost_factor(fields.get("cost_text"))

    # Infer activity/recurrence from description + title + community name
    activity_corpus = " ".join(filter(None, [
        fields.get("title"), fields.get("description"),
        fields.get("community_name"),
    ]))
    fields["activity"] = infer_activity(activity_corpus)

    # Infer datetime strings
    raw_dt = fields.get("raw_payload", {})
    for dt_field, raw_key in [("event_datetime_start", "datetime_start"),
                               ("event_datetime_end",   "datetime_end")]:
        dt = parse_datetime(raw_dt.get(raw_key) or raw_dt.get("datetime"))
        fields[dt_field] = dt.isoformat() if dt else raw_dt.get(raw_key)

    # Run tagging
    signals = tag_record(
        title=fields.get("title"),
        description=fields.get("description"),
        organizer_name=fields.get("organizer_name"),
        community_name=fields.get("community_name"),
        venue_name=fields.get("venue_name"),
        cost_text=fields.get("cost_text"),
        raw_category=fields.get("raw_category"),
        source_url=fields.get("source_url"),
        is_online=fields.get("is_online"),
    )
    fields.update(signals)
    return fields


def normalize_meetup(raw: dict) -> CommunityEventRecord | None:
    fields = _base_record(raw, "meetup")
    if not fields["title"] or not fields["source_url"]:
        return None
    # Meetup-specific: 'group_name' is the recurring group
    if fields.get("community_name"):
        fields.setdefault("activity", "recurring")
    _enrich(fields)
    return CommunityEventRecord(**fields)


def normalize_eventbrite(raw: dict) -> CommunityEventRecord | None:
    fields = _base_record(raw, "eventbrite")
    if not fields["title"] or not fields["source_url"]:
        return None
    _enrich(fields)
    return CommunityEventRecord(**fields)


def normalize_luma(raw: dict) -> CommunityEventRecord | None:
    fields = _base_record(raw, "luma")
    if not fields["title"] or not fields["source_url"]:
        return None
    _enrich(fields)
    return CommunityEventRecord(**fields)


def normalize_generic(raw: dict, source: str = "generic") -> CommunityEventRecord | None:
    fields = _base_record(raw, source)
    if not fields["title"] or not fields["source_url"]:
        return None
    _enrich(fields)
    return CommunityEventRecord(**fields)


_NORMALIZERS = {
    "meetup":     normalize_meetup,
    "eventbrite": normalize_eventbrite,
    "luma":       normalize_luma,
}


def normalize(raw: dict, source: str) -> CommunityEventRecord | None:
    """Dispatch to the correct normalizer by source name."""
    fn = _NORMALIZERS.get(source, normalize_generic)
    try:
        return fn(raw)
    except Exception as exc:
        from community_collector.utils.logging_utils import get_logger
        get_logger("normalization").warning(
            "normalization.failed", source=source, error=str(exc),
            title=raw.get("title", "?")
        )
        return None
