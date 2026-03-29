from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from community_matcher.domain.candidates import CandidateCommunity


class SearchBrief(BaseModel):
    session_id: str
    profile_summary: str = ""
    archetypes: dict[str, float] = Field(default_factory=dict)
    location: str = ""
    query_intents: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)


class RecommendationBundle(BaseModel):
    best_overall: list[CandidateCommunity] = Field(default_factory=list)
    best_first_step: list[CandidateCommunity] = Field(default_factory=list)
    best_recurring: list[CandidateCommunity] = Field(default_factory=list)
    stretch: list[CandidateCommunity] = Field(default_factory=list)
    explanations: dict[str, str] = Field(default_factory=dict)  # id -> reason
