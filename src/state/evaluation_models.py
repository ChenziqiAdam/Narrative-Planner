from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

from .models import serialize_value


@dataclass
class TurnEvaluation:
    turn_id: str
    question_quality_score: float
    information_gain_score: float
    non_redundancy_score: float
    slot_targeting_score: float
    emotional_alignment_score: float
    planner_alignment_score: float
    coverage_gain: float = 0.0
    targeted_slots: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, object]:
        return serialize_value(self)
