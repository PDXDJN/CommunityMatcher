"""
RecommendationWriter agent — formats ranked candidates into user-facing
recommendation buckets with fit explanations. Template-based, no LLM.
"""
from __future__ import annotations
import json
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()


def _short_title(row: dict) -> str:
    return row.get("title") or row.get("name") or "(untitled)"


def _url(row: dict) -> str:
    return (
        row.get("source_url")
        or row.get("canonical_url")
        or row.get("url")
        or ""
    )


def _score(row: dict) -> float:
    return row.get("_scores", {}).get("total", 0.0)


def _fit_reason(row: dict) -> str:
    """Generate a one-line fit explanation from scores."""
    scores = row.get("_scores", {})
    reasons = []

    if scores.get("interest_alignment", 0) > 0.6:
        reasons.append("matches your interests")
    if scores.get("newcomer_friendliness", 0) > 0.6:
        reasons.append("newcomer-friendly")
    if scores.get("vibe_alignment", 0) > 0.6:
        reasons.append("fits your social style")
    if scores.get("language_fit", 0) >= 1.0:
        reasons.append("English-language event")
    if scores.get("recurrence_strength", 0) >= 0.8:
        reasons.append("recurring community")
    if scores.get("risk_sanity", 0) >= 0.9:
        reasons.append("established event")

    tags_raw = row.get("topic_signals") or row.get("tags") or ""
    if isinstance(tags_raw, str) and tags_raw.startswith("["):
        try:
            tags = json.loads(tags_raw)[:4]
            if tags:
                reasons.append(f"tagged: {', '.join(tags)}")
        except Exception:
            pass

    return "; ".join(reasons) if reasons else "general match"


def _format_item(i: int, row: dict) -> list[str]:
    lines = [f"{i}. **{_short_title(row)}**"]
    reason = _fit_reason(row)
    if reason:
        lines.append(f"   _{reason}_")
    url = _url(row)
    if url:
        lines.append(f"   {url}")
    return lines


@tool
def recommendation_writer_tool(ranked_json: str) -> str:
    """
    Produces user-facing recommendation output from ranked candidates.

    Groups results into:
      - Best overall fits (top 3 by score)
      - Best first step (highest newcomer_friendliness)
      - Best recurring community (highest recurrence_strength)
      - Stretch options (lower-scoring but interesting)

    Args:
        ranked_json: JSON array of scored candidates (from ranking_tool).

    Returns:
        Formatted markdown recommendation string for display to the user.
    """
    try:
        rows = json.loads(ranked_json)
        if not isinstance(rows, list) or not rows:
            return "No matching communities found. Try describing what you're looking for differently."

        lines: list[str] = []

        # Best overall: top 3
        best = rows[:3]
        lines.append(f"**Here are your top matches** ({len(rows)} found):\n")
        for i, row in enumerate(best, 1):
            lines.extend(_format_item(i, row))
            lines.append("")

        # Best first step: highest newcomer_friendliness outside top-3
        rest = rows[3:]
        newcomer_pick = max(rest, key=lambda r: r.get("_scores", {}).get("newcomer_friendliness", 0), default=None)
        if newcomer_pick and newcomer_pick.get("_scores", {}).get("newcomer_friendliness", 0) > 0.6:
            lines.append("**Best first step** (most welcoming to newcomers):")
            lines.extend(_format_item(1, newcomer_pick))
            lines.append("")

        # Best recurring
        recurring_pick = max(rest, key=lambda r: r.get("_scores", {}).get("recurrence_strength", 0), default=None)
        if recurring_pick and recurring_pick.get("_scores", {}).get("recurrence_strength", 0) >= 0.8:
            title = _short_title(recurring_pick)
            if not newcomer_pick or title != _short_title(newcomer_pick):
                lines.append("**Best recurring community:**")
                lines.extend(_format_item(1, recurring_pick))
                lines.append("")

        lines.append("_Type 'more' to see more options, or tell me what you'd like to refine._")

        log.info("recommendation_writer.done", rows=len(rows))
        return "\n".join(lines)
    except Exception as exc:
        log.warning("recommendation_writer.error", error=str(exc))
        return ranked_json  # fallback: return raw JSON
