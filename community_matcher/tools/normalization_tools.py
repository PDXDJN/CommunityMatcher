from community_matcher.agents import tool


@tool
def normalize_candidate(raw_json: str) -> str:
    """
    Normalizes a raw community candidate from any source into CandidateCommunity format.

    Args:
        raw_json: Raw JSON string from a discovery source.

    Returns:
        JSON string conforming to CandidateCommunity schema.
    """
    return raw_json


@tool
def deduplicate_candidates(candidates_json: str) -> str:
    """
    Deduplicates a list of CandidateCommunity objects by name and URL similarity.

    Args:
        candidates_json: JSON array of CandidateCommunity objects.

    Returns:
        Deduplicated JSON array.
    """
    return candidates_json
