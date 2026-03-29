from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class CandidateCommunity(BaseModel):
    id: str
    name: str
    description: str
    category: str  # "event" | "group" | "venue"
    url: str | None = None
    location: str | None = None
    recurrence: str | None = None
    language: str | None = None
    tags: list[str] = Field(default_factory=list)
    raw_source: dict[str, Any] = Field(default_factory=dict)
