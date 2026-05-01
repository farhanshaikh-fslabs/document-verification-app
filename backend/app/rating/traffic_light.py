"""Traffic-light document rating from extractions and validation outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.db.models import TrafficLight


@dataclass
class RatingOutcome:
    traffic_light: TrafficLight
    reasons: list[str]
    manual_review_required: bool


def compute_rating(
    extraction_confidences: list[float],
    attribute_passed: list[bool],
    citation_flagged: list[bool],
    threshold: float | None = None,
) -> RatingOutcome:
    settings = get_settings()
    x = threshold if threshold is not None else settings.confidence_threshold
    reasons: list[str] = []

    any_attr_fail = any(not p for p in attribute_passed)
    any_cite_flag = any(citation_flagged)
    low_conf = any(c < x for c in extraction_confidences)

    if any_attr_fail or any_cite_flag:
        reasons.append("Non-conformance or citation review required")
        if any_attr_fail:
            reasons.append("One or more attribute validations failed")
        if any_cite_flag:
            reasons.append("One or more citations flagged for immediate review")
        return RatingOutcome(TrafficLight.red, reasons, True)

    if low_conf:
        reasons.append(f"One or more extractions below confidence threshold ({x})")
        return RatingOutcome(TrafficLight.yellow, reasons, True)

    return RatingOutcome(TrafficLight.green, ["All checks passed within confidence threshold"], False)
