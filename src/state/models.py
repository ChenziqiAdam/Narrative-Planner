from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from src.state.narrative_models import GraphExtraction, NarrativeFragment


ActionType = Literal[
    "DEEP_DIVE",
    "BREADTH_SWITCH",
    "CLARIFY",
    "SUMMARIZE",
    "PAUSE_SESSION",
    "CLOSE_INTERVIEW",
]


def serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {
            item.name: serialize_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    return value


@dataclass
class ElderProfile:
    name: Optional[str] = None
    birth_year: Optional[int] = None
    age: Optional[int] = None
    hometown: Optional[str] = None
    background_summary: Optional[str] = None
    stable_facts: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class EmotionalState:
    emotional_energy: float = 0.5
    cognitive_energy: float = 0.5
    valence: float = 0.0
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class ThemeState:
    theme_id: str
    title: str
    status: Literal["pending", "mentioned", "exhausted"]
    priority: int
    narrative_richness: float = 0.0
    entity_count: int = 0
    exploration_depth: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class ExtractionMetadata:
    extractor_version: str
    confidence: float
    source_spans: List[str] = field(default_factory=list)
    is_incremental_update: bool = False
    matched_event_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class GraphDelta:
    fragment_candidates: List[Any] = field(default_factory=list)
    graph_extraction: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class ExtractionResult:
    turn_id: str
    metadata: ExtractionMetadata
    graph_delta: GraphDelta
    debug_trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class TurnRecord:
    turn_id: str
    turn_index: int
    timestamp: datetime
    interviewer_question: str
    interviewee_answer: str
    extraction_result: Optional[ExtractionResult] = None
    turn_evaluation: Optional["TurnEvaluation"] = None
    debug_trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class SessionMetrics:
    overall_theme_coverage: float = 0.0
    average_turn_quality: float = 0.0
    average_information_gain: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class BackgroundJobStatus:
    job_id: str
    job_type: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class DynamicProfileField:
    value: Any = None
    confidence: float = 0.0
    evidence_turn_ids: List[str] = field(default_factory=list)
    evidence_fragment_ids: List[str] = field(default_factory=list)
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class DynamicElderProfile:
    schema_version: str = "dynamic_elder_profile_v1"
    core_identity_and_personality: Dict[str, DynamicProfileField] = field(default_factory=dict)
    current_life_status: Dict[str, DynamicProfileField] = field(default_factory=dict)
    family_situation: Dict[str, DynamicProfileField] = field(default_factory=dict)
    life_views_and_attitudes: Dict[str, DynamicProfileField] = field(default_factory=dict)
    planner_guidance: List[str] = field(default_factory=list)
    profile_quality: Dict[str, float] = field(default_factory=dict)
    update_count: int = 0
    last_updated_turn_id: Optional[str] = None
    last_update_reason: Optional[str] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class SessionState:
    session_id: str
    mode: Literal["graph_rag"] = "graph_rag"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    elder_profile: ElderProfile = field(default_factory=ElderProfile)
    transcript: List[TurnRecord] = field(default_factory=list)
    theme_state: Dict[str, ThemeState] = field(default_factory=dict)
    dynamic_profile: Optional[DynamicElderProfile] = None
    evaluation_trace: List["TurnEvaluation"] = field(default_factory=list)
    session_metrics: Optional[SessionMetrics] = None
    current_focus_theme_id: Optional[str] = None
    pending_jobs: List[BackgroundJobStatus] = field(default_factory=list)
    pending_question: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    narrative_fragments: Dict[str, Any] = field(default_factory=dict)

    @property
    def turn_count(self) -> int:
        return len(self.transcript)

    def recent_transcript(self, limit: int = 3) -> List[TurnRecord]:
        if limit <= 0:
            return []
        return self.transcript[-limit:]

    def touch(self) -> None:
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)
