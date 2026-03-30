"""
Bulk event collection for Berlin using API-based adapters (no browser needed).

Runs MeetupAdapter + LumaAdapter directly, bypassing the Playwright orchestrator.
Targets ~1000+ unique events across all DEFAULT_BERLIN_TOPICS search terms.

Usage:
    python bulk_collect.py [--max MAX] [--sources meetup,luma] [--db DB_PATH]
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from community_collector.config import CollectorConfig, DB_PATH
from community_collector.keywords import DEFAULT_BERLIN_TOPICS
from community_collector.normalization import normalize
from community_collector.persistence import init_db, save_records
from community_collector.utils.logging_utils import configure_logging, get_logger

log = get_logger("bulk_collect")


async def run_adapter(adapter, config, term: str) -> list[dict]:
    try:
        return await adapter.collect(None, config, term)
    except Exception as exc:
        log.warning("bulk_collect.adapter_failed",
                    source=adapter.source_name, term=repr(term), error=str(exc))
        return []


async def collect(
    sources: list[str],
    max_events: int,
    db_path: str,
    terms: list[str],
) -> dict[str, int]:
    configure_logging("INFO")
    init_db(db_path)

    config = CollectorConfig(
        location="Berlin",
        country="Germany",
        max_results_per_source=max_events,
        sources_to_run=sources,
    )

    # Instantiate adapters
    adapters = []
    if "meetup" in sources:
        from community_collector.adapters.meetup_adapter import MeetupAdapter
        adapters.append(MeetupAdapter())
    if "luma" in sources:
        from community_collector.adapters.luma_adapter import LumaAdapter
        adapters.append(LumaAdapter())
    if "mobilize" in sources:
        from community_collector.adapters.mobilize_adapter import MobilizeAdapter
        adapters.append(MobilizeAdapter())
    if "ical" in sources:
        from community_collector.adapters.ical_adapter import ICalAdapter
        adapters.append(ICalAdapter())
    if "github" in sources:
        from community_collector.adapters.github_adapter import GitHubAdapter
        adapters.append(GitHubAdapter())

    all_raw: dict[str, list[dict]] = {a.source_name: [] for a in adapters}
    seen_urls: dict[str, set[str]] = {a.source_name: set() for a in adapters}

    total_terms = len(terms)
    for i, term in enumerate(terms):
        log.info("bulk_collect.term",
                 idx=i + 1, total=total_terms, term=repr(term),
                 collected={s: len(v) for s, v in seen_urls.items()})

        # Run all adapters concurrently for this term
        tasks = [run_adapter(a, config, term) for a in adapters]
        results = await asyncio.gather(*tasks)

        for adapter, batch in zip(adapters, results):
            name = adapter.source_name
            new = 0
            for r in batch:
                url = (r.get("url") or "").strip()
                if url and url not in seen_urls[name]:
                    seen_urls[name].add(url)
                    all_raw[name].append(r)
                    new += 1
            if new:
                log.info("bulk_collect.new_records",
                         source=name, term=repr(term), new=new, total=len(seen_urls[name]))

    print(f"\n=== Collection complete ===")
    for name, raw_list in all_raw.items():
        print(f"  {name}: {len(raw_list)} unique events")

    # Normalize all records
    normalized = []
    for name, raw_list in all_raw.items():
        for raw in raw_list:
            rec = normalize(raw, name)
            if rec:
                normalized.append(rec)
    print(f"  Normalized total: {len(normalized)}")

    # Save to DB
    saved = save_records(normalized, db_path)
    print(f"  Saved/upserted: {saved} records to {db_path}")

    # Dump raw JSON per source
    ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(db_path).parent / f"bulk_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, raw_list in all_raw.items():
        out_file = out_dir / f"raw_{name}.json"
        out_file.write_text(
            json.dumps(raw_list, indent=2, default=str), encoding="utf-8"
        )
    print(f"  Raw JSON: {out_dir}/")

    return {name: len(v) for name, v in all_raw.items()}


def main() -> None:
    p = argparse.ArgumentParser(description="Bulk-collect Berlin events (API-based, no browser)")
    p.add_argument("--max",     type=int,  default=500,
                   help="Max results per source per term (default: 500)")
    p.add_argument("--sources", default="meetup,luma,mobilize,ical,github",
                   help="Comma-separated sources (default: meetup,luma,mobilize,ical,github)")
    p.add_argument("--db",      default=str(DB_PATH))
    args = p.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    asyncio.run(collect(sources, args.max, args.db, DEFAULT_BERLIN_TOPICS))


if __name__ == "__main__":
    main()
