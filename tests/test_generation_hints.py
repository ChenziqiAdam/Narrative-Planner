from datetime import datetime

from src.orchestration.session_orchestrator import SessionOrchestrator
from src.state import ElderProfile, SessionState, ThemeState, TurnEvaluation, TurnRecord


def _build_turn(turn_id: str, info_gain: float) -> TurnRecord:
    turn = TurnRecord(
        turn_id=turn_id,
        turn_index=int(turn_id.split("_")[-1]),
        timestamp=datetime.now(),
        interviewer_question="Q",
        interviewee_answer="A",
    )
    turn.turn_evaluation = TurnEvaluation(
        turn_id=turn_id,
        question_quality_score=0.5,
        information_gain_score=info_gain,
        non_redundancy_score=0.5,
        slot_targeting_score=0.5,
        emotional_alignment_score=0.5,
        planner_alignment_score=0.5,
    )
    return turn


def _build_state(transcript: list[TurnRecord]) -> SessionState:
    now = datetime.now()
    return SessionState(
        session_id="test_session",
        mode="planner",
        created_at=now,
        updated_at=now,
        elder_profile=ElderProfile(name="测试老人"),
        transcript=transcript,
    )


def test_low_info_streak_triggers_breadth_switch_hint():
    orchestrator = SessionOrchestrator("test_session")
    state = _build_state(
        [
            _build_turn("turn_1", 0.06),
            _build_turn("turn_2", 0.05),
        ]
    )

    hints = orchestrator._build_generation_hints(state, post_overall_coverage=0.40)

    assert hints["low_info_streak"] == 2
    assert hints["prefer_breadth_switch"] is True
    assert hints["suggest_close"] is False


def test_low_info_streak_and_high_coverage_suggest_close():
    orchestrator = SessionOrchestrator("test_session")
    state = _build_state(
        [
            _build_turn("turn_1", 0.04),
            _build_turn("turn_2", 0.03),
            _build_turn("turn_3", 0.02),
        ]
    )

    hints = orchestrator._build_generation_hints(state, post_overall_coverage=0.82)

    assert hints["low_info_streak"] == 3
    assert hints["prefer_breadth_switch"] is True
    assert hints["suggest_close"] is True


def test_generation_hints_track_fallback_repeat_count():
    orchestrator = SessionOrchestrator("test_session")
    state = _build_state([])
    state.metadata["fallback_repeat_count"] = 1
    state.metadata["last_fallback_question"] = "重复问题"

    hints = orchestrator._build_generation_hints(
        state,
        post_overall_coverage=0.30,
        last_question="重复问题",
    )

    assert hints["fallback_repeat_count"] == 2


def test_generation_hints_include_recommended_undercovered_theme():
    orchestrator = SessionOrchestrator("test_session")
    state = _build_state([])
    state.theme_state = {
        "THEME_A": ThemeState(
            theme_id="THEME_A",
            title="人生篇章",
            status="mentioned",
            priority=2,
            completion_ratio=0.6,
        ),
        "THEME_B": ThemeState(
            theme_id="THEME_B",
            title="童年记忆",
            status="pending",
            priority=3,
            completion_ratio=0.0,
        ),
    }

    hints = orchestrator._build_generation_hints(
        state,
        post_overall_coverage=0.2,
        last_question="上一轮问题",
    )

    assert hints["recommended_theme_id"] == "THEME_B"
    assert hints["recommended_theme_title"] == "童年记忆"
