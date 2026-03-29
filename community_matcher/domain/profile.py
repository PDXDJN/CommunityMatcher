from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field


class FieldConfidence(str, Enum):
    EXPLICIT = "explicit"
    INFERRED_HIGH = "inferred_high"
    INFERRED_LOW = "inferred_low"
    UNKNOWN = "unknown"


class BudgetSensitivity(str, Enum):
    FREE_ONLY = "free_only"
    LOW = "low"
    MEDIUM = "medium"
    ANY = "any"


class LogisticsPrefs(BaseModel):
    districts: list[str] = Field(default_factory=list)
    max_travel_minutes: int | None = None
    available_days: list[str] = Field(default_factory=list)
    available_times: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    goals: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    social_mode: str | None = None  # workshops/talks/project_nights/drinks/games
    environment: str | None = None  # newcomer_friendly/deep_community
    language_pref: list[str] = Field(default_factory=list)
    logistics: LogisticsPrefs = Field(default_factory=LogisticsPrefs)
    budget: BudgetSensitivity = BudgetSensitivity.ANY
    values: list[str] = Field(default_factory=list)
    dealbreakers: list[str] = Field(default_factory=list)
    archetype_weights: dict[str, float] = Field(default_factory=dict)
    field_confidence: dict[str, FieldConfidence] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return (
            not self.goals
            and not self.interests
            and self.social_mode is None
            and self.environment is None
        )
