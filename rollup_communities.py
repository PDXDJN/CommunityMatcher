"""
Community rollup: collapse event-level scrape_records into organizer-level community rows.

The default persistence layer creates one community row per event (using the event
title as the community name). This script fixes that by:

  1. Grouping scrape_records by organizer_name (recurring organizer = one community).
  2. Upserting a single community row per unique organizer with:
       - name        = organizer_name
       - url         = organizer's Luma/Meetup calendar URL (from raw_payload)
       - description = longest non-empty description across all their events
       - activity    = "recurring" if they have 2+ events, else original
       - cost_factor = median cost_factor across their events
  3. Re-linking all their scrape_records to the new community row (c_idx).
  4. Writing aggregated kw_affinity rows (union of tags, max aff_value).
  5. Events with no organizer fall back to grouping by community_name, then title.

Events from ALL sources are rolled up, but Luma and Meetup benefit most.

Usage:
    python rollup_communities.py [--db DB_PATH] [--source luma] [--dry-run]
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

from community_collector.config import DB_PATH
from community_collector.utils.logging_utils import configure_logging, get_logger

log = get_logger("rollup")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _organizer_url_from_payload(raw_payload_json: str | None) -> str | None:
    """Extract organizer URL stored in raw_payload by the Luma/Meetup adapter."""
    if not raw_payload_json:
        return None
    try:
        payload = json.loads(raw_payload_json)
        return (
            payload.get("organizer_url")          # Luma calendar URL
            or payload.get("group_url")            # Meetup group URL
        )
    except (json.JSONDecodeError, AttributeError):
        return None


def _best_description(descriptions: list[str | None]) -> str | None:
    """Pick the longest non-empty description."""
    candidates = [d.strip() for d in descriptions if d and d.strip()]
    if not candidates:
        return None
    return max(candidates, key=len)


def _median_cost(cost_factors: list[float | None]) -> float | None:
    valid = [c for c in cost_factors if c is not None]
    if not valid:
        return None
    return round(statistics.median(valid), 4)


def _grouping_key(row: sqlite3.Row) -> str:
    """
    Return the best available grouping key for a scrape_record row.
    Priority: organizer_name > community_name > title.
    """
    return (
        (row["organizer_name"] or "").strip()
        or (row["community_name"] or "").strip()
        or (row["title"] or "").strip()
    )


# ---------------------------------------------------------------------------
# Core rollup
# ---------------------------------------------------------------------------

def rollup(db_path: str, source_filter: str | None, dry_run: bool) -> dict:
    conn = _connect(db_path)
    cur = conn.cursor()

    # Fetch all scrape_records (optionally filtered by source)
    if source_filter:
        cur.execute(
            "SELECT * FROM scrape_record WHERE source = ?",
            (source_filter,)
        )
    else:
        cur.execute("SELECT * FROM scrape_record")

    rows = cur.fetchall()
    log.info("rollup.loaded_records", count=len(rows), source=source_filter or "all")

    # ── Group by organizer key ────────────────────────────────────────────────
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        key = _grouping_key(row)
        if key:
            groups[key].append(row)

    log.info("rollup.groups_found", count=len(groups))

    stats = {
        "groups_processed": 0,
        "communities_created": 0,
        "communities_updated": 0,
        "records_relinked": 0,
    }

    # ── Upsert one community per group ───────────────────────────────────────
    for org_name, event_rows in sorted(groups.items()):
        stats["groups_processed"] += 1

        descriptions   = [r["description"] for r in event_rows]
        cost_factors   = [r["cost_factor"] for r in event_rows]
        activities     = [r["activity"] for r in event_rows]

        best_desc  = _best_description(descriptions)
        cost_med   = _median_cost(cost_factors)
        activity   = "recurring" if len(event_rows) >= 2 else (activities[0] if activities else None)

        # Organizer URL: try raw_payload from each event
        org_url: str | None = None
        for r in event_rows:
            org_url = _organizer_url_from_payload(r["raw_payload"])
            if org_url:
                break
        # Fallback: use the event's canonical_url if only one event
        if not org_url and len(event_rows) == 1:
            org_url = event_rows[0]["canonical_url"] or event_rows[0]["source_url"]

        # Aggregate tags for this community group
        all_tags: set[str] = set()
        tag_sources: dict[str, str] = {}  # tag → "topic_signal" | "tag"
        for r in event_rows:
            try:
                topics = json.loads(r["topic_signals"] or "[]")
                for t in topics:
                    all_tags.add(t)
                    tag_sources[t] = "topic_signal"
                for t in json.loads(r["tags"] or "[]"):
                    all_tags.add(t)
                    if t not in tag_sources:
                        tag_sources[t] = "tag"
            except (json.JSONDecodeError, TypeError):
                pass

        if dry_run:
            print(
                f"[DRY RUN] {org_name!r:50s} → {len(event_rows):3d} events | "
                f"tags: {len(all_tags)} | url: {org_url}"
            )
            continue

        # ── Upsert community row ───────────────────────────────────────────
        existing = cur.execute(
            "SELECT idx FROM community WHERE name = ?", (org_name,)
        ).fetchone()

        if existing:
            c_idx = existing["idx"]
            cur.execute(
                """
                UPDATE community
                SET url = COALESCE(?, url),
                    description = COALESCE(?, description),
                    activity = COALESCE(?, activity),
                    cost_factor = COALESCE(?, cost_factor)
                WHERE idx = ?
                """,
                (org_url, best_desc, activity, cost_med, c_idx),
            )
            stats["communities_updated"] += 1
        else:
            cur.execute(
                "INSERT INTO community (name, url, description, activity, cost_factor) "
                "VALUES (?, ?, ?, ?, ?)",
                (org_name, org_url, best_desc, activity, cost_med),
            )
            c_idx = cur.lastrowid
            stats["communities_created"] += 1

        # ── Upsert social link ─────────────────────────────────────────────
        if org_url:
            cur.execute(
                "INSERT OR IGNORE INTO social (c_idx, url, annotation) VALUES (?, ?, ?)",
                (c_idx, org_url, "organizer_calendar"),
            )

        # ── Keyword affinities ────────────────────────────────────────────
        for tag, source_type in tag_sources.items():
            aff = 0.75 if source_type == "topic_signal" else 0.6
            cur.execute(
                "INSERT OR IGNORE INTO keyword (short) VALUES (?)",
                (tag,),
            )
            k_idx = cur.execute(
                "SELECT idx FROM keyword WHERE short = ?", (tag,)
            ).fetchone()["idx"]
            cur.execute(
                """
                INSERT INTO kw_affinity (c_idx, k_idx, aff_value, annotation)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(c_idx, k_idx) DO UPDATE SET
                    aff_value  = MAX(excluded.aff_value, kw_affinity.aff_value),
                    annotation = excluded.annotation
                """,
                (c_idx, k_idx, aff, f"rollup_{source_type}"),
            )

        # ── Re-link scrape_records to the rolled-up community ────────────
        record_ids = [r["id"] for r in event_rows]
        cur.executemany(
            "UPDATE scrape_record SET c_idx = ? WHERE id = ?",
            [(c_idx, rid) for rid in record_ids],
        )
        stats["records_relinked"] += len(record_ids)

    if not dry_run:
        conn.commit()

    conn.close()
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    configure_logging("INFO")
    p = argparse.ArgumentParser(description="Roll up events into organizer-level communities")
    p.add_argument("--db",     default=str(DB_PATH), help="SQLite DB path")
    p.add_argument("--source", default=None,
                   help="Only process records from this source (e.g. 'luma')")
    p.add_argument("--dry-run", action="store_true",
                   help="Print groupings without writing to DB")
    args = p.parse_args()

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Rolling up communities in {args.db}")
    if args.source:
        print(f"  Source filter: {args.source}")

    stats = rollup(args.db, args.source, args.dry_run)

    if not args.dry_run:
        print(f"\n=== Rollup Complete ===")
        print(f"  Groups processed    : {stats['groups_processed']}")
        print(f"  Communities created : {stats['communities_created']}")
        print(f"  Communities updated : {stats['communities_updated']}")
        print(f"  Records re-linked   : {stats['records_relinked']}")


if __name__ == "__main__":
    main()
