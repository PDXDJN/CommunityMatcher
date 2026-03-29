from __future__ import annotations
import os
from pathlib import Path
from pydantic import BaseModel, Field
from community_collector.keywords import DEFAULT_BERLIN_TOPICS

# Resolved paths
_PACKAGE_DIR = Path(__file__).parent
OUTPUT_DIR = _PACKAGE_DIR / "output"
DB_PATH = OUTPUT_DIR / "communitymatcher.db"

# User-Agent matching a modern browser to avoid trivial bot blocks
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class CollectorConfig(BaseModel):
    """Runtime configuration for a collection run."""

    location: str = "Berlin"
    country: str = "Germany"
    search_terms: list[str] = Field(
        default_factory=lambda: DEFAULT_BERLIN_TOPICS
    )
    category_filters: list[str] = Field(
        default_factory=lambda: ["tech", "maker", "startup", "community"]
    )
    max_results_per_source: int = 20
    headless: bool = True
    sources_to_run: list[str] = Field(
        default_factory=lambda: ["meetup", "eventbrite", "luma"]
    )
    # Page interaction timeouts in milliseconds
    navigation_timeout_ms: int = 20_000
    selector_timeout_ms: int = 8_000
    # Modest inter-action delay (ms) — be a respectful prototype, not a DDoS
    page_delay_ms: int = 1_200
    # Database path (can be overridden for tests)
    db_path: str = str(DB_PATH)


def config_from_env() -> CollectorConfig:
    """Build a CollectorConfig from environment variables (optional overrides)."""
    return CollectorConfig(
        location=os.getenv("COLLECTOR_LOCATION", "Berlin"),
        headless=os.getenv("COLLECTOR_HEADLESS", "true").lower() != "false",
        max_results_per_source=int(os.getenv("COLLECTOR_MAX_RESULTS", "20")),
        sources_to_run=os.getenv(
            "COLLECTOR_SOURCES", "meetup,eventbrite,luma"
        ).split(","),
    )
