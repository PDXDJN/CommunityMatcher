"""
RecommendationWriter agent — formats ranked candidates into user-facing
recommendation buckets with fit explanations. Template-based, no LLM.

Events from the same community are rolled up into a single community entry
so the user sees "Python Meetup Berlin (3 upcoming events)" rather than
three separate rows for the same group.
"""
from __future__ import annotations
import json
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _short_title(row: dict) -> str:
    return row.get("title") or row.get("name") or "(untitled)"


def _community_key(row: dict) -> str | None:
    """Return a canonical community identity string, or None for standalone events."""
    name = (row.get("community_name") or "").strip()
    organizer = (row.get("organizer_name") or "").strip()
    # Prefer community_name; fall back to organizer_name; ignore if both empty
    key = name or organizer or None
    return key.lower() if key else None


def _url(row: dict) -> str:
    return (
        row.get("source_url")
        or row.get("canonical_url")
        or row.get("url")
        or ""
    )


def _score(row: dict) -> float:
    return row.get("_scores", {}).get("total", 0.0)


def _fit_reason(row: dict, vibe: dict | None = None) -> str:
    """Generate a one-line fit explanation from scores and vibe dimensions."""
    scores = row.get("_scores", {})
    v = vibe or row.get("_vibe", {})
    reasons = []

    if scores.get("interest_alignment", 0) > 0.6:
        reasons.append("matches your interests")
    if scores.get("newcomer_friendliness", 0) > 0.6:
        reasons.append("newcomer-friendly")
    if scores.get("vibe_alignment", 0) > 0.6:
        reasons.append("fits your social style")
    if scores.get("language_fit", 0) >= 1.0:
        reasons.append("English-language")
    if scores.get("recurrence_strength", 0) >= 0.8:
        reasons.append("recurring community")
    if scores.get("risk_sanity", 0) >= 0.9:
        reasons.append("established group")
    if v.get("corporate_ness", 1) < 0.3:
        reasons.append("grassroots/community-run")
    if v.get("alcohol_centrality", 1) < 0.2 and scores.get("newcomer_friendliness", 0) > 0.5:
        reasons.append("alcohol-light")

    tags_raw = row.get("topic_signals") or row.get("tags") or ""
    if isinstance(tags_raw, str) and tags_raw.startswith("["):
        try:
            tags = json.loads(tags_raw)[:3]
            if tags:
                reasons.append(f"tagged: {', '.join(tags)}")
        except Exception:
            pass

    return "; ".join(reasons) if reasons else "general match"


# ── Community rollup ──────────────────────────────────────────────────────────

def _group_by_community(rows: list[dict]) -> list[dict]:
    """
    Roll individual event rows up into community entries.

    Rows that share a community_name or organizer_name are merged into a
    single representative entry. The representative gets:
      - The community name as its title
      - The URL of the highest-scoring event
      - A list of upcoming event titles in _events
      - Scores from the highest-scoring event
      - _vibe aggregated from all events (averaged floats)
      - _event_count: total events found for this community

    Rows with no community identity (standalone one-off events with no organizer)
    are kept as-is with _event_count = 1.
    """
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()

    # Build groups: key → list of rows
    groups: dict[str, list[dict]] = {}
    standalone: list[dict] = []

    for row in rows:
        key = _community_key(row)
        if key:
            groups.setdefault(key, []).append(row)
        else:
            standalone.append(row)

    result: list[dict] = []

    for key, group_rows in groups.items():
        # Sort group by score descending
        group_rows.sort(key=_score, reverse=True)
        best = group_rows[0]

        # Collect upcoming event titles (future-dated or undated = community/recurring)
        upcoming = []
        for r in group_rows:
            dt = r.get("event_datetime_start")
            is_future = not dt or str(dt) > now_iso
            if is_future:
                t = _short_title(r)
                if t not in upcoming:
                    upcoming.append(t)

        # Aggregate vibe scores
        vibe_keys = ["newcomer_friendliness", "vibe_alignment", "alcohol_centrality", "corporate_ness"]
        agg_vibe: dict[str, float] = {}
        for vk in vibe_keys:
            vals = [r.get("_vibe", {}).get(vk, 0.5) for r in group_rows if "_vibe" in r]
            if vals:
                agg_vibe[vk] = round(sum(vals) / len(vals), 2)
        for vk in ["is_casual", "is_technical", "is_creative"]:
            bools = [r.get("_vibe", {}).get(vk, False) for r in group_rows if "_vibe" in r]
            if bools:
                agg_vibe[vk] = any(bools)

        # Build the rolled-up entry
        community_name = (
            group_rows[0].get("community_name")
            or group_rows[0].get("organizer_name")
            or _short_title(best)
        )
        entry = dict(best)
        entry["title"] = community_name
        entry["_events"] = upcoming
        entry["_event_count"] = len(group_rows)
        entry["_vibe"] = {**best.get("_vibe", {}), **agg_vibe}
        result.append(entry)

    # Standalone events pass through unchanged
    for row in standalone:
        entry = dict(row)
        entry["_event_count"] = 1
        result.append(entry)

    # Re-sort by score
    result.sort(key=_score, reverse=True)
    return result


# ── Formatting ────────────────────────────────────────────────────────────────

def _format_community(i: int, row: dict) -> list[str]:
    """Format one community entry (possibly with rolled-up events)."""
    lines = [f"{i}. **{_short_title(row)}**"]

    event_count = row.get("_event_count", 1)
    events = row.get("_events", [])

    if event_count > 1:
        label = f"{event_count} upcoming events" if event_count > 1 else "1 event"
        lines[0] += f"  _{label}_"

    reason = _fit_reason(row, row.get("_vibe"))
    if reason:
        lines.append(f"   _{reason}_")

    # Show first 3 upcoming event names as sub-bullets
    for evt_title in events[:3]:
        lines.append(f"   • {evt_title}")
    if len(events) > 3:
        lines.append(f"   • …and {len(events) - 3} more")

    url = _url(row)
    if url:
        lines.append(f"   {url}")

    return lines


@tool
def recommendation_writer_tool(ranked_json: str) -> str:
    """
    Produces user-facing recommendation output from ranked candidates.

    Groups results into:
      - Best overall fits (top 3 community entries by score)
      - Best first step (highest newcomer_friendliness)
      - Best recurring community (highest recurrence_strength)

    Events from the same community/organizer are rolled up into a single
    community entry so the user sees the group rather than individual events.

    Args:
        ranked_json: JSON array of scored candidates (from ranking_tool).

    Returns:
        Formatted markdown recommendation string for display to the user.
    """
    try:
        rows = json.loads(ranked_json)
        if not isinstance(rows, list) or not rows:
            return "No matching communities found. Try describing what you're looking for differently."

        # Roll individual events up to their parent communities
        rolled = _group_by_community(rows)

        lines: list[str] = []

        # Best overall: top 3 community entries
        best = rolled[:3]
        lines.append(f"**Here are your top matches** ({len(rolled)} communities found):\n")
        for i, row in enumerate(best, 1):
            lines.extend(_format_community(i, row))
            lines.append("")

        rest = rolled[3:]

        # Best first step: highest newcomer_friendliness outside top-3
        newcomer_pick = max(
            rest,
            key=lambda r: r.get("_vibe", r.get("_scores", {})).get("newcomer_friendliness", 0)
                          if isinstance(r.get("_vibe"), dict)
                          else r.get("_scores", {}).get("newcomer_friendliness", 0),
            default=None,
        )
        if newcomer_pick:
            nf = newcomer_pick.get("_vibe", {}).get("newcomer_friendliness") \
                 or newcomer_pick.get("_scores", {}).get("newcomer_friendliness", 0)
            if nf and float(nf) > 0.6:
                lines.append("**Best first step** (most welcoming to newcomers):")
                lines.extend(_format_community(1, newcomer_pick))
                lines.append("")

        # Best recurring
        recurring_pick = max(
            rest,
            key=lambda r: r.get("_scores", {}).get("recurrence_strength", 0),
            default=None,
        )
        if recurring_pick and recurring_pick.get("_scores", {}).get("recurrence_strength", 0) >= 0.8:
            if not newcomer_pick or _short_title(recurring_pick) != _short_title(newcomer_pick):
                lines.append("**Best recurring community:**")
                lines.extend(_format_community(1, recurring_pick))
                lines.append("")

        lines.append("_Type 'more' to see more options, or tell me what you'd like to refine._")

        log.info("recommendation_writer.done", communities=len(rolled), original_rows=len(rows))
        return "\n".join(lines)
    except Exception as exc:
        log.warning("recommendation_writer.error", error=str(exc))
        return ranked_json  # fallback: return raw JSON
