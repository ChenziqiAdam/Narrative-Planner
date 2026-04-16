from datetime import datetime

from src.core.interfaces import EventSlots, ExtractedEvent
from src.orchestration.turn_routing_policy import (
    GRAPH_DEFER_ROUTE,
    GRAPH_FAST_ROUTE,
    GRAPH_UPDATE_ROUTE,
    TurnRoutingPolicy,
)
from src.services.merge_engine import MergeEngine
from src.state import ElderProfile, GraphSummary, SessionState, TurnRecord


def _state() -> SessionState:
    return SessionState(
        session_id="routing-test",
        mode="planner",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        elder_profile=ElderProfile(name="测试老人"),
    )


def _turn(answer: str, question: str = "您愿意讲讲那时候的事情吗？") -> TurnRecord:
    return TurnRecord(
        turn_id="turn_test",
        turn_index=1,
        timestamp=datetime.now(),
        interviewer_question=question,
        interviewee_answer=answer,
    )


def _summary() -> GraphSummary:
    return GraphSummary(
        overall_coverage=0.2,
        theme_coverage={"childhood": 0.1, "work": 0.4},
        slot_coverage={},
        people_coverage=0.0,
        current_focus_theme_id=None,
    )


def test_backchannel_routes_to_fast_reply_without_llm():
    decision = TurnRoutingPolicy().evaluate(_state(), _turn("嗯，是的。"), _summary())

    assert decision.route == GRAPH_FAST_ROUTE
    assert decision.llm_used is False
    assert decision.signals["is_backchannel"] is True


def test_targeted_people_answer_requires_graph_update():
    question = "当时和您一起去的还有谁？"
    answer = "那时候是我二姐陪我去的，后来师傅也帮了我很多。"

    decision = TurnRoutingPolicy().evaluate(_state(), _turn(answer, question), _summary())

    assert decision.route == GRAPH_UPDATE_ROUTE
    assert "targeted_slot_answer" in decision.reasons
    assert decision.signals["targeted_slot"] == "people"
    assert decision.signals["answered_targeted_slot"] is True


def test_reflection_can_defer_when_not_targeted_slot():
    answer = "现在回头看，那段日子让我一辈子都明白，做人还是要踏踏实实，不能只看眼前。"

    decision = TurnRoutingPolicy().evaluate(_state(), _turn(answer), _summary())

    assert decision.route in {GRAPH_DEFER_ROUTE, GRAPH_UPDATE_ROUTE}
    assert decision.signals["has_reflection_marker"] is True
    assert decision.llm_used is False


def test_actual_outcome_marks_unsafe_skip_for_high_value_merge():
    policy = TurnRoutingPolicy()
    decision = policy.evaluate(_state(), _turn("嗯。"), _summary())

    class MergeResultStub:
        touched_event_ids = ["evt_1"]
        touched_person_ids = []
        new_event_ids = ["evt_1"]
        updated_event_ids = []
        new_person_ids = []

    actual = policy.build_actual_outcome(
        decision,
        MergeResultStub(),
        extracted_events=[object()],
        pre_coverage=0.1,
        post_coverage=0.2,
        turn_record=_turn("嗯。"),
    )

    assert actual["high_value_update"] is True
    assert actual["skip_would_be_safe"] is False


def test_merge_creates_unique_ids_when_extractor_reuses_new_event_id():
    state = _state()
    engine = MergeEngine()
    events = [
        ExtractedEvent(
            event_id="evt_new_001",
            extracted_at=datetime.now(),
            slots=EventSlots(event=f"事件{i}"),
            confidence=0.8,
        )
        for i in range(2)
    ]

    first = engine.merge(state, [events[0]], "turn_1")
    second = engine.merge(state, [events[1]], "turn_2")

    assert first.new_event_ids[0] == "evt_new_001"
    assert second.new_event_ids[0] != "evt_new_001"
    assert len(state.canonical_events) == 2
