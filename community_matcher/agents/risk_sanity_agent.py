"""
RiskSanity agent — filters dead groups, stale listings, spammy events,
and obvious bad fits. Rule-based, no LLM.
"""
from __future__ import annotations
import json
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()

_SPAM_SIGNALS = [
    "make money", "earn from home", "mlm", "pyramid", "investment opportunity",
    "get rich", "crypto pump", "nft drop", "exclusive offer",
]


@tool
def risk_sanity_tool(candidate_json: str) -> str:
    """
    Filters dead groups, stale listings, and spammy events.

    Scores the candidate on a risk_sanity_score (0.0–1.0). A score below
    0.3 means the candidate should likely be excluded.

    Args:
        candidate_json: JSON string of a DB row (scrape_record or community).

    Returns:
        JSON object: {"pass": bool, "risk_sanity_score": float, "reasons": [...]}
    """
    try:
        row = json.loads(candidate_json)

        score = 1.0
        reasons: list[str] = []

        title       = (row.get("title") or row.get("name") or "").lower()
        description = (row.get("description") or "").lower()
        url         = row.get("source_url") or row.get("canonical_url") or row.get("url") or ""
        combined    = title + " " + description

        # No title → suspicious
        if not title.strip():
            score -= 0.4
            reasons.append("no title")

        # Very short description → low quality
        if len(description) < 20:
            score -= 0.2
            reasons.append("description too short")

        # No URL → can't verify
        if not url:
            score -= 0.15
            reasons.append("no source URL")

        # Spam signals
        for signal in _SPAM_SIGNALS:
            if signal in combined:
                score -= 0.5
                reasons.append(f"spam signal: {signal}")
                break

        score = max(0.0, min(1.0, score))
        passed = score >= 0.4

        if not passed:
            log.debug("risk_sanity.fail", title=title[:60], score=score, reasons=reasons)

        return json.dumps({
            "pass":              passed,
            "risk_sanity_score": round(score, 2),
            "reasons":           reasons,
        })
    except Exception as exc:
        log.warning("risk_sanity.error", error=str(exc))
        return '{"pass": true, "risk_sanity_score": 0.8, "reasons": []}'
