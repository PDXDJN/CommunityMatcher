from __future__ import annotations
import uuid
from enum import Enum
from pydantic import BaseModel, Field
from community_matcher.domain.profile import UserProfile
from community_matcher.domain.candidates import CandidateCommunity
from community_matcher.domain.briefs import SearchBrief, RecommendationBundle


class OrchestratorPhase(str, Enum):
    INTAKE = "intake"
    QUESTIONING = "questioning"
    SEARCHING = "searching"
    AGGREGATING = "aggregating"
    RECOMMENDING = "recommending"
    REFINING = "refining"


class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    phase: OrchestratorPhase = OrchestratorPhase.INTAKE
    profile: UserProfile = Field(default_factory=UserProfile)
    conversation_history: list[dict] = Field(default_factory=list)
    candidates: list[CandidateCommunity] = Field(default_factory=list)
    search_brief: SearchBrief | None = None
    recommendation_bundle: RecommendationBundle | None = None
    # Raw DB rows from the last search — used by the refinement loop to
    # re-rank without re-querying the database.
    last_ranked_rows: list[dict] = Field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        self.conversation_history.append({"role": role, "content": content})

    def advance_phase(self, new_phase: OrchestratorPhase) -> None:
        self.phase = new_phase
