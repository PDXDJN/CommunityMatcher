"""
Collection orchestrator.

Drives the full pipeline:
  1. launch Playwright browser
  2. run enabled source adapters (sequentially per term, sources in parallel)
  3. normalize raw records
  4. save to JSON output files + SQLite DB
  5. return CollectionResult summary
"""
from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from community_collector.config import CollectorConfig, OUTPUT_DIR
from community_collector.models import CommunityEventRecord, CollectionResult
from community_collector.normalization import normalize
from community_collector.persistence import save_records, save_run_summary
from community_collector.utils.logging_utils import get_logger

log = get_logger("orchestrator")

# Registry of available adapters
_ADAPTER_REGISTRY: dict[str, type] = {}


def _load_adapters() -> None:
    from community_collector.adapters.meetup_adapter import MeetupAdapter
    from community_collector.adapters.eventbrite_adapter import EventbriteAdapter
    from community_collector.adapters.luma_adapter import LumaAdapter
    _ADAPTER_REGISTRY["meetup"]     = MeetupAdapter
    _ADAPTER_REGISTRY["eventbrite"] = EventbriteAdapter
    _ADAPTER_REGISTRY["luma"]       = LumaAdapter


async def _run_adapter(
    adapter_cls, browser, config: CollectorConfig, term: str
) -> tuple[str, list[dict]]:
    """Run one adapter for one search term. Returns (source_name, raw_records)."""
    adapter = adapter_cls()
    try:
        records = await adapter.collect(browser, config, term)
        return adapter.source_name, records
    except Exception as exc:
        log.warning("orchestrator.adapter_failed",
                    source=adapter.source_name, term=term, error=str(exc))
        return adapter.source_name, []


async def collect_async(config: CollectorConfig) -> CollectionResult:
    """
    Full async collection pipeline.

    For each search term, all enabled source adapters run concurrently.
    Failures in one adapter don't affect others.
    """
    _load_adapters()

    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.utcnow().isoformat()
    t0 = datetime.utcnow()

    # Output folder with timestamp
    ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    run_dir = Path(config.db_path).parent / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    enabled_adapters = [
        _ADAPTER_REGISTRY[s]
        for s in config.sources_to_run
        if s in _ADAPTER_REGISTRY
    ]
    unknown = [s for s in config.sources_to_run if s not in _ADAPTER_REGISTRY]
    if unknown:
        log.warning("orchestrator.unknown_sources", unknown=unknown)

    raw_per_source: dict[str, list[dict]] = {cls().source_name: [] for cls in enabled_adapters}
    errors: dict[str, str] = {}

    log.info("orchestrator.start", run_id=run_id, sources=[c().source_name for c in enabled_adapters],
             terms=config.search_terms, location=config.location)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.headless)

        for term in config.search_terms:
            log.info("orchestrator.term", term=term)
            tasks = [
                _run_adapter(cls, browser, config, term)
                for cls in enabled_adapters
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    log.warning("orchestrator.task_exception", error=str(result))
                    continue
                source_name, records = result
                raw_per_source[source_name].extend(records)

        await browser.close()

    # Save raw outputs per source
    for source, raw_list in raw_per_source.items():
        raw_path = run_dir / f"raw_{source}.json"
        raw_path.write_text(json.dumps(raw_list, indent=2, default=str), encoding="utf-8")
        log.info("orchestrator.raw_saved", source=source, count=len(raw_list), path=str(raw_path))

    # Normalize all records
    normalized: list[CommunityEventRecord] = []
    for source, raw_list in raw_per_source.items():
        for raw in raw_list:
            record = normalize(raw, source)
            if record:
                normalized.append(record)

    # Add curated Berlin communities (static, no browser needed)
    try:
        from community_collector.adapters.berlin_communities_adapter import records_from_curated
        curated = records_from_curated({
            "search_terms": config.search_terms,
            "category_filters": [],
        })
        normalized.extend(curated)
        log.info("orchestrator.curated_added", count=len(curated))
    except Exception as exc:
        log.warning("orchestrator.curated_failed", error=str(exc))

    log.info("orchestrator.normalized_total", count=len(normalized))

    # Deduplicate by canonical_url
    seen_urls: set[str] = set()
    deduped: list[CommunityEventRecord] = []
    for rec in normalized:
        key = rec.canonical_url or rec.source_url
        if key not in seen_urls:
            seen_urls.add(key)
            deduped.append(rec)

    log.info("orchestrator.after_dedup", count=len(deduped))

    # Save normalized JSON
    norm_path = run_dir / "normalized_records.json"
    norm_path.write_text(
        json.dumps([r.model_dump() for r in deduped], indent=2, default=str),
        encoding="utf-8",
    )

    # Persist to SQLite
    saved_count = await asyncio.to_thread(save_records, deduped, config.db_path)
    log.info("orchestrator.db_saved", count=saved_count, db=config.db_path)

    finished_at = datetime.utcnow().isoformat()
    duration = (datetime.utcnow() - t0).total_seconds()

    result = CollectionResult(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=round(duration, 2),
        location=config.location,
        search_terms=config.search_terms,
        sources_attempted=[c().source_name for c in enabled_adapters],
        records_per_source={s: len(v) for s, v in raw_per_source.items()},
        normalized_total=len(deduped),
        errors=errors,
        output_dir=str(run_dir),
        db_path=config.db_path,
    )

    # Save run summary JSON + DB
    summary_path = run_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps(result.model_dump(), indent=2),
        encoding="utf-8",
    )
    await asyncio.to_thread(save_run_summary, result, config.db_path)

    log.info("orchestrator.complete", run_id=run_id, duration_s=duration,
             normalized=len(deduped), output_dir=str(run_dir))
    return result


def run_collection(config: CollectorConfig | None = None) -> CollectionResult:
    """Synchronous entry point — wraps the async pipeline."""
    cfg = config or CollectorConfig()
    return asyncio.run(collect_async(cfg))
