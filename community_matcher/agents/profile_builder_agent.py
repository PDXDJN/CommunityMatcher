"""
ProfileBuilder agent — extracts structured UserProfile field updates from
one user conversation turn using the configured LLM.

Returns a JSON object of fields to merge into the existing profile.
Fields omitted from the output are left unchanged.
"""
from __future__ import annotations
import json
import structlog
from community_matcher.agents import tool

log = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are a profile extraction specialist for CommunityMatcher Berlin.

Given a user message, extract structured profile updates as a JSON object.
Only include fields explicitly mentioned or clearly implied.
Return {} if nothing is extractable.

Valid field values:
  goals        : list, values from ["friends", "networking", "learning", "community"]
  interests    : list, values from ["ai", "python", "data_science", "startup", "cloud",
                 "cybersecurity", "blockchain", "maker", "design", "gaming",
                 "social_coding", "language_exchange", "music", "art",
                 "fitness", "wellness", "tech"]
  social_mode  : one of "workshop", "talk", "social", "project", "conference"
  environment  : one of "newcomer_friendly", "deep_community"
  language_pref: list, values from ["english", "german"]
  logistics    : {"districts": [list of Berlin district names], "max_travel_minutes": int}
  budget       : one of "free_only", "low", "medium", "any"
  values       : list of strings (e.g. ["inclusive", "lgbtq_friendly"])
  dealbreakers : list of strings (e.g. ["too corporate", "too loud", "alcohol"])

Also include a "_confidence" object mapping each extracted field name to one of:
  "explicit"   — user stated it directly ("I want friends", "I love Python")
  "inferred"   — clearly implied but not stated verbatim ("I'm new here" → newcomer_friendly)

Example output:
  {"interests": ["ai"], "goals": ["learning"],
   "_confidence": {"interests": "explicit", "goals": "inferred"}}

Output ONLY the JSON object. No explanation. No markdown fences.
"""


@tool
def profile_builder_tool(conversation_turn: str) -> str:
    """
    Extracts structured profile updates from a single conversation turn.

    Calls the LLM to parse the user's message and return a JSON object
    of UserProfile field updates to merge into the current session profile.

    Args:
        conversation_turn: The raw user message from the current turn.

    Returns:
        JSON object of profile field updates (partial UserProfile). Returns {}
        on extraction failure or when nothing extractable was found.
    """
    from community_matcher.agents.llm_client import llm_json

    try:
        raw = llm_json(_SYSTEM_PROMPT, conversation_turn)
        # Validate it parses as a dict
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return "{}"
        log.info("profile_builder.extracted", fields=list(parsed.keys()))
        return json.dumps(parsed)
    except Exception as exc:
        log.warning("profile_builder.error", error=str(exc))
        return "{}"
