from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.extraction_agent import ExtractionAgent
from src.agents.interviewer_agent import InterviewerAgent
from src.core.graph_manager import GraphManager
from src.orchestration.state_store import InMemorySessionStateStore
from src.services import CoverageCalculator, GraphProjector, MemoryProjector, MergeEngine
from src.state import ElderProfile, SessionState, TurnRecord


class SessionOrchestrator:
    def __init__(
        self,
        session_id: str,
        mode: str = "planner",
        store: Optional[InMemorySessionStateStore] = None,
        interviewer_agent: Optional[InterviewerAgent] = None,
        extraction_agent: Optional[ExtractionAgent] = None,
        evaluator_agent: Optional[EvaluatorAgent] = None,
        merge_engine: Optional[MergeEngine] = None,
        graph_projector: Optional[GraphProjector] = None,
        memory_projector: Optional[MemoryProjector] = None,
        coverage_calculator: Optional[CoverageCalculator] = None,
    ):
        self.session_id = session_id
        self.mode = mode
        self.store = store or InMemorySessionStateStore()
        self.graph_manager = GraphManager()
        self.interviewer_agent = interviewer_agent or InterviewerAgent()
        self.extraction_agent = extraction_agent or ExtractionAgent()
        self.evaluator_agent = evaluator_agent or EvaluatorAgent()
        self.merge_engine = merge_engine or MergeEngine()
        self.graph_projector = graph_projector or GraphProjector()
        self.memory_projector = memory_projector or MemoryProjector()
        self.coverage_calculator = coverage_calculator or CoverageCalculator()
        self._evaluation_threads: Dict[str, threading.Thread] = {}

    def initialize_session(self, elder_info: Dict[str, Any]) -> SessionState:
        elder_profile = self._build_elder_profile(elder_info)
        now = datetime.now()
        state = SessionState(
            session_id=self.session_id,
            mode=self.mode,
            created_at=now,
            updated_at=now,
            elder_profile=elder_profile,
        )
        state.memory_capsule = self.memory_projector.build_initial_capsule(state)
        self.graph_projector.initialize_from_elder_profile(self.graph_manager, elder_info)
        state.theme_state = self.graph_projector.build_theme_state(self.graph_manager)
        graph_summary = self.coverage_calculator.build_graph_summary(state, self.graph_manager)
        # 统一架构：不再调用 PlannerAgent，规划逻辑整合到 InterviewerAgent 中
        generated = self.interviewer_agent.generate_question(
            state.elder_profile,
            [],
            state.memory_capsule,
            graph_summary,
            focus_event_payload=None,
        )
        state.pending_plan = None  # 统一架构不再使用 Plan 对象
        state.pending_question = generated["question"]
        state.pending_action = generated["action"]
        state.current_focus_theme_id = graph_summary.current_focus_theme_id
        state.session_metrics = self.coverage_calculator.calculate_session_metrics(state, self.graph_manager)
        self.store.save(state)
        return state

    async def process_user_response(self, user_response: str) -> Dict[str, Any]:
        state = self._require_state()
        pre_graph_summary = self.coverage_calculator.build_graph_summary(state, self.graph_manager)
        turn_record = TurnRecord(
            turn_id=f"turn_{uuid.uuid4().hex[:10]}",
            turn_index=state.turn_count + 1,
            timestamp=datetime.now(),
            interviewer_question=state.pending_question or "",
            interviewee_answer=user_response,
            planner_plan=None,  # 统一架构不再使用 Plan 对象
        )
        current_interviewer_action = state.pending_action or "continue"

        extracted_events, extraction_result = await self.extraction_agent.extract(state, turn_record)
        turn_record.extraction_result = extraction_result

        merge_result = self.merge_engine.merge(state, extracted_events, turn_record.turn_id)
        graph_changes = self.graph_projector.apply_projection(
            state,
            self.graph_manager,
            merge_result.touched_event_ids,
        )

        state.transcript.append(turn_record)
        state.theme_state = self.graph_projector.build_theme_state(self.graph_manager)
        # 统一架构：current_focus_theme_id 已在 transcript 更新时维护
        state.memory_capsule = self.memory_projector.refresh(state)
        post_graph_summary = self.coverage_calculator.build_graph_summary(state, self.graph_manager)
        state.session_metrics = self.coverage_calculator.calculate_session_metrics(state, self.graph_manager)

        focus_event_payload = self._build_focus_event_payload(state)
        generated = self.interviewer_agent.generate_question(
            state.elder_profile,
            state.recent_transcript(3),
            state.memory_capsule,
            post_graph_summary,
            focus_event_payload=focus_event_payload,
        )
        state.pending_plan = None  # 统一架构不再使用 Plan 对象
        state.pending_question = generated["question"]
        state.pending_action = generated["action"]
        state.current_focus_theme_id = state.memory_capsule.current_storyline or state.current_focus_theme_id
        self.store.save(state)
        self._schedule_turn_evaluation(
            turn_record.turn_id,
            pre_graph_summary.overall_coverage,
            post_graph_summary.overall_coverage,
            current_interviewer_action,
        )

        return {
            "question": state.pending_question,
            "action": state.pending_action,
            "extracted_events": [event.to_dict() for event in extracted_events],
            "graph_changes": graph_changes,
            "current_graph_state": self.get_graph_state(),
            "turn_count": state.turn_count,
            "turn_evaluation": {"status": "pending", "turn_id": turn_record.turn_id},
            "session_metrics": state.session_metrics.to_dict() if state.session_metrics else {},
            "planner_plan": None,  # 统一架构不再使用 Plan 对象
        }

    def get_pending_question_result(self) -> Dict[str, Any]:
        state = self._require_state()
        return {
            "question": state.pending_question or "",
            "action": state.pending_action or "continue",
            "extracted_events": [],
            "graph_changes": {},
            "current_graph_state": self.get_graph_state(),
            "turn_count": state.turn_count,
            "turn_evaluation": {},
            "session_metrics": state.session_metrics.to_dict() if state.session_metrics else {},
            "planner_plan": None,  # 统一架构不再使用 Plan 对象
        }

    def get_graph_state(self) -> Dict[str, Any]:
        state = self._require_state()
        return self.graph_projector.build_graph_state(self.graph_manager, state)

    def get_evaluation_state(self) -> Dict[str, Any]:
        state = self._require_state()
        graph_state = self.get_graph_state()
        completed = {
            turn.turn_id: turn.turn_evaluation.to_dict()
            for turn in state.transcript
            if turn.turn_evaluation
        }
        pending_turn_ids = [
            turn.turn_id
            for turn in state.transcript
            if not turn.turn_evaluation
        ]
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
            "turn_count": state.turn_count,
            "completed_turn_count": len(completed),
            "pending_turn_ids": pending_turn_ids,
            "turn_evaluations": completed,
            "turns": turns,
            "session_metrics": state.session_metrics.to_dict() if state.session_metrics else {},
            "coverage_metrics": graph_state.get("coverage_metrics", {}),
            "latest_turn_evaluation": graph_state.get("latest_turn_evaluation", {}),
        }

    def build_conversation_history(self) -> List[Dict[str, str]]:
        state = self._require_state()
        history: List[Dict[str, str]] = [
            {"role": "system", "content": f"Session started for {state.elder_profile.name or 'unknown elder'}"}
        ]
        for turn in state.transcript:
            history.append({"role": "assistant", "content": turn.interviewer_question})
            history.append({"role": "user", "content": turn.interviewee_answer})
        if state.pending_question:
            history.append({"role": "assistant", "content": state.pending_question})
        return history

    def save_session(self) -> str:
        state = self._require_state()
        results_dir = "results/conversations"
        os.makedirs(results_dir, exist_ok=True)

        output_file = os.path.join(results_dir, f"planner_{state.session_id}.txt")
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(f"=== Planner Interview - Session {state.session_id} ===\n\n")
            file.write(f"Elder Info: {json.dumps(state.elder_profile.to_dict(), ensure_ascii=False)}\n\n")
            for turn in state.transcript:
                file.write(f"[Interviewer]: {turn.interviewer_question}\n")
                file.write(f"[Interviewee]: {turn.interviewee_answer}\n")
                if turn.turn_evaluation:
                    file.write(
                        f"[TurnEvaluation]: {json.dumps(turn.turn_evaluation.to_dict(), ensure_ascii=False)}\n"
                    )
                file.write("\n")
            if state.pending_question:
                file.write(f"[Interviewer]: {state.pending_question}\n")

        self.graph_manager.save_checkpoint(state.session_id)
        state_path = os.path.join(results_dir, f"planner_state_{state.session_id}.json")
        with open(state_path, "w", encoding="utf-8") as file:
            json.dump(state.to_dict(), file, ensure_ascii=False, indent=2)
        return output_file

    async def close(self) -> None:
        await self.extraction_agent.close()

    def _build_focus_event_payload(self, state: SessionState) -> Optional[Dict[str, Any]]:
        # 获取当前活跃的事件作为焦点
        active_event_ids = state.memory_capsule.active_event_ids if state.memory_capsule else []
        target_event_id = active_event_ids[-1] if active_event_ids else None
        if not target_event_id:
            return None

        event = state.canonical_events.get(target_event_id)
        if not event:
            return None

        known_slots = {
            "time": event.time,
            "location": event.location,
            "people": event.people_names,
            "event": event.event or event.summary,
            "feeling": event.feeling,
            "reflection": event.reflection,
            "cause": event.cause,
            "result": event.result,
        }
        missing_slots = [
            slot_name for slot_name, value in known_slots.items()
            if value in (None, "", [])
        ]
        recent_answer_span = ""
        for turn in reversed(state.transcript):
            if turn.turn_id in event.source_turn_ids:
                recent_answer_span = turn.interviewee_answer
                break

        return {
            "event_id": event.event_id,
            "title": event.title,
            "summary": event.summary,
            "known_slots": known_slots,
            "missing_slots": missing_slots,
            "people_names": list(event.people_names),
            "recent_answer_span": recent_answer_span,
            "unexpanded_clues": list(event.unexpanded_clues),
            "source_turn_ids": list(event.source_turn_ids),
        }

    def _require_state(self) -> SessionState:
        state = self.store.get(self.session_id)
        if not state:
            raise RuntimeError(f"Session {self.session_id} has not been initialized.")
        return state

    def _schedule_turn_evaluation(
        self,
        turn_id: str,
        pre_overall_coverage: float,
        post_overall_coverage: float,
        interviewer_action: str,
    ) -> None:
        worker = threading.Thread(
            target=self._evaluate_turn_background,
            args=(turn_id, pre_overall_coverage, post_overall_coverage, interviewer_action),
            daemon=True,
        )
        self._evaluation_threads[turn_id] = worker
        worker.start()

    def _evaluate_turn_background(
        self,
        turn_id: str,
        pre_overall_coverage: float,
        post_overall_coverage: float,
        interviewer_action: str,
    ) -> None:
        try:
            state = self._require_state()
            turn_record = next((turn for turn in state.transcript if turn.turn_id == turn_id), None)
            if not turn_record or turn_record.turn_evaluation:
                return

            evaluation = self.evaluator_agent.evaluate_turn(
                state,
                turn_record,
                pre_overall_coverage,
                post_overall_coverage,
                interviewer_action,
            )
            turn_record.turn_evaluation = evaluation
            state.evaluation_trace.append(evaluation)
            state.session_metrics = self.coverage_calculator.calculate_session_metrics(state, self.graph_manager)
            self.store.save(state)
        finally:
            self._evaluation_threads.pop(turn_id, None)

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
