from community_matcher.agents import tool


@tool
def web_search(query: str, max_results: int = 10) -> str:
    """
    Performs a web search for community events or groups.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.

    Returns:
        JSON array of search result objects.
    """
    return "[]"


@tool
def meetup_search(query: str, location: str) -> str:
    """
    Searches Meetup.com for groups and events.

    Args:
        query: Topic or keyword to search.
        location: City or region string.

    Returns:
        JSON array of Meetup group objects.
    """
    return "[]"
