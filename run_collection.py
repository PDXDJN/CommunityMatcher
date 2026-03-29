"""
One-shot collection runner via the MCP server.
Covers all archetype vocabulary in three batches.
Run from project root with the venv active.
"""
from __future__ import annotations
import sys
sys.path.insert(0, ".")

from community_matcher.tools.collector_mcp_client import live_search

BATCHES = [
    # Batch A — AI / data / python / cloud
    ["AI meetup Berlin", "machine learning Berlin", "data science Berlin",
     "python developer Berlin", "cloud DevOps Berlin", "LLM AI community Berlin"],

    # Batch B — startup / networking / maker / hardware
    ["startup networking Berlin", "founder meetup Berlin", "entrepreneurship Berlin",
     "maker hackerspace Berlin", "hardware hacking Berlin", "open source Berlin"],

    # Batch C — social / gaming / design / newcomer / queer-tech
    ["social coding Berlin", "game dev Berlin", "design community Berlin",
     "newcomer English Berlin", "cybersecurity infosec Berlin", "blockchain web3 Berlin"],
]

def main():
    from community_matcher.db.connection import execute_query

    before = execute_query("SELECT COUNT(*) as n FROM scrape_record")[0]["n"]
    print(f"\nDB before: {before} records\n")

    for i, terms in enumerate(BATCHES, 1):
        print(f"{'='*60}")
        print(f"Batch {i}/{len(BATCHES)}: {', '.join(terms)}")
        print(f"{'='*60}")
        result = live_search(terms, max_results=40, print_progress=False)
        if result:
            print("  Collection complete.")
        else:
            print("  Collection returned None (check logs for errors).")

    after = execute_query("SELECT COUNT(*) as n FROM scrape_record")[0]["n"]
    by_source = execute_query(
        "SELECT source, COUNT(*) as n FROM scrape_record GROUP BY source ORDER BY n DESC"
    )
    print(f"\n{'='*60}")
    print(f"DB after:  {after} records  (+{after - before} new)")
    for r in by_source:
        print(f"  {r['source']}: {r['n']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
