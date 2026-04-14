from datetime import datetime

from src.orchestration.planner_decision_policy import PlannerDecisionPolicy, PlannerDecisionWeights
from src.orchestration.session_orchestrator import SessionOrchestrator
from src.state import (
    CanonicalEvent,
    ElderProfile,
    EmotionalState,
    ExtractionMetadata,
    ExtractionResult,
    GraphDelta,
    MemoryCapsule,
    MemoryDelta,
    SessionState,
    ThemeState,
    TurnRecord,
)


def _build_state() -> SessionState:
    now = datetime.now()
    return SessionState(
        session_id="decision_policy_test",
        mode="planner",
        created_at=now,
        updated_at=now,
        elder_profile=ElderProfile(name="测试老人"),
        memory_capsule=MemoryCapsule(
            emotional_state=EmotionalState(
                emotional_energy=0.4,
                cognitive_energy=0.35,
                valence=-0.45,
                confidence=0.8,
                evidence=["回答简短", "情绪偏低"],
            ),
            recent_topics=["人生篇章"],
        ),
    )


def _append_turn_with_extraction(state: SessionState, info_gain_like: bool = True) -> None:
    turn = TurnRecord(
        turn_id=f"turn_{state.turn_count + 1}",
        turn_index=state.turn_count + 1,
        timestamp=datetime.now(),
        interviewer_question="Q",
        interviewee_answer="回答内容比较丰富" if info_gain_like else "嗯",
    )
    candidates = []
    if info_gain_like:
        candidates = [
            CanonicalEvent(
                event_id="evt_new_1",
                title="新事件",
                summary="提到新的工作经历",
                time="1968年",
                location="上海",
                people_names=["师傅"],
                event="进入工厂工作",
                confidence=0.78,
                completeness_score=0.65,
            )
        ]
    turn.extraction_result = ExtractionResult(
        turn_id=turn.turn_id,
        metadata=ExtractionMetadata(extractor_version="test", confidence=0.9),
        memory_delta=MemoryDelta(),
        graph_delta=GraphDelta(event_candidates=candidates),
    )
    state.transcript.append(turn)


def test_missing_slot_weight_vs_new_info_weight_changes_focus_preference():
    state = _build_state()
    _append_turn_with_extraction(state, info_gain_like=True)

    focus_event_payload = {
        "event_id": "evt_focus",
        "missing_slots": ["time", "location", "people", "cause", "result", "reflection"],
        "people_names": ["父亲"],
    }

    policy_gap = PlannerDecisionPolicy(
        PlannerDecisionWeights.from_config(
            {
                "missing_slot_weight": 1.7,
                "new_info_weight": 0.7,
            }
        )
    )
    result_gap = policy_gap.evaluate(
        state=state,
        post_overall_coverage=0.35,
        focus_event_payload=focus_event_payload,
        fallback_repeat_count=0,
    )

    policy_new = PlannerDecisionPolicy(
        PlannerDecisionWeights.from_config(
            {
                "missing_slot_weight": 0.7,
                "new_info_weight": 1.8,
            }
        )
    )
    result_new = policy_new.evaluate(
        state=state,
        post_overall_coverage=0.35,
        focus_event_payload=focus_event_payload,
        fallback_repeat_count=0,
    )

    assert result_gap["preferred_focus"] == "stay_current_event"
    assert result_new["scores"]["focus"]["switch_new_event"] > result_gap["scores"]["focus"]["switch_new_event"]


def test_factual_vs_reflection_slot_weight_changes_slot_ranking():
    state = _build_state()
    _append_turn_with_extraction(state, info_gain_like=True)

    focus_event_payload = {
        "event_id": "evt_focus",
        "missing_slots": ["time", "reflection"],
        "people_names": ["母亲"],
    }

    factual_first = PlannerDecisionPolicy(
        PlannerDecisionWeights.from_config(
            {
                "factual_slot_weight": 1.4,
                "reflection_slot_weight": 0.5,
            }
        )
    )
    reflection_first = PlannerDecisionPolicy(
        PlannerDecisionWeights.from_config(
            {
                "factual_slot_weight": 0.7,
                "reflection_slot_weight": 2.0,
            }
        )
    )

    factual_result = factual_first.evaluate(state, 0.4, focus_event_payload, fallback_repeat_count=0)
    reflection_result = reflection_first.evaluate(state, 0.4, focus_event_payload, fallback_repeat_count=0)

    assert factual_result["slot_rankings"][0]["slot"] == "time"
    assert reflection_result["slot_rankings"][0]["slot"] == "reflection"


def test_low_gain_penalty_and_high_coverage_can_trigger_close_hint():
    orchestrator = SessionOrchestrator("hint_test", decision_weights={"low_gain_penalty": 1.8})
    state = _build_state()

    for _ in range(3):
        _append_turn_with_extraction(state, info_gain_like=False)

    hints = orchestrator._build_generation_hints(
        state,
        post_overall_coverage=0.82,
        focus_event_payload={"missing_slots": []},
        last_question="重复问题",
    )

    assert hints["low_info_streak"] == 3
    assert hints["suggest_close"] is True


def test_undercovered_theme_priority_affects_theme_recommendation():
    orchestrator = SessionOrchestrator("theme_test", decision_weights={"theme_coverage_weight": 1.6})
    state = _build_state()
    _append_turn_with_extraction(state, info_gain_like=False)

    state.theme_state = {
        "THEME_HIGH": ThemeState(
            theme_id="THEME_HIGH",
            title="人生篇章",
            status="mentioned",
            priority=2,
            completion_ratio=0.8,
        ),
        "THEME_LOW": ThemeState(
            theme_id="THEME_LOW",
            title="童年记忆",
            status="pending",
            priority=4,
            completion_ratio=0.05,
        ),
    }

    hints = orchestrator._build_generation_hints(
        state,
        post_overall_coverage=0.3,
        focus_event_payload={"missing_slots": []},
        last_question="Q",
    )

    assert hints["recommended_theme_id"] == "THEME_LOW"
    assert hints["theme_rankings"][0]["theme_id"] == "THEME_LOW"


def test_generation_hints_exposes_decision_breakdown_fields():
    orchestrator = SessionOrchestrator("breakdown_test")
    state = _build_state()
    _append_turn_with_extraction(state, info_gain_like=True)

    hints = orchestrator._build_generation_hints(
        state,
        post_overall_coverage=0.45,
        focus_event_payload={"missing_slots": ["time", "people", "reflection"]},
        last_question="上轮问题",
    )

    assert "weights" in hints
    assert "decision_signals" in hints
    assert "decision_scores" in hints
    assert "preferred_action" in hints
    assert "preferred_focus" in hints
    assert isinstance(hints.get("slot_rankings"), list)


def test_weight_vector_mapping_and_roundtrip():
    vector = [1.1, 1.2, 1.3, 0.9, 0.8, 1.4, 1.0, 1.5, 0.7, 1.6]
    weights = PlannerDecisionWeights.from_vector(vector)

    payload = weights.to_dict()
    for key, value in zip(PlannerDecisionWeights.VECTOR_ORDER, vector):
        assert payload[key] == value

    assert weights.to_vector() == vector


def test_orchestrator_accepts_vector_input_for_weights():
    vector = [1.0, 1.1, 1.2, 0.9, 0.8, 1.0, 0.95, 1.3, 0.75, 1.05]
    orchestrator = SessionOrchestrator("vector_input_test", decision_weights=vector)

    payload = orchestrator.get_decision_weight_payload()
    assert payload["weight_vector"] == vector
    assert payload["weight_vector_order"] == list(PlannerDecisionWeights.VECTOR_ORDER)
