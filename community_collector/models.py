from __future__ import annotations
from datetime import datetime, UTC
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class CommunityEventRecord(BaseModel):
    """Normalized representation of a scraped community or event listing."""

    # --- Source provenance ---
    source: str                               # adapter name, e.g. "meetup"
    source_record_id: Optional[str] = None   # source-native ID if available
    source_url: str                           # URL as seen on source site
    canonical_url: Optional[str] = None      # de-tracked, normalized URL

    # --- Core identity ---
    title: str
    description: Optional[str] = None
    organizer_name: Optional[str] = None
    community_name: Optional[str] = None

    # --- Temporal ---
    event_datetime_start: Optional[str] = None  # ISO string or raw text
    event_datetime_end: Optional[str] = None
    timezone: Optional[str] = None
    activity: Optional[str] = None           # "weekly" | "monthly" | "one-off" | "recurring"

    # --- Location ---
    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    is_online: Optional[bool] = None

    # --- Cost ---
    cost_text: Optional[str] = None
    cost_factor: Optional[float] = None      # 0 = free, >0 = paid, None = unknown
    currency: Optional[str] = None

    # --- Inferred metadata ---
    tags: list[str] = Field(default_factory=list)
    topic_signals: list[str] = Field(default_factory=list)
    audience_signals: list[str] = Field(default_factory=list)
    format_signals: list[str] = Field(default_factory=list)
    vibe_signals: list[str] = Field(default_factory=list)

    # --- Translations ---
    title_en: Optional[str] = None          # English title (original or translated)
    description_en: Optional[str] = None    # English description
    title_de: Optional[str] = None          # German title (original or translated)
    description_de: Optional[str] = None    # German description
    detected_language: Optional[str] = None # "en" | "de" — auto-detected source language

    # --- Classification ---
    raw_category: Optional[str] = None
    language: Optional[str] = None

    # --- Collector bookkeeping ---
    extraction_timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    search_term: Optional[str] = None
    raw_payload: dict = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v

    @field_validator("source_url")
    @classmethod
    def url_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("source_url must not be empty")
        return v


class CollectionResult(BaseModel):
    """Summary returned after a full collection run."""

    run_id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    location: str
    search_terms: list[str]
    sources_attempted: list[str]
    records_per_source: dict[str, int]
    normalized_total: int
    errors: dict[str, str]          # source_name → error message
    output_dir: str
    db_path: str
