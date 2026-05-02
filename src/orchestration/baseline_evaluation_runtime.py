from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

from src.agents.evaluator_agent import EvaluatorAgent
from src.orchestration.state_store import InMemorySessionStateStore
from src.state import (
    ElderProfile,
    ExtractionMetadata,
    ExtractionResult,
    GraphDelta,
    SessionMetrics,
    SessionState,
    TurnRecord,
)


class BaselineEvaluationRuntime:
    """Lightweight scorer for the no-planner baseline control group.

    This intentionally does not call the deleted event extraction, merge, slot,
    or graph projection pipeline.  It only records turns and computes the shared
    turn-quality metrics that can be compared with GraphRAG Planner runs.
    """

    def __init__(
        self,
        session_id: str,
        store: InMemorySessionStateStore | None = None,
        evaluator_agent: EvaluatorAgent | None = None,
    ):
        self.session_id = session_id
        self.store = store or InMemorySessionStateStore()
        self.evaluator_agent = evaluator_agent or EvaluatorAgent()

    def initialize_session(self, elder_info: Dict[str, Any] | str | None) -> SessionState:
        elder_info_dict = elder_info if isinstance(elder_info, dict) else {"background": elder_info or ""}
        now = datetime.now()
        state = SessionState(
            session_id=self.session_id,
            mode="baseline",
            created_at=now,
            updated_at=now,
            elder_profile=self._build_elder_profile(elder_info_dict),
            session_metrics=SessionMetrics(),
            metadata={
                "pipeline": "baseline_no_planner",
                "control_group": True,
                "planner_enabled": False,
            },
        )
        self.store.save(state)
        return state

    def submit_turn(
        self,
        question: str,
        answer: str,
        action: str = "continue",
    ) -> Dict[str, Any]:
        state = self._require_state()
        turn_record = TurnRecord(
            turn_id=f"turn_{uuid.uuid4().hex[:10]}",
            turn_index=state.turn_count + 1,
            timestamp=datetime.now(),
            interviewer_question=question or "",
            interviewee_answer=answer or "",
            extraction_result=self._build_baseline_extraction(answer),
            debug_trace={
                "pipeline": "baseline_no_planner",
                "planner_enabled": False,
                "interviewer_action": action,
            },
        )

        state.transcript.append(turn_record)
        turn_evaluation = self.evaluator_agent.evaluate_turn(
            state=state,
            turn_record=turn_record,
            pre_overall_coverage=0.0,
            post_overall_coverage=0.0,
            interviewer_action=action,
        )
        turn_record.turn_evaluation = turn_evaluation
        state.evaluation_trace.append(turn_evaluation)
        state.session_metrics = self._compute_session_metrics(state)
        state.metadata["latest_interviewer_action"] = action
        self.store.save(state)

        payload = turn_evaluation.to_dict()
        payload["status"] = "completed"
        return payload

    def get_evaluation_state(self) -> Dict[str, Any]:
        state = self._require_state()
        completed = {
            turn.turn_id: turn.turn_evaluation.to_dict()
            for turn in state.transcript
            if turn.turn_evaluation
        }
        turns = [
            {
                "turn_id": turn.turn_id,
                "turn_index": turn.turn_index,
                "interviewer_question": turn.interviewer_question,
                "interviewee_answer": turn.interviewee_answer,
                "evaluation_status": "completed" if turn.turn_evaluation else "pending",
                "turn_evaluation": turn.turn_evaluation.to_dict() if turn.turn_evaluation else None,
                "debug_trace": turn.debug_trace,
            }
            for turn in state.transcript
        ]
        latest = state.evaluation_trace[-1].to_dict() if state.evaluation_trace else None

        return {
            "session_id": state.session_id,
            "mode": "baseline",
            "pipeline": "baseline_no_planner",
            "control_group": True,
            "turn_count": state.turn_count,
            "completed_turn_count": len(completed),
            "pending_turn_ids": [],
            "turn_evaluations": completed,
            "turns": turns,
            "latest_turn_evaluation": latest,
            "session_metrics": self._session_metrics_payload(state),
            "coverage_metrics": {
                "overall_coverage": 0.0,
                "overall_richness": 0.0,
                "theme_coverage": {},
                "theme_richness": {},
            },
        }

    def close(self) -> None:
        self.store.delete(self.session_id)

    def _build_baseline_extraction(self, answer: str) -> ExtractionResult:
        answer = (answer or "").strip()
        fragments = [answer] if len(answer) >= 20 else []
        return ExtractionResult(
            turn_id=f"baseline_delta_{uuid.uuid4().hex[:10]}",
            metadata=ExtractionMetadata(
                extractor_version="baseline_no_planner",
                confidence=0.3 if fragments else 0.0,
                source_spans=[answer[:120]] if answer else [],
            ),
            graph_delta=GraphDelta(fragment_candidates=fragments),
            debug_trace={
                "note": "Baseline scoring uses answer length as a minimal information-gain proxy.",
            },
        )

    def _compute_session_metrics(self, state: SessionState) -> SessionMetrics:
        evaluations = state.evaluation_trace
        if not evaluations:
            return SessionMetrics()
        count = len(evaluations)
        return SessionMetrics(
            overall_theme_coverage=0.0,
            average_turn_quality=round(
                sum(item.question_quality_score for item in evaluations) / count,
                4,
            ),
            average_information_gain=round(
                sum(item.information_gain_score for item in evaluations) / count,
                4,
            ),
        )

    def _session_metrics_payload(self, state: SessionState) -> Dict[str, Any]:
        metrics = state.session_metrics.to_dict() if state.session_metrics else SessionMetrics().to_dict()
        metrics.setdefault("people_coverage", 0.0)
        metrics.setdefault("open_loop_closure_rate", 0.0)
        metrics.setdefault("contradiction_resolution_rate", 0.0)
        metrics.setdefault("average_non_redundancy", self._average_non_redundancy(state))
        return metrics

    @staticmethod
    def _average_non_redundancy(state: SessionState) -> float:
        evaluations = state.evaluation_trace
        if not evaluations:
            return 0.0
        return round(sum(item.non_redundancy_score for item in evaluations) / len(evaluations), 4)

    @staticmethod
    def _build_elder_profile(elder_info: Dict[str, Any]) -> ElderProfile:
        age = elder_info.get("age")
        birth_year = elder_info.get("birth_year")
        if not age and birth_year:
            try:
                age = datetime.now().year - int(birth_year)
            except (TypeError, ValueError):
                age = None
        stable_facts = {
            key: value
            for key, value in elder_info.items()
            if key not in {"name", "birth_year", "age", "hometown", "background"}
        }
        return ElderProfile(
            name=elder_info.get("name"),
            birth_year=birth_year,
            age=age,
            hometown=elder_info.get("hometown"),
            background_summary=elder_info.get("background"),
            stable_facts=stable_facts,
        )

    def _require_state(self) -> SessionState:
        state = self.store.get(self.session_id)
        if not state:
            raise RuntimeError(f"Baseline session {self.session_id} has not been initialized.")
        return state
