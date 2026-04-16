from datetime import datetime

from src.orchestration.session_orchestrator import SessionOrchestrator
from src.services import MergeResult, ProfileProjector
from src.state import CanonicalEvent, ElderProfile, PersonProfile, SessionState, TurnRecord


def _build_state() -> SessionState:
    now = datetime.now()
    return SessionState(
        session_id="dynamic_profile_test",
        mode="planner",
        created_at=now,
        updated_at=now,
        elder_profile=ElderProfile(
            name="Test Elder",
            birth_year=1942,
            hometown="Chengdu",
            background_summary="Retired textile worker who raised three children.",
        ),
    )


def _build_turn(index: int, answer: str = "I remember that period clearly.") -> TurnRecord:
    return TurnRecord(
        turn_id=f"turn_{index}",
        turn_index=index,
        timestamp=datetime.now(),
        interviewer_question="Q",
        interviewee_answer=answer,
    )


def test_dynamic_profile_uses_significant_event_trigger():
    projector = ProfileProjector()
    state = _build_state()
    state.dynamic_profile = projector.build_initial_profile(state)
    event = CanonicalEvent(
        event_id="evt_major",
        title="Factory promotion",
        summary="Promoted after years of difficult factory work.",
        time="1978",
        location="Chengdu factory",
        people_names=["mentor"],
        event="Promoted after years of difficult factory work.",
        cause="worked hard",
        result="became team lead",
        reflection="I felt grateful for family support and responsibility.",
        confidence=0.82,
        completeness_score=0.75,
    )
    state.canonical_events[event.event_id] = event
    merge_result = MergeResult(touched_event_ids=[event.event_id])

    should_update, reason = projector.should_update(
        state,
        merge_result,
        _build_turn(1),
        min_turns_between_updates=3,
        max_turns_between_updates=5,
    )

    assert should_update is True
    assert reason == "major_event_completed"


def test_dynamic_profile_uses_summary_window_for_non_major_turns():
    projector = ProfileProjector()
    state = _build_state()
    state.dynamic_profile = projector.build_initial_profile(state)
    event = CanonicalEvent(
        event_id="evt_small",
        title="Small detail",
        summary="A small extra detail.",
        confidence=0.3,
        completeness_score=0.25,
    )
    state.canonical_events[event.event_id] = event
    merge_result = MergeResult(touched_event_ids=[event.event_id])

    early_update, early_reason = projector.should_update(
        state,
        merge_result,
        _build_turn(2),
        min_turns_between_updates=3,
        max_turns_between_updates=5,
    )
    window_update, window_reason = projector.should_update(
        state,
        merge_result,
        _build_turn(3),
        min_turns_between_updates=3,
        max_turns_between_updates=5,
    )

    assert early_update is False
    assert early_reason == "below_update_threshold"
    assert window_update is True
    assert window_reason == "summary_turn_window"


def test_dynamic_profile_projects_events_people_and_guidance():
    projector = ProfileProjector()
    state = _build_state()
    state.dynamic_profile = projector.build_initial_profile(state)
    state.people_registry = {
        "person_child": PersonProfile(
            person_id="person_child",
            display_name="eldest son",
            relation_to_elder="child",
            related_event_ids=["evt_major"],
        ),
        "person_spouse": PersonProfile(
            person_id="person_spouse",
            display_name="spouse",
            relation_to_elder="spouse",
            related_event_ids=["evt_major"],
        ),
    }
    event = CanonicalEvent(
        event_id="evt_major",
        title="Factory promotion",
        summary="Promoted after years of difficult factory work.",
        people_names=["eldest son", "spouse"],
        reflection="I felt grateful for family support and responsibility.",
        feeling="proud but it was not easy",
        confidence=0.82,
        completeness_score=0.75,
    )
    state.canonical_events[event.event_id] = event
    turn = _build_turn(3, "I was proud, and I always felt grateful for my family.")

    profile = projector.update_profile(
        state,
        turn,
        MergeResult(touched_event_ids=[event.event_id]),
        reason="major_event_completed",
    )

    assert profile.update_count == 1
    assert profile.last_updated_turn_id == "turn_3"
    assert profile.core_identity_and_personality["life_overview"].value
    assert "responsibility" in profile.life_views_and_attitudes["core_values"].value
    assert profile.family_situation["parents_children"].value
    assert profile.family_situation["marital_status"].value
    assert profile.planner_guidance


def test_generation_hints_include_dynamic_profile_payload():
    projector = ProfileProjector()
    orchestrator = SessionOrchestrator("dynamic_profile_hint_test", profile_projector=projector)
    state = _build_state()
    state.dynamic_profile = projector.build_initial_profile(state)
    profile_field = state.dynamic_profile.family_situation["parents_children"]
    profile_field.value = ["eldest son (child, linked_events=1)"]
    profile_field.confidence = 0.65
    state.dynamic_profile.profile_quality = projector._compute_profile_quality(state.dynamic_profile)
    state.dynamic_profile.planner_guidance = projector._build_planner_guidance(state.dynamic_profile, state)

    hints = orchestrator._build_generation_hints(
        state,
        post_overall_coverage=0.25,
        focus_event_payload={"missing_slots": []},
        last_question="Q",
    )

    assert "dynamic_profile" in hints
    assert hints["dynamic_profile"]["sections"]["family_situation"]["parents_children"]["value"]
    assert hints["profile_guidance"]


def test_evaluation_state_exposes_dynamic_profile_metrics():
    projector = ProfileProjector()
    orchestrator = SessionOrchestrator("dynamic_profile_metrics_test", profile_projector=projector)
    state = _build_state()
    state.session_id = "dynamic_profile_metrics_test"
    state.dynamic_profile = projector.build_initial_profile(state)
    state.dynamic_profile.update_count = 1
    state.dynamic_profile.last_updated_turn_id = "turn_3"
    state.dynamic_profile.last_update_reason = "summary_turn_window"
    turn = _build_turn(3)
    turn.debug_trace = {
        "profile_update": {
            "should_update": True,
            "reason": "summary_turn_window",
        }
    }
    state.transcript.append(turn)
    orchestrator.store.save(state)

    evaluation_state = orchestrator.get_evaluation_state()

    metrics = evaluation_state["dynamic_profile_metrics"]
    assert metrics["update_count"] == 1
    assert metrics["scheduled_update_count"] == 1
    assert metrics["reason_counts"]["summary_turn_window"] == 1
