"""
MCP server for the CommunityCollector.

Exposes the Playwright-based community scraper as a single MCP tool so that
the CommunityMatcher orchestrator (and the Strands Agent) can trigger targeted
live searches without directly importing the collector module.

Running this server:
    python -m community_collector.mcp_server

Or via the CLI shim:
    python community_collector/mcp_server.py

The server communicates over stdio (default FastMCP transport), which is the
standard for local subprocess-based MCP integrations.

Environment variables forwarded from the parent process:
    CM_SQLITE_DB_PATH — path to the shared SQLite database (default: output/communitymatcher.db)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="community-collector",
    instructions=(
        "Searches live sources (Meetup, Luma) for community events and groups in Berlin, "
        "saves results to the shared database, and returns a summary of what was found. "
        "Use this when the local database has no results for a user query."
    ),
)


@mcp.tool()
def search_communities(
    search_terms: list[str],
    max_results_per_source: int = 25,
) -> str:
    """
    Search live community sources for Berlin events and groups matching
    the given search terms. Results are saved to the shared SQLite database.

    Args:
        search_terms: List of natural-language search terms, e.g.
                      ["AI meetup", "python workshop", "maker Berlin"].
                      Up to 6 terms are used; extras are ignored.
        max_results_per_source: Maximum results to collect per source (default 25).

    Returns:
        JSON object with keys:
          - terms_used: list of search terms actually run
          - sources_run: list of source names
          - records_saved: total new records written to the database
          - summary: human-readable summary string
    """
    from community_collector.orchestrator import run_collection
    from community_collector.config import CollectorConfig
    import structlog

    log = structlog.get_logger()

    terms = [str(t).strip() for t in search_terms if str(t).strip()][:6]
    if not terms:
        terms = ["tech community Berlin"]

    log.info("mcp_server.search_start", terms=terms)

    try:
        cfg = CollectorConfig(
            search_terms=terms,
            sources_to_run=["meetup", "luma"],
            max_results_per_source=max(1, min(50, max_results_per_source)),
            headless=True,
        )
        run_collection(cfg)

        result = {
            "terms_used": terms,
            "sources_run": ["meetup", "luma"],
            "records_saved": -1,   # collector doesn't yet return a count; -1 = unknown
            "summary": f"Live search complete for: {', '.join(terms)}. Results saved to database.",
        }
        log.info("mcp_server.search_done", terms=terms)
        return json.dumps(result)

    except Exception as exc:
        log.warning("mcp_server.search_failed", error=str(exc))
        return json.dumps({
            "terms_used": terms,
            "sources_run": [],
            "records_saved": 0,
            "summary": f"Live search failed: {exc}",
            "error": str(exc),
        })


if __name__ == "__main__":
    mcp.run()
