from __future__ import annotations
import json
from community_matcher.agents import tool

# Minimum results from txt2sql before we bother with semantic fallback
_SEMANTIC_FALLBACK_THRESHOLD = 3


@tool
def event_discovery_tool(brief_json: str) -> str:
    """
    Searches for one-off events and activities matching the search brief.
    Queries both the community database (via txt2sql) and external sources.
    Falls back to semantic keyword search when txt2sql returns fewer than
    {threshold} results (e.g. open-ended queries like "tinker with hardware").

    Args:
        brief_json: JSON string of the SearchBrief.

    Returns:
        JSON array of CandidateCommunity objects (category: event).
    """.format(threshold=_SEMANTIC_FALLBACK_THRESHOLD)
    from community_matcher.agents.txt2sql_agent import txt2sql_tool
    from community_matcher.agents.semantic_search_tool import semantic_search_tool

    try:
        brief = json.loads(brief_json)
        query_intents = brief.get("query_intents", [])
        location = brief.get("location", "")

        intent_str = ", ".join(query_intents) if query_intents else "events"
        question = (
            f"Find one-off events related to: {intent_str}."
            + (f" Location context: {location}." if location else "")
            + " Filter to communities where activity = 'one-off' or similar."
            + " Include social links. Limit 50."
        )

        db_results_raw = txt2sql_tool(question)
        db_results = json.loads(db_results_raw) if db_results_raw else []

        # If txt2sql returned an error or too few rows, try semantic fallback
        if (
            isinstance(db_results, dict)
            or (isinstance(db_results, list) and len(db_results) < _SEMANTIC_FALLBACK_THRESHOLD)
        ):
            fallback_raw = semantic_search_tool(intent_str, json.dumps(brief.get("interests", [])))
            fallback_rows = json.loads(fallback_raw) if fallback_raw else []
            if isinstance(fallback_rows, list) and fallback_rows:
                existing_urls = {
                    r.get("source_url") for r in (db_results if isinstance(db_results, list) else [])
                }
                for row in fallback_rows:
                    if row.get("source_url") not in existing_urls:
                        if isinstance(db_results, list):
                            db_results.append(row)
                        else:
                            db_results = fallback_rows
                        existing_urls.add(row.get("source_url"))

        return json.dumps(db_results) if isinstance(db_results, list) else db_results_raw

    except Exception as e:
        return json.dumps({"error": str(e)})
