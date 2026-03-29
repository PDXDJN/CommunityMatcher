from __future__ import annotations
import json
from community_matcher.agents import tool

# Minimum results from txt2sql before we bother with semantic fallback
_SEMANTIC_FALLBACK_THRESHOLD = 3


@tool
def group_discovery_tool(brief_json: str) -> str:
    """
    Searches for recurring groups, clubs, and standing meetups matching the search brief.
    Queries both the community database (via txt2sql) and external sources.
    Falls back to semantic keyword search when txt2sql returns fewer than
    {threshold} results (e.g. open-ended queries like "tinker with hardware").

    Args:
        brief_json: JSON string of the SearchBrief.

    Returns:
        JSON array of CandidateCommunity objects (category: group).
    """.format(threshold=_SEMANTIC_FALLBACK_THRESHOLD)
    from community_matcher.agents.txt2sql_agent import txt2sql_tool
    from community_matcher.agents.semantic_search_tool import semantic_search_tool

    try:
        brief = json.loads(brief_json)
        archetypes = brief.get("archetypes", {})
        query_intents = brief.get("query_intents", [])
        location = brief.get("location", "")

        # Build a natural language question for the txt2sql agent
        intent_str = ", ".join(query_intents) if query_intents else "community groups"
        archetype_str = ", ".join(archetypes.keys()) if archetypes else ""
        question = (
            f"Find recurring community groups related to: {intent_str}."
            + (f" Topics: {archetype_str}." if archetype_str else "")
            + (f" Location context: {location}." if location else "")
            + " Include their social links. Order by keyword affinity descending. Limit 50."
        )

        db_results_raw = txt2sql_tool(question)
        db_results = json.loads(db_results_raw) if db_results_raw else []

        # If txt2sql returned an error or too few rows, try semantic fallback
        if (
            isinstance(db_results, dict)
            or (isinstance(db_results, list) and len(db_results) < _SEMANTIC_FALLBACK_THRESHOLD)
        ):
            semantic_query = intent_str
            if archetype_str:
                semantic_query += f" {archetype_str}"
            fallback_raw = semantic_search_tool(semantic_query)
            fallback_rows = json.loads(fallback_raw) if fallback_raw else []
            if isinstance(fallback_rows, list) and fallback_rows:
                # Merge with any existing rows, dedup by source_url
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

        return json.dumps(db_results) if not isinstance(db_results_raw, str) or isinstance(db_results, list) else db_results_raw

    except Exception as e:
        return json.dumps({"error": str(e)})
