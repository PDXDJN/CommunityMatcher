from community_matcher.agents import tool


@tool
def resolve_district(location_text: str) -> str:
    """
    Resolves a freeform location string to a canonical city district.

    Args:
        location_text: Raw location description from the user.

    Returns:
        Canonical district name string, or empty string if unresolved.
    """
    return ""


@tool
def estimate_travel_time(origin: str, destination: str, mode: str = "transit") -> str:
    """
    Estimates travel time between two locations.

    Args:
        origin: Starting point address or district.
        destination: Target address or district.
        mode: Travel mode — "transit", "walking", or "cycling".

    Returns:
        JSON object with estimated minutes.
    """
    return '{"minutes": 0}'
