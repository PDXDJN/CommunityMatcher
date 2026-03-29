from __future__ import annotations
import json
from community_matcher.agents import tool


@tool
def event_discovery_tool(brief_json: str) -> str:
    """
    Searches for one-off events and activities matching the search brief.
    Queries both the community database (via txt2sql) and external sources.

    Args:
        brief_json: JSON string of the SearchBrief.

    Returns:
        JSON array of CandidateCommunity objects (category: event).
    """
    from community_matcher.agents.txt2sql_agent import txt2sql_tool

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

        db_results = txt2sql_tool(question)
        return db_results

    except Exception as e:
        return json.dumps({"error": str(e)})
