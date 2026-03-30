"""
Bulk Luma event collection for Berlin — no browser/Playwright required.

Runs the LumaAdapter directly (bypasses the Playwright orchestrator),
collects ~1000+ unique events across broad + specific search sweeps,
normalizes, deduplicates, and saves to the SQLite DB.

Usage:
    python luma_bulk_collect.py [--max MAX] [--db DB_PATH]
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent))

from community_collector.adapters.luma_adapter import LumaAdapter
from community_collector.config import CollectorConfig, DB_PATH, OUTPUT_DIR
from community_collector.normalization import normalize
from community_collector.persistence import init_db, save_records
from community_collector.utils.logging_utils import configure_logging, get_logger

log = get_logger("luma_bulk_collect")

# Sweep 1: broad empty query returns ALL upcoming Berlin events (most important)
# Sweep 2+: targeted terms to fill gaps the broad sweep misses
_SEARCH_SWEEPS: list[str] = [
    "",                          # all Berlin events (no filter)
    "tech AI",
    "startup founders",
    "community social",
    "hackathon workshop",
    "machine learning",
    "open source",
    "maker hardware",
    "gaming",
    "design UX",
    "data science",
    "python",
    "blockchain web3",
    "queer LGBTQ",
    "women tech",
    "expat newcomer Berlin",
    "language exchange",
    "networking mixer",
    "art culture",
    "music",
    "fitness sport",
    "coworking",
    "cybersecurity",
    "cloud devops",
    "LLM agents",
]


async def collect(max_events: int, db_path: str) -> int:
    configure_logging("INFO")
    init_db(db_path)

    config = CollectorConfig(
        location="Berlin",
        country="Germany",
        max_results_per_source=max_events,
        sources_to_run=["luma"],
    )
    adapter = LumaAdapter()

    all_raw: list[dict] = []
    seen_urls: set[str] = set()

    for sweep_idx, term in enumerate(_SEARCH_SWEEPS):
        if len(seen_urls) >= max_events:
            log.info("luma_bulk.target_reached", target=max_events)
            break

        label = repr(term) if term else "(all events)"
        log.info("luma_bulk.sweep", idx=sweep_idx + 1,
                 total_sweeps=len(_SEARCH_SWEEPS),
                 term=label, collected_so_far=len(seen_urls))

        try:
            raw_batch = await adapter.collect(None, config, term)  # browser=None (not used)
        except Exception as exc:
            log.warning("luma_bulk.sweep_failed", term=label, error=str(exc))
            continue

        new = 0
        for r in raw_batch:
            url = (r.get("url") or "").strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_raw.append(r)
                new += 1

        log.info("luma_bulk.sweep_done", term=label,
                 new=new, total=len(seen_urls))

    print(f"\nCollected {len(all_raw)} unique Luma events across {len(_SEARCH_SWEEPS)} sweeps.")

    # Normalize
    normalized = []
    for raw in all_raw:
        rec = normalize(raw, "luma")
        if rec:
            normalized.append(rec)
    print(f"Normalized: {len(normalized)} records")

    # Save to DB
    saved = save_records(normalized, db_path)
    print(f"Saved/upserted: {saved} records → {db_path}")

    # Also dump raw JSON for inspection
    ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(db_path).parent / f"luma_bulk_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "raw_luma.json").write_text(
        json.dumps(all_raw, indent=2, default=str), encoding="utf-8"
    )
    print(f"Raw JSON → {out_dir}/raw_luma.json")

    return saved


def main() -> None:
    p = argparse.ArgumentParser(description="Bulk-collect Luma events for Berlin")
    p.add_argument("--max", type=int, default=1200,
                   help="Target number of unique events (default: 1200)")
    p.add_argument("--db", default=str(DB_PATH),
                   help="SQLite DB path")
    args = p.parse_args()

    saved = asyncio.run(collect(args.max, args.db))
    print(f"\nDone. {saved} records saved.")


if __name__ == "__main__":
    main()
