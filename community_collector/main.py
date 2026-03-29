"""
CLI entry point for the community_collector.

Usage:
  python -m community_collector.main --location Berlin --terms "AI,python,startup" \\
         --sources meetup,eventbrite,luma --max-results 20

  python -m community_collector.main --help
"""
from __future__ import annotations
import argparse
import sys
from community_collector.config import CollectorConfig
from community_collector.orchestrator import run_collection
from community_collector.utils.logging_utils import configure_logging


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="community_collector",
        description="Collect public community and event data for CommunityMatcher.",
    )
    p.add_argument("--location",    default="Berlin",
                   help="City to search in (default: Berlin)")
    p.add_argument("--country",     default="Germany",
                   help="Country (default: Germany)")
    p.add_argument("--terms",       default="AI,python,startup,hackerspace",
                   help="Comma-separated search terms")
    p.add_argument("--sources",     default="meetup,eventbrite,luma",
                   help="Comma-separated source names")
    p.add_argument("--max-results", type=int, default=20,
                   help="Max results per source per term (default: 20)")
    p.add_argument("--no-headless", action="store_true",
                   help="Run browser in visible mode (useful for debugging)")
    p.add_argument("--log-level",   default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="Log verbosity (default: INFO)")
    p.add_argument("--db-path",     default=None,
                   help="Override SQLite DB path")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    configure_logging(args.log_level)

    config = CollectorConfig(
        location=args.location,
        country=args.country,
        search_terms=[t.strip() for t in args.terms.split(",") if t.strip()],
        sources_to_run=[s.strip() for s in args.sources.split(",") if s.strip()],
        max_results_per_source=args.max_results,
        headless=not args.no_headless,
    )
    if args.db_path:
        config = config.model_copy(update={"db_path": args.db_path})

    print(f"\n=== CommunityMatcher Collector ===")
    print(f"  Location : {config.location}")
    print(f"  Terms    : {', '.join(config.search_terms)}")
    print(f"  Sources  : {', '.join(config.sources_to_run)}")
    print(f"  DB       : {config.db_path}")
    print(f"  Headless : {config.headless}\n")

    try:
        result = run_collection(config)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 1
    except Exception as exc:
        print(f"\n[ERROR] Collection failed: {exc}", file=sys.stderr)
        return 1

    print("\n=== Collection Complete ===")
    print(f"  Duration       : {result.duration_seconds:.1f}s")
    print(f"  Normalized     : {result.normalized_total} records")
    for src, count in result.records_per_source.items():
        print(f"  {src:<14}: {count} raw records")
    if result.errors:
        print(f"  Errors         : {result.errors}")
    print(f"  Output folder  : {result.output_dir}")
    print(f"  Database       : {result.db_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
