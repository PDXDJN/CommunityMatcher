from __future__ import annotations
from dataclasses import dataclass, field
from community_matcher.domain.profile import UserProfile, FieldConfidence

# Confidence → fractional credit toward the sufficiency score.
# None means the field was set directly (e.g. in tests or seed data) without
# going through the extraction pipeline — treat as INFERRED_HIGH benefit-of-doubt.
_CONFIDENCE_CREDIT: dict[FieldConfidence | None, float] = {
    FieldConfidence.EXPLICIT:       1.0,
    FieldConfidence.INFERRED_HIGH:  0.75,
    FieldConfidence.INFERRED_LOW:   0.5,
    FieldConfidence.UNKNOWN:        0.0,
    None:                           0.7,  # field present, no metadata → benefit of doubt
}

# Required categories and their weight in the overall score (must sum to 1.0)
_REQUIRED_FIELDS = {
    "primary_goal":    0.30,
    "interest_cluster": 0.30,
    "social_mode":     0.25,
    "logistics":       0.15,
}

# Threshold above which we consider the profile sufficient
_SUFFICIENCY_THRESHOLD = 0.65


@dataclass
class SufficiencyResult:
    is_sufficient: bool
    score: float
    missing_categories: list[str] = field(default_factory=list)
    reason: str = ""


def _field_credit(profile: UserProfile, category: str) -> float:
    """Return 0..1 credit for a required category, weighted by confidence."""
    if category == "primary_goal":
        if not profile.goals:
            return 0.0
        conf = profile.field_confidence.get("goals")
        return _CONFIDENCE_CREDIT[conf]
    elif category == "interest_cluster":
        if not profile.interests:
            return 0.0
        conf = profile.field_confidence.get("interests")
        return _CONFIDENCE_CREDIT[conf]
    elif category == "social_mode":
        if not profile.social_mode:
            return 0.0
        conf = profile.field_confidence.get("social_mode")
        return _CONFIDENCE_CREDIT[conf]
    elif category == "logistics":
        has_district = bool(profile.logistics.districts)
        has_travel = profile.logistics.max_travel_minutes is not None
        if not has_district and not has_travel:
            return 0.0
        conf = profile.field_confidence.get("logistics")
        return _CONFIDENCE_CREDIT[conf]
    return 0.0


def check_sufficiency(profile: UserProfile) -> SufficiencyResult:
    """
    Confidence-weighted sufficiency check (Sprint 2).

    Each required category contributes to the score proportional to:
      - its weight in _REQUIRED_FIELDS
      - the confidence of the extracted value (EXPLICIT=1.0, INFERRED_HIGH=0.75,
        INFERRED_LOW=0.5)

    The profile is considered sufficient when score >= _SUFFICIENCY_THRESHOLD.
    """
    score = 0.0
    missing: list[str] = []

    for category, weight in _REQUIRED_FIELDS.items():
        credit = _field_credit(profile, category)
        score += weight * credit
        if credit < 0.5:
            missing.append(category)

    score = round(score, 3)
    is_sufficient = score >= _SUFFICIENCY_THRESHOLD

    return SufficiencyResult(
        is_sufficient=is_sufficient,
        score=score,
        missing_categories=missing,
        reason=(
            "Profile is sufficient for search."
            if is_sufficient
            else f"Missing or low-confidence: {', '.join(missing)} (score={score:.2f})"
        ),
    )
