from __future__ import annotations

import asyncio
import queue
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.extraction_agent import ExtractionAgent
from src.core.graph_manager import GraphManager
from src.orchestration.state_store import InMemorySessionStateStore
from src.services import CoverageCalculator, GraphProjector, MemoryProjector, MergeEngine
from src.state import ElderProfile, SessionState, TurnRecord


class BaselineEvaluationRuntime:
    """
    Lightweight async scorer for baseline sessions.

    It reuses the extraction / merge / evaluation pipeline so baseline and
    planner share the same scoring logic, while keeping all planner-specific
    planning and memory decisions out of the baseline question loop.
    """

    def __init__(
        self,
        session_id: str,
        store: Optional[InMemorySessionStateStore] = None,
        evaluator_agent: Optional[EvaluatorAgent] = None,
        merge_engine: Optional[MergeEngine] = None,
        graph_projector: Optional[GraphProjector] = None,
        memory_projector: Optional[MemoryProjector] = None,
        coverage_calculator: Optional[CoverageCalculator] = None,
    ):
        self.session_id = session_id
        self.store = store or InMemorySessionStateStore()
        self.graph_manager = GraphManager()
        self.evaluator_agent = evaluator_agent or EvaluatorAgent()
        self.merge_engine = merge_engine or MergeEngine()
        self.graph_projector = graph_projector or GraphProjector()
        self.memory_projector = memory_projector or MemoryProjector()
        self.coverage_calculator = coverage_calculator or CoverageCalculator()
        self._pending_turns: Dict[str, Dict[str, Any]] = {}
        self._submitted_turn_count = 0
        self._lock = threading.RLock()
        self._job_queue: queue.Queue[Optional[str]] = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def initialize_session(self, elder_info: Dict[str, Any]) -> SessionState:
        elder_profile = self._build_elder_profile(elder_info)
        now = datetime.now()
        state = SessionState(
            session_id=self.session_id,
            mode="baseline",
            created_at=now,
            updated_at=now,
            elder_profile=elder_profile,
        )
        state.memory_capsule = self.memory_projector.build_initial_capsule(state)
        self.graph_projector.initialize_from_elder_profile(self.graph_manager, elder_info)
        state.theme_state = self.graph_projector.build_theme_state(self.graph_manager)
        state.session_metrics = self.coverage_calculator.calculate_session_metrics(state, self.graph_manager)
        self.store.save(state)
        return state

    def submit_turn(
        self,
        interviewer_question: str,
        interviewee_answer: str,
        interviewer_action: str = "continue",
    ) -> Dict[str, Any]:
        with self._lock:
            self._require_state()
            self._submitted_turn_count += 1
            turn_id = f"baseline_turn_{uuid.uuid4().hex[:10]}"
            self._pending_turns[turn_id] = {
                "turn_id": turn_id,
                "turn_index": self._submitted_turn_count,
                "timestamp": datetime.now(),
                "interviewer_question": interviewer_question,
                "interviewee_answer": interviewee_answer,
                "interviewer_action": interviewer_action,
            }
        self._job_queue.put(turn_id)
        return {"status": "pending", "turn_id": turn_id}

    def get_evaluation_state(self) -> Dict[str, Any]:
        with self._lock:
            state = self._require_state()
            graph_state = self.graph_projector.build_graph_state(self.graph_manager, state)
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
                }
                for turn in state.transcript
            ]
            return {
                "session_id": state.session_id,
                "turn_count": self._submitted_turn_count,
                "completed_turn_count": len(completed),
                "pending_turn_ids": list(self._pending_turns.keys()),
                "turn_evaluations": completed,
                "turns": turns,
                "session_metrics": state.session_metrics.to_dict() if state.session_metrics else {},
                "coverage_metrics": graph_state.get("coverage_metrics", {}),
                "latest_turn_evaluation": graph_state.get("latest_turn_evaluation", {}),
            }

    def close(self) -> None:
        self._job_queue.put(None)
        if self._worker.is_alive():
            self._worker.join(timeout=1.0)

    def _worker_loop(self) -> None:
        while True:
            turn_id = self._job_queue.get()
            if turn_id is None:
                return
            try:
                asyncio.run(self._process_turn(turn_id))
            except Exception:
                with self._lock:
                    self._pending_turns.pop(turn_id, None)

    async def _process_turn(self, turn_id: str) -> None:
        with self._lock:
            job = self._pending_turns.get(turn_id)
            if not job:
                return
            state = self._require_state()
            pre_graph_summary = self.coverage_calculator.build_graph_summary(state, self.graph_manager)
            turn_record = TurnRecord(
                turn_id=job["turn_id"],
                turn_index=job["turn_index"],
                timestamp=job["timestamp"],
                interviewer_question=job["interviewer_question"],
                interviewee_answer=job["interviewee_answer"],
            )

        extraction_agent = ExtractionAgent()
        try:
            extracted_events, extraction_result = await extraction_agent.extract(state, turn_record)
        finally:
            await extraction_agent.close()

        with self._lock:
            state = self._require_state()
            turn_record.extraction_result = extraction_result
            merge_result = self.merge_engine.merge(state, extracted_events, turn_record.turn_id)
            self.graph_projector.apply_projection(
                state,
                self.graph_manager,
                merge_result.touched_event_ids,
            )
            state.transcript.append(turn_record)
            state.theme_state = self.graph_projector.build_theme_state(self.graph_manager)
            state.memory_capsule = self.memory_projector.refresh(state)
            post_graph_summary = self.coverage_calculator.build_graph_summary(state, self.graph_manager)
            evaluation = self.evaluator_agent.evaluate_turn(
                state,
                turn_record,
                pre_graph_summary.overall_coverage,
                post_graph_summary.overall_coverage,
                job["interviewer_action"],
            )
            turn_record.turn_evaluation = evaluation
            state.evaluation_trace.append(evaluation)
            state.session_metrics = self.coverage_calculator.calculate_session_metrics(state, self.graph_manager)
            self.store.save(state)
            self._pending_turns.pop(turn_id, None)

    def _require_state(self) -> SessionState:
        state = self.store.get(self.session_id)
        if not state:
            raise RuntimeError(f"Session {self.session_id} has not been initialized.")
        return state

    def _build_elder_profile(self, elder_info: Dict[str, Any]) -> ElderProfile:
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
