from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .models import serialize_value


@dataclass
class TurnEvaluation:
    turn_id: str
    question_quality_score: float
    information_gain_score: float
    non_redundancy_score: float
    emotional_alignment_score: float
    coverage_gain: float = 0.0
    notes: List[str] = field(default_factory=list)
    llm_judge_status: str = "not_started"
    llm_judge_score: Optional[float] = None
    llm_judge_reason: str = ""
    llm_judge_dimensions: Dict[str, float] = field(default_factory=dict)
    llm_judge_suggestions: List[str] = field(default_factory=list)
    llm_judge_model: Optional[str] = None
    llm_judge_error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, object]:
        return serialize_value(self)
