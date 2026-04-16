from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.extraction_agent import ExtractionAgent
from src.agents.interviewer_agent import InterviewerAgent
from src.config import Config
from src.core.graph_manager import GraphManager
from src.orchestration.planner_decision_policy import (
    PlannerDecisionPolicy,
    PlannerDecisionWeights,
    pick_undercovered_theme,
)
from src.orchestration.state_store import InMemorySessionStateStore
from src.services import (
    CoverageCalculator,
    EventVectorStore,
    GraphProjector,
    MemoryProjector,
    MergeEngine,
    ProfileProjector,
)
from src.state import BackgroundJobStatus, ElderProfile, SessionState, TurnRecord

# Neo4j-backed components (loaded only when NEO4J_ENABLED=true)
if Config.NEO4J_ENABLED:
    from src.services.neo4j_graph_adapter import Neo4jGraphAdapter
    from src.services.neo4j_graph_projector import Neo4jGraphProjector


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
        profile_projector: Optional[ProfileProjector] = None,
        coverage_calculator: Optional[CoverageCalculator] = None,
        decision_weights: Optional[Any] = None,
        event_vector_store: Optional[EventVectorStore] = None,
    ):
        self.session_id = session_id
        self.mode = mode
        self.store = store or InMemorySessionStateStore()
        # Select graph backend based on NEO4J_ENABLED flag.
        if Config.NEO4J_ENABLED:
            self.graph_manager = Neo4jGraphAdapter()
        else:
            self.graph_manager = GraphManager()
        self.interviewer_agent = interviewer_agent or InterviewerAgent()
        self.event_vector_store = event_vector_store or EventVectorStore()
        self.extraction_agent = extraction_agent or ExtractionAgent(vector_store=self.event_vector_store)
        self.evaluator_agent = evaluator_agent or EvaluatorAgent()
        self.merge_engine = merge_engine or MergeEngine()
        if graph_projector:
            self.graph_projector = graph_projector
        elif Config.NEO4J_ENABLED:
            self.graph_projector = Neo4jGraphProjector()
        else:
            self.graph_projector = GraphProjector()
        self.memory_projector = memory_projector or MemoryProjector()
        self.profile_projector = profile_projector or ProfileProjector()
        self.coverage_calculator = coverage_calculator or CoverageCalculator()
        self.decision_policy = PlannerDecisionPolicy(
            PlannerDecisionWeights.from_external(decision_weights)
        )
        self._evaluation_threads: Dict[str, threading.Thread] = {}
        self._profile_threads: Dict[str, threading.Thread] = {}

    def set_decision_weight_vector(self, vector: Sequence[float]) -> None:
        self.decision_policy = PlannerDecisionPolicy(PlannerDecisionWeights.from_vector(vector))

    def set_decision_weights(self, weights: Dict[str, float]) -> None:
        self.decision_policy = PlannerDecisionPolicy(PlannerDecisionWeights.from_config(weights))

    def get_decision_weight_payload(self) -> Dict[str, Any]:
        return {
            "weights": self.decision_policy.weights.to_dict(),
            "weight_vector": self.decision_policy.weights.to_vector(),
            "weight_vector_order": list(self.decision_policy.weights.VECTOR_ORDER),
        }

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
        if Config.ENABLE_DYNAMIC_PROFILE_UPDATE:
            state.dynamic_profile = self.profile_projector.build_initial_profile(state)
        self.graph_projector.initialize_from_elder_profile(self.graph_manager, elder_info)
        # Persist initial theme state to Neo4j if available.
        if Config.NEO4J_ENABLED:
            try:
                self.graph_manager.sync_themes_to_neo4j()
                self.graph_manager._refresh_coverage_cache()
            except Exception:
                logger.debug("Neo4j theme sync skipped", exc_info=True)
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
        self._index_confirmed_events(state, merge_result.touched_event_ids)
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
        profile_update_decision = self._decide_dynamic_profile_update(state, merge_result, turn_record)

        focus_event_payload = self._build_focus_event_payload(state)
        generation_hints = self._build_generation_hints(
            state,
            post_overall_coverage=post_graph_summary.overall_coverage,
            focus_event_payload=focus_event_payload,
            last_question=turn_record.interviewer_question,
        )
        generated = self.interviewer_agent.generate_question(
            state.elder_profile,
            state.recent_transcript(3),
            state.memory_capsule,
            post_graph_summary,
            focus_event_payload=focus_event_payload,
            generation_hints=generation_hints,
        )
        preferred_action = generation_hints.get("preferred_action")
        if preferred_action == "next_phase" and generated.get("action") == "continue":
            missing_slots = focus_event_payload.get("missing_slots", []) if focus_event_payload else []
            if not missing_slots:
                generated["action"] = "next_phase"
        if preferred_action == "end" and generation_hints.get("suggest_close"):
            generated["action"] = "end"
            if not generated.get("question"):
                generated["question"] = "今天聊到这里已经很完整了，谢谢您愿意分享这么多珍贵回忆。"
        self._update_generation_metadata(state, generated, turn_record.interviewer_question)
        turn_debug_trace = self._build_turn_debug_trace(
            turn_record,
            extraction_result.debug_trace,
            merge_result,
            pre_graph_summary.overall_coverage,
            post_graph_summary.overall_coverage,
            generation_hints,
            generated.get("action", ""),
            profile_update_decision,
        )
        turn_record.debug_trace = turn_debug_trace
        state.pending_plan = None  # 统一架构不再使用 Plan 对象
        state.pending_question = generated["question"]
        state.pending_action = generated["action"]
        state.current_focus_theme_id = state.memory_capsule.current_storyline or state.current_focus_theme_id
        self.store.save(state)
        if profile_update_decision.get("should_update"):
            self._schedule_dynamic_profile_update(
                turn_record.turn_id,
                merge_result,
                str(profile_update_decision.get("reason", "scheduled")),
            )
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
            "debug_trace": turn_debug_trace,
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
            "debug_trace": {},
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
                "debug_trace": turn.debug_trace,
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
            "planner_decision_metrics": self._build_planner_decision_metrics(state),
            "dynamic_profile_metrics": self._build_dynamic_profile_metrics(state),
            "decision_weight_payload": self.get_decision_weight_payload(),
            "dynamic_profile": self._build_dynamic_profile_hint(state),
        }

    def _build_turn_debug_trace(
        self,
        turn_record: TurnRecord,
        extraction_trace: Dict[str, Any],
        merge_result: Any,
        pre_coverage: float,
        post_coverage: float,
        generation_hints: Optional[Dict[str, Any]] = None,
        next_action: str = "",
        profile_update_decision: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "schema_version": "planner_debug_v1",
            "turn_id": turn_record.turn_id,
            "extraction": extraction_trace or {},
            "merge": {
                "decisions": list(getattr(merge_result, "merge_decisions", [])),
                "fallback_reasons": list(getattr(merge_result, "fallback_reasons", [])),
                "new_event_ids": list(getattr(merge_result, "new_event_ids", [])),
                "updated_event_ids": list(getattr(merge_result, "updated_event_ids", [])),
            },
            "coverage": {
                "before": pre_coverage,
                "after": post_coverage,
                "delta": post_coverage - pre_coverage,
            },
            "planning": {
                "low_info_streak": int((generation_hints or {}).get("low_info_streak", 0) or 0),
                "prefer_breadth_switch": bool((generation_hints or {}).get("prefer_breadth_switch", False)),
                "suggest_close": bool((generation_hints or {}).get("suggest_close", False)),
                "fallback_repeat_count": int((generation_hints or {}).get("fallback_repeat_count", 0) or 0),
                "preferred_action": (generation_hints or {}).get("preferred_action"),
                "preferred_focus": (generation_hints or {}).get("preferred_focus"),
                "recommended_theme_id": (generation_hints or {}).get("recommended_theme_id"),
                "recommended_theme_title": (generation_hints or {}).get("recommended_theme_title"),
                "decision_weights": (generation_hints or {}).get("weights", {}),
                "decision_weight_vector": (generation_hints or {}).get("weight_vector", []),
                "decision_weight_vector_order": (generation_hints or {}).get("weight_vector_order", []),
                "decision_signals": (generation_hints or {}).get("decision_signals", {}),
                "decision_scores": (generation_hints or {}).get("decision_scores", {}),
                "slot_rankings": (generation_hints or {}).get("slot_rankings", []),
                "theme_rankings": (generation_hints or {}).get("theme_rankings", []),
                "dynamic_profile_quality": (generation_hints or {}).get("dynamic_profile", {}).get("profile_quality", {}),
                "profile_guidance": (generation_hints or {}).get("profile_guidance", []),
                "next_action": next_action or "",
            },
            "profile_update": profile_update_decision or {},
        }

    def _index_confirmed_events(self, state: "SessionState", touched_event_ids: List[str]) -> None:
        for event_id in touched_event_ids:
            event = state.canonical_events.get(event_id)
            if event is None:
                continue
            summary = event.summary or event.title or ""
            if summary:
                try:
                    self.event_vector_store.add(event_id, summary)
                except Exception:
                    logger.warning(f"Failed to index event {event_id}")

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

    def _build_generation_hints(
        self,
        state: SessionState,
        post_overall_coverage: float,
        focus_event_payload: Optional[Dict[str, Any]] = None,
        last_question: str = "",
    ) -> Dict[str, Any]:
        fallback_repeat_count = int(state.metadata.get("fallback_repeat_count", 0) or 0)
        last_fallback_question = str(state.metadata.get("last_fallback_question", "") or "")
        if last_fallback_question and last_question and last_fallback_question == last_question:
            fallback_repeat_count += 1

        # Build optional Neo4j relation service for Chain B.
        relation_service = None
        if Config.NEO4J_ENABLED:
            try:
                from src.services.neo4j_graph_adapter import Neo4jGraphAdapter
                if isinstance(self.graph_manager, Neo4jGraphAdapter):
                    neo4j_mgr = self.graph_manager.get_neo4j_manager()
                    if neo4j_mgr:
                        from src.services.neo4j_relation_service import Neo4jRelationService
                        relation_service = Neo4jRelationService(neo4j_mgr)
            except Exception:
                pass

        policy_result = self.decision_policy.evaluate(
            state=state,
            post_overall_coverage=post_overall_coverage,
            focus_event_payload=focus_event_payload,
            fallback_repeat_count=fallback_repeat_count,
            relation_service=relation_service,
        )
        low_info_streak = int(policy_result.get("low_info_streak", 0) or 0)
        preferred_action = str(policy_result.get("preferred_action", "continue"))

        slot_rankings = list(policy_result.get("slot_rankings", []))
        recommended_slots = [
            item.get("slot")
            for item in slot_rankings
            if isinstance(item, dict) and isinstance(item.get("slot"), str)
        ]

        recommended_theme_id = policy_result.get("recommended_theme_id")
        recommended_theme_title = policy_result.get("recommended_theme_title")
        if not recommended_theme_id:
            recommended_theme_id, recommended_theme_title = self._pick_breadth_switch_theme_from_state(state)

        suggest_close = (
            (preferred_action == "end" and low_info_streak >= 2 and post_overall_coverage >= 0.60)
            or (low_info_streak >= 3 and post_overall_coverage >= 0.78)
        )
        dynamic_profile_hint = self._build_dynamic_profile_hint(state)
        profile_guidance = list(dynamic_profile_hint.get("planner_guidance", []))[
            : max(0, Config.PROFILE_GUIDANCE_MAX_NOTES)
        ]
        return {
            "low_info_streak": low_info_streak,
            "prefer_breadth_switch": preferred_action == "next_phase",
            "suggest_close": suggest_close,
            "fallback_repeat_count": fallback_repeat_count,
            "weights": policy_result.get("weights", {}),
            "weight_vector": policy_result.get("weight_vector", []),
            "weight_vector_order": policy_result.get("weight_vector_order", []),
            "decision_signals": policy_result.get("signals", {}),
            "decision_scores": policy_result.get("scores", {}),
            "preferred_action": preferred_action,
            "preferred_focus": policy_result.get("preferred_focus", "stay_current_event"),
            "slot_rankings": slot_rankings,
            "recommended_slots": recommended_slots,
            "recommended_theme_id": recommended_theme_id,
            "recommended_theme_title": recommended_theme_title,
            "theme_rankings": policy_result.get("theme_rankings", []),
            "suggested_angle": policy_result.get("suggested_angle", ""),
            "dynamic_profile": dynamic_profile_hint,
            "profile_guidance": profile_guidance,
        }

    def _recent_low_information_streak(self, state: SessionState, max_window: int = 3) -> int:
        streak = 0
        for turn in reversed(state.transcript[-max_window:]):
            if self._is_low_information_turn(turn):
                streak += 1
            else:
                break
        return streak

    def _is_low_information_turn(self, turn: TurnRecord) -> bool:
        if turn.turn_evaluation and turn.turn_evaluation.information_gain_score <= 0.08:
            return True

        extracted_count = 0
        if turn.extraction_result:
            extracted_count = len(turn.extraction_result.graph_delta.event_candidates)
        coverage_delta = (
            (turn.debug_trace.get("coverage", {}) or {}).get("delta", 0.0)
            if isinstance(turn.debug_trace, dict)
            else 0.0
        )
        answer_len = len((turn.interviewee_answer or "").strip())
        return extracted_count == 0 and coverage_delta <= 0.005 and answer_len < 40

    def _pick_breadth_switch_theme_from_state(self, state: SessionState) -> tuple[Optional[str], Optional[str]]:
        return pick_undercovered_theme(state.theme_state)

    def _build_dynamic_profile_hint(self, state: SessionState) -> Dict[str, Any]:
        profile = state.dynamic_profile
        if not profile:
            return {}

        sections: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for section_name in (
            "core_identity_and_personality",
            "current_life_status",
            "family_situation",
            "life_views_and_attitudes",
        ):
            section = getattr(profile, section_name, {})
            compact_fields: Dict[str, Dict[str, Any]] = {}
            for field_name, field in section.items():
                if not field or field.value in (None, "", []):
                    continue
                compact_fields[field_name] = {
                    "value": field.value,
                    "confidence": field.confidence,
                    "evidence_turn_ids": list(field.evidence_turn_ids[-3:]),
                    "evidence_event_ids": list(field.evidence_event_ids[-3:]),
                }
            if compact_fields:
                sections[section_name] = compact_fields

        return {
            "schema_version": profile.schema_version,
            "update_count": profile.update_count,
            "last_updated_turn_id": profile.last_updated_turn_id,
            "last_update_reason": profile.last_update_reason,
            "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
            "profile_quality": dict(profile.profile_quality or {}),
            "planner_guidance": list(profile.planner_guidance or []),
            "sections": sections,
        }

    def _decide_dynamic_profile_update(
        self,
        state: SessionState,
        merge_result: Any,
        turn_record: TurnRecord,
    ) -> Dict[str, Any]:
        if not Config.ENABLE_DYNAMIC_PROFILE_UPDATE:
            return {"enabled": False, "should_update": False, "reason": "disabled"}

        should_update, reason = self.profile_projector.should_update(
            state,
            merge_result,
            turn_record,
            min_turns_between_updates=Config.DYNAMIC_PROFILE_MIN_TURNS_BETWEEN_UPDATES,
            max_turns_between_updates=Config.DYNAMIC_PROFILE_MAX_TURNS_BETWEEN_UPDATES,
        )
        last_turn_index = int(state.metadata.get("dynamic_profile_last_turn_index", 0) or 0)
        return {
            "enabled": True,
            "should_update": should_update,
            "reason": reason,
            "turns_since_last_update": max(0, turn_record.turn_index - last_turn_index),
            "min_turns_between_updates": Config.DYNAMIC_PROFILE_MIN_TURNS_BETWEEN_UPDATES,
            "max_turns_between_updates": Config.DYNAMIC_PROFILE_MAX_TURNS_BETWEEN_UPDATES,
        }

    def _build_planner_decision_metrics(self, state: SessionState) -> Dict[str, Any]:
        action_counts = {"continue": 0, "next_phase": 0, "end": 0}
        low_gain_streak_max = 0
        low_gain_streak = 0
        previous_question = ""
        repeated_question_count = 0

        for turn in state.transcript:
            action = str((turn.debug_trace.get("planning", {}) or {}).get("next_action", ""))
            if action in action_counts:
                action_counts[action] += 1

            if self._is_low_information_turn(turn):
                low_gain_streak += 1
                low_gain_streak_max = max(low_gain_streak_max, low_gain_streak)
            else:
                low_gain_streak = 0

            question = (turn.interviewer_question or "").strip()
            if question and previous_question and question == previous_question:
                repeated_question_count += 1
            previous_question = question or previous_question

        early_end_count = 0
        for turn in state.transcript:
            planning = (turn.debug_trace.get("planning", {}) or {})
            if planning.get("next_action") == "end":
                coverage_after = ((turn.debug_trace.get("coverage", {}) or {}).get("after", 0.0) or 0.0)
                if coverage_after < 0.70:
                    early_end_count += 1

        return {
            "action_counts": action_counts,
            "phase_switch_count": action_counts["next_phase"],
            "repeated_question_count": repeated_question_count,
            "low_gain_streak_max": low_gain_streak_max,
            "early_end_count": early_end_count,
        }

    def _build_dynamic_profile_metrics(self, state: SessionState) -> Dict[str, Any]:
        reason_counts: Dict[str, int] = {}
        scheduled_count = 0
        for turn in state.transcript:
            profile_update = (turn.debug_trace.get("profile_update", {}) or {})
            if not profile_update:
                continue
            reason = str(profile_update.get("reason", "") or "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            if profile_update.get("should_update"):
                scheduled_count += 1

        jobs_by_status: Dict[str, int] = {}
        for job in state.pending_jobs:
            if job.job_type != "dynamic_profile_update":
                continue
            jobs_by_status[job.status] = jobs_by_status.get(job.status, 0) + 1

        profile = state.dynamic_profile
        return {
            "enabled": Config.ENABLE_DYNAMIC_PROFILE_UPDATE,
            "scheduled_update_count": scheduled_count,
            "update_count": profile.update_count if profile else 0,
            "last_updated_turn_id": profile.last_updated_turn_id if profile else None,
            "last_update_reason": profile.last_update_reason if profile else None,
            "profile_quality": dict(profile.profile_quality or {}) if profile else {},
            "reason_counts": reason_counts,
            "jobs_by_status": jobs_by_status,
        }

    def _update_generation_metadata(
        self,
        state: SessionState,
        generated: Dict[str, Any],
        last_question: str,
    ) -> None:
        question = str(generated.get("question", "") or "")
        if generated.get("action") == "next_phase":
            state.metadata["last_fallback_question"] = question
            if question and question == last_question:
                state.metadata["fallback_repeat_count"] = int(state.metadata.get("fallback_repeat_count", 0) or 0) + 1
            else:
                state.metadata["fallback_repeat_count"] = 0
            return

        state.metadata["fallback_repeat_count"] = 0

    def _require_state(self) -> SessionState:
        state = self.store.get(self.session_id)
        if not state:
            raise RuntimeError(f"Session {self.session_id} has not been initialized.")
        return state

    def _schedule_dynamic_profile_update(
        self,
        turn_id: str,
        merge_result: Any,
        reason: str,
    ) -> None:
        state = self._require_state()
        job_id = f"profile_update_{turn_id}"
        if not any(job.job_id == job_id for job in state.pending_jobs):
            state.pending_jobs.append(
                BackgroundJobStatus(
                    job_id=job_id,
                    job_type="dynamic_profile_update",
                    status="pending",
                )
            )
            self.store.save(state)

        worker = threading.Thread(
            target=self._update_dynamic_profile_background,
            args=(turn_id, merge_result, reason, job_id),
            daemon=True,
        )
        self._profile_threads[turn_id] = worker
        worker.start()

    def _update_dynamic_profile_background(
        self,
        turn_id: str,
        merge_result: Any,
        reason: str,
        job_id: str,
    ) -> None:
        try:
            state = self._require_state()
            job = next((item for item in state.pending_jobs if item.job_id == job_id), None)
            if job:
                job.status = "running"
                job.updated_at = datetime.now()
                self.store.save(state)

            turn_record = next((turn for turn in state.transcript if turn.turn_id == turn_id), None)
            if not turn_record:
                raise RuntimeError(f"Turn {turn_id} not found for dynamic profile update.")

            state.dynamic_profile = self.profile_projector.update_profile(
                state,
                turn_record,
                merge_result,
                reason,
            )
            state.metadata["dynamic_profile_last_turn_index"] = turn_record.turn_index
            state.metadata["dynamic_profile_last_update_reason"] = reason
            if job:
                job.status = "completed"
                job.updated_at = datetime.now()
            self.store.save(state)
        except Exception:
            logger.exception("Dynamic profile update failed for turn %s", turn_id)
            try:
                state = self._require_state()
                job = next((item for item in state.pending_jobs if item.job_id == job_id), None)
                if job:
                    job.status = "failed"
                    job.updated_at = datetime.now()
                    self.store.save(state)
            except Exception:
                logger.exception("Failed to mark dynamic profile job as failed for turn %s", turn_id)
        finally:
            self._profile_threads.pop(turn_id, None)

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
