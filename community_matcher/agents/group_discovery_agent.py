from __future__ import annotations
import json
from community_matcher.agents import tool


@tool
def group_discovery_tool(brief_json: str) -> str:
    """
    Searches for recurring groups, clubs, and standing meetups matching the search brief.
    Queries both the community database (via txt2sql) and external sources.

    Args:
        brief_json: JSON string of the SearchBrief.

    Returns:
        JSON array of CandidateCommunity objects (category: group).
    """
    from community_matcher.agents.txt2sql_agent import txt2sql_tool

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

        db_results = txt2sql_tool(question)
        return db_results

    except Exception as e:
        return json.dumps({"error": str(e)})
