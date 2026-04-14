from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional


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
class OpenLoop:
    loop_id: str
    source_event_id: Optional[str]
    loop_type: Literal["missing_slot", "unexpanded_clue", "conflict", "person_gap"]
    description: str
    priority: float

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class ContradictionNote:
    note_id: str
    event_ids: List[str]
    description: str
    severity: Literal["low", "medium", "high"]

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
class MemoryCapsule:
    session_summary: str = ""
    current_storyline: str = ""
    active_event_ids: List[str] = field(default_factory=list)
    active_people_ids: List[str] = field(default_factory=list)
    open_loops: List[OpenLoop] = field(default_factory=list)
    contradictions: List[ContradictionNote] = field(default_factory=list)
    emotional_state: Optional[EmotionalState] = None
    recent_topics: List[str] = field(default_factory=list)
    do_not_repeat: List[str] = field(default_factory=list)
    open_loop_history_total: int = 0
    resolved_open_loop_count: int = 0
    contradiction_history_total: int = 0
    resolved_contradiction_count: int = 0

    @classmethod
    def empty(cls) -> "MemoryCapsule":
        return cls(
            session_summary="Interview session initialized.",
            current_storyline="Opening the conversation.",
            emotional_state=EmotionalState(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class CanonicalEvent:
    event_id: str
    title: str
    summary: str
    time: Optional[str] = None
    location: Optional[str] = None
    people_ids: List[str] = field(default_factory=list)
    people_names: List[str] = field(default_factory=list)
    event: Optional[str] = None
    feeling: Optional[str] = None
    reflection: Optional[str] = None
    cause: Optional[str] = None
    result: Optional[str] = None
    unexpanded_clues: List[str] = field(default_factory=list)
    theme_id: Optional[str] = None
    source_turn_ids: List[str] = field(default_factory=list)
    completeness_score: float = 0.0
    confidence: float = 0.0
    merge_status: Literal["new", "updated", "merged", "uncertain"] = "new"

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class PersonProfile:
    person_id: str
    display_name: str
    aliases: List[str] = field(default_factory=list)
    relation_to_elder: Optional[str] = None
    summary: Optional[str] = None
    related_event_ids: List[str] = field(default_factory=list)
    stable_attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class ThemeState:
    theme_id: str
    title: str
    status: Literal["pending", "mentioned", "exhausted"]
    priority: int
    expected_slots: List[str] = field(default_factory=list)
    filled_slots: Dict[str, bool] = field(default_factory=dict)
    extracted_event_ids: List[str] = field(default_factory=list)
    open_question_count: int = 0
    completion_ratio: float = 0.0
    exploration_depth: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class ThemeSummary:
    """主题摘要信息，用于 PlannerContext"""
    theme_id: str
    title: str
    description: str
    status: str
    completion_ratio: float
    priority: int
    extracted_event_count: int
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class GraphSummary:
    overall_coverage: float
    theme_coverage: Dict[str, float]
    slot_coverage: Dict[str, float]
    people_coverage: float
    current_focus_theme_id: Optional[str]
    active_event_ids: List[str] = field(default_factory=list)

    # 主题详细列表（新增）
    all_themes: List[ThemeSummary] = field(default_factory=list)
    pending_themes: List[ThemeSummary] = field(default_factory=list)      # 空白主题
    mentioned_themes: List[ThemeSummary] = field(default_factory=list)   # 已提及主题
    exhausted_themes: List[ThemeSummary] = field(default_factory=list)   # 已穷尽主题

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class QuestionPlan:
    plan_id: str
    primary_action: ActionType
    tactical_goal: str
    target_theme_id: Optional[str]
    target_event_id: Optional[str]
    target_person_id: Optional[str]
    tactical_goal_type: str = "EXTRACT_DETAILS"
    target_slots: List[str] = field(default_factory=list)
    tone: str = "EMPATHIC_SUPPORTIVE"
    secondary_tone: Optional[str] = None
    tone_constraints: List[str] = field(default_factory=list)
    strategy: str = "OBJECT_TO_EMOTION"
    strategy_parameters: Dict[str, Any] = field(default_factory=dict)
    strategy_priority: int = 1
    reasoning_trace: List[str] = field(default_factory=list)
    instruction_set: Dict[str, Any] = field(default_factory=dict)
    reference_anchor: Optional[str] = None
    raw_planner_response: Dict[str, Any] = field(default_factory=dict)

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
class MemoryDelta:
    summary_updates: List[str] = field(default_factory=list)
    new_open_loops: List[OpenLoop] = field(default_factory=list)
    contradiction_notes: List[ContradictionNote] = field(default_factory=list)
    emotional_state_update: Optional[EmotionalState] = None

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class GraphDelta:
    event_candidates: List[CanonicalEvent] = field(default_factory=list)
    people_candidates: List[PersonProfile] = field(default_factory=list)
    theme_hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class ExtractionResult:
    turn_id: str
    metadata: ExtractionMetadata
    memory_delta: MemoryDelta
    graph_delta: GraphDelta
    debug_trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class PlannerContext:
    session_id: str
    turn_index: int
    elder_profile: ElderProfile
    recent_transcript: List["TurnRecord"]
    graph_summary: GraphSummary
    memory_capsule: MemoryCapsule

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class TurnRecord:
    turn_id: str
    turn_index: int
    timestamp: datetime
    interviewer_question: str
    interviewee_answer: str
    planner_plan: Optional[QuestionPlan] = None
    extraction_result: Optional[ExtractionResult] = None
    turn_evaluation: Optional["TurnEvaluation"] = None
    debug_trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


@dataclass
class SessionMetrics:
    overall_theme_coverage: float = 0.0
    overall_slot_coverage: Dict[str, float] = field(default_factory=dict)
    people_coverage: float = 0.0
    open_loop_closure_rate: float = 0.0
    contradiction_resolution_rate: float = 0.0
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
class SessionState:
    session_id: str
    mode: Literal["baseline", "planner"]
    created_at: datetime
    updated_at: datetime
    elder_profile: ElderProfile
    transcript: List[TurnRecord] = field(default_factory=list)
    canonical_events: Dict[str, CanonicalEvent] = field(default_factory=dict)
    people_registry: Dict[str, PersonProfile] = field(default_factory=dict)
    theme_state: Dict[str, ThemeState] = field(default_factory=dict)
    memory_capsule: Optional[MemoryCapsule] = None
    evaluation_trace: List["TurnEvaluation"] = field(default_factory=list)
    session_metrics: Optional[SessionMetrics] = None
    current_focus_theme_id: Optional[str] = None
    pending_jobs: List[BackgroundJobStatus] = field(default_factory=list)
    pending_plan: Optional[QuestionPlan] = None
    pending_question: Optional[str] = None
    pending_action: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

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
