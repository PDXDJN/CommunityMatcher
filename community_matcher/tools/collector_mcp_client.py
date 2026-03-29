"""
MCP client for the CommunityCollector server.

Provides a synchronous wrapper around the collector MCP server so the
orchestrator can trigger a live search without importing Playwright directly.

The collector server runs as a subprocess over stdio — the standard local
MCP transport. This isolates Playwright from the matcher process and avoids
event-loop conflicts.

Usage:
    from community_matcher.tools.collector_mcp_client import live_search

    preamble = live_search(["AI meetup Berlin", "python workshop"])
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path
import structlog

log = structlog.get_logger()

# Resolve the mcp_server entry point relative to this package
_SERVER_SCRIPT = str(
    Path(__file__).parent.parent.parent / "community_collector" / "mcp_server.py"
)


async def _call_search_communities(terms: list[str], max_results: int = 25) -> dict:
    """Async: spawn the collector MCP server, call search_communities, return result dict."""
    from mcp import StdioServerParameters, stdio_client
    from mcp.client.session import ClientSession

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[_SERVER_SCRIPT],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_communities",
                {"search_terms": terms, "max_results_per_source": max_results},
            )
            # result.content is a list of TextContent objects
            if result.content:
                raw = result.content[0].text
                return json.loads(raw)
            return {"summary": "No response from collector server", "records_saved": 0}


def live_search(
    terms: list[str],
    max_results: int = 25,
    print_progress: bool = True,
) -> str | None:
    """
    Synchronous wrapper: spawn the collector MCP server, run a live search,
    return a preamble string to display to the user (or None on failure).

    Args:
        terms: Search terms to pass to the collector.
        max_results: Max results per source.
        print_progress: If True, print a progress message to stdout.

    Returns:
        A preamble string like "I searched live and found …" or None on error.
    """
    if print_progress:
        print(
            "\n[Searching live — nothing found in local database. "
            "This may take 1-2 minutes…]\n",
            flush=True,
        )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                _call_search_communities(terms, max_results)
            )
        finally:
            loop.close()

        if result.get("error"):
            log.warning("collector_mcp_client.error", error=result["error"])
            return None

        summary = result.get("summary", "Live search complete.")
        log.info("collector_mcp_client.done", summary=summary)
        return (
            "I couldn't find much in my local database, so I did a live search — "
            "this took a few minutes but here's what I found:\n\n"
        )

    except Exception as exc:
        log.warning("collector_mcp_client.failed", error=str(exc))
        return None
