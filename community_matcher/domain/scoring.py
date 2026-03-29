from __future__ import annotations
from pydantic import BaseModel, model_validator
from community_matcher.config.settings import settings


class CandidateScores(BaseModel):
    interest_alignment: float = 0.0
    vibe_alignment: float = 0.0
    newcomer_friendliness: float = 0.0
    logistics_fit: float = 0.0
    language_fit: float = 0.0
    values_fit: float = 0.0
    recurrence_strength: float = 0.0
    risk_sanity: float = 0.0
    total: float = 0.0

    @model_validator(mode="after")
    def compute_total(self) -> "CandidateScores":
        s = settings
        self.total = (
            s.weight_interest_alignment * self.interest_alignment
            + s.weight_vibe_alignment * self.vibe_alignment
            + s.weight_newcomer_friendliness * self.newcomer_friendliness
            + s.weight_logistics_fit * self.logistics_fit
            + s.weight_language_fit * self.language_fit
            + s.weight_values_fit * self.values_fit
            + s.weight_recurrence_strength * self.recurrence_strength
            + s.weight_risk_sanity * self.risk_sanity
        )
        return self
