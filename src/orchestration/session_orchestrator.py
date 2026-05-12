from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.agents.evaluator_agent import EvaluatorAgent
from src.agents.graph_extraction_agent import GraphExtractionAgent
from src.agents.interviewer_agent import InterviewerAgent
from src.config import Config
from src.orchestration.state_store import InMemorySessionStateStore
from src.services import ProfileProjector
from src.services.entity_vector_store import EntityVectorStore
from src.services.history_compressor import HistoryCompressor
from src.services.graph_coverage import GraphCoverageCalculator
from src.services.graph_rag_metrics import build_graph_rag_metrics
from src.services.graph_rag_decision_context import GraphRAGDecisionContextBuilder
from src.services.graph_writer import GraphWriter
from src.services.hybrid_retriever import HybridRetriever
from src.services.session_graph_bridge import SessionGraphBridge
from openai import OpenAI

from src.state import (
    BackgroundJobStatus,
    ElderProfile,
    ExtractionMetadata,
    ExtractionResult,
    GraphDelta,
    SessionState,
    TurnRecord,
)
from src.state.narrative_models import NarrativeFragment
from src.storage.neo4j.manager import Neo4jGraphManager
from src.pipeline.timing import TurnTokenUsage
from src.tools.planner_tools import PlannerToolSystem

logger = logging.getLogger(__name__)


class SessionOrchestrator:
    def __init__(
        self,
        session_id: str,
        store: Optional[InMemorySessionStateStore] = None,
        interviewer_agent: Optional[InterviewerAgent] = None,
        evaluator_agent: Optional[EvaluatorAgent] = None,
        profile_projector: Optional[ProfileProjector] = None,
        mode: Optional[str] = None,
        decision_weights: Optional[Any] = None,
        reset_graph_on_start: bool = False,
    ):
        self.session_id = session_id
        self.store = store or InMemorySessionStateStore()
        self.interviewer_agent = interviewer_agent or InterviewerAgent()
        self.evaluator_agent = evaluator_agent or EvaluatorAgent()
        self.profile_projector = profile_projector or ProfileProjector()
        self.mode = "graph_rag"
        self._legacy_mode = mode
        self._decision_weights = decision_weights
        self._reset_graph_on_start = bool(reset_graph_on_start)

        # Neo4j graph manager (lazy connect)
        self._neo4j_manager: Optional[Neo4jGraphManager] = None

        # GraphRAG pipeline components (lazy init after Neo4j is ready)
        self._graph_extraction_agent = GraphExtractionAgent()
        self._entity_vector_store = EntityVectorStore()
        self._graph_writer: Optional[GraphWriter] = None
        self._hybrid_retriever: Optional[HybridRetriever] = None
        self._session_graph_bridge: Optional[SessionGraphBridge] = None
        self._decision_ctx_builder: Optional[GraphRAGDecisionContextBuilder] = None
        self._coverage_calculator = GraphCoverageCalculator()

        self._evaluation_threads: Dict[str, threading.Thread] = {}
        self._profile_threads: Dict[str, threading.Thread] = {}

        # Conversation summary compressor (lazy init)
        self._compressor: Optional[HistoryCompressor] = None

    # ── Neo4j lazy connection ──

    def _get_neo4j_manager(self) -> Neo4jGraphManager:
        if self._neo4j_manager is None:
            self._neo4j_manager = Neo4jGraphManager()
            self._neo4j_manager.initialize()
        return self._neo4j_manager

    # ── GraphRAG lazy initialization helpers ──

    def _get_graph_writer(self) -> GraphWriter:
        if self._graph_writer is None:
            self._graph_writer = GraphWriter(
                neo4j_manager=self._get_neo4j_manager(),
                entity_vector_store=self._entity_vector_store,
            )
        return self._graph_writer

    def _get_hybrid_retriever(self) -> HybridRetriever:
        if self._hybrid_retriever is None:
            self._hybrid_retriever = HybridRetriever(
                neo4j_manager=self._get_neo4j_manager(),
                entity_vector_store=self._entity_vector_store,
            )
        return self._hybrid_retriever

    def _get_session_graph_bridge(self) -> SessionGraphBridge:
        if self._session_graph_bridge is None:
            self._session_graph_bridge = SessionGraphBridge(
                neo4j_manager=self._get_neo4j_manager(),
                entity_vector_store=self._entity_vector_store,
            )
        return self._session_graph_bridge

    def _get_decision_context_builder(self) -> GraphRAGDecisionContextBuilder:
        if self._decision_ctx_builder is None:
            self._decision_ctx_builder = GraphRAGDecisionContextBuilder(
                neo4j_manager=self._get_neo4j_manager(),
                entity_vector_store=self._entity_vector_store,
                extraction_agent=self._graph_extraction_agent,
            )
        return self._decision_ctx_builder

    def _get_compressor(self) -> HistoryCompressor:
        if self._compressor is None:
            client = OpenAI(**Config.get_openai_client_kwargs())
            self._compressor = HistoryCompressor(client)
        return self._compressor

    # ── Session lifecycle ──

    def initialize_session(self, elder_info: Dict[str, Any]) -> SessionState:
        _t0 = time.perf_counter()
        elder_profile = self._build_elder_profile(elder_info)
        now = datetime.now()
        state = SessionState(
            session_id=self.session_id,
            created_at=now,
            updated_at=now,
            elder_profile=elder_profile,
        )
        if Config.ENABLE_DYNAMIC_PROFILE_UPDATE:
            state.dynamic_profile = self.profile_projector.build_initial_profile(state)
        logger.info("[init] profile built: %.1fms", (time.perf_counter() - _t0) * 1000)

        # Sync initial theme state to Neo4j
        _t1 = time.perf_counter()
        try:
            neo4j = self._get_neo4j_manager()
            if self._reset_graph_on_start:
                reset_result = neo4j.reset_interview_graph(preserve_topics=True)
                state.metadata["graph_reset_on_start"] = reset_result
                logger.info("[init] graph reset: %s", reset_result)
            neo4j.sync_themes_to_neo4j()
        except Exception:
            logger.debug("Neo4j theme sync skipped", exc_info=True)
        logger.info("[init] neo4j connect + theme sync: %.1fms", (time.perf_counter() - _t1) * 1000)

        # Load cross-session history
        _t2 = time.perf_counter()
        bridge_context = self._load_cross_session_history(state)
        logger.info("[init] cross-session history: %.1fms", (time.perf_counter() - _t2) * 1000)

        # Build theme state from Neo4j
        _t3 = time.perf_counter()
        state.theme_state = self._build_theme_state_from_neo4j()
        logger.info("[init] theme state build: %.1fms", (time.perf_counter() - _t3) * 1000)

        # Build decision context and generate first question
        _t4 = time.perf_counter()
        decision_ctx = self._get_decision_context_builder().build(
            state, 
            None, 
            None, 
            bridge_result=bridge_context,
            enable_query_optimization=Config.QUERY_OPTIMIZATION_ENABLED,
        )
        logger.info("[init] decision context: %.1fms", (time.perf_counter() - _t4) * 1000)

        _t5 = time.perf_counter()
        generated = self.interviewer_agent.generate_question(
            state.elder_profile,
            [],
            decision_ctx,
        )
        logger.info("[init] LLM question generation: %.1fms", (time.perf_counter() - _t5) * 1000)

        state.current_focus_theme_id = decision_ctx.current_focus_theme_id
        state.pending_question = generated["question"]
        state.pending_action = generated["action"]
        state.metadata["pending_planner_plan"] = generated.get("planner_plan", {})
        state.session_metrics = self._compute_session_metrics()
        self.store.save(state)
        logger.info("[init] TOTAL: %.1fms", (time.perf_counter() - _t0) * 1000)
        return state

    async def process_user_response(self, user_response: str) -> Dict[str, Any]:
        state = self._require_state()
        pre_coverage = self._compute_overall_coverage()

        turn_record = TurnRecord(
            turn_id=f"turn_{uuid.uuid4().hex[:10]}",
            turn_index=state.turn_count + 1,
            timestamp=datetime.now(),
            interviewer_question=state.pending_question or "",
            interviewee_answer=user_response,
        )
        current_interviewer_action = state.pending_action or "continue"

        # ── Graph extraction ──
        # The current answer is extracted first, then written to the graph.
        # Planner retrieval happens after the write so the next question can
        # use freshly committed GraphRAG evidence.
        _t = time.perf_counter()
        graph_extraction, _extraction_usage = await self._graph_extraction_agent.extract(
            state, turn_record, graph_context=None,
            neo4j_manager=self._get_neo4j_manager(),
        )
        _extraction_ms = (time.perf_counter() - _t) * 1000

        # ── Write to Neo4j ──
        _t = time.perf_counter()
        write_result = self._get_graph_writer().write_extraction(
            graph_extraction,
            session_id=self.session_id,
            elder_id=f"{state.elder_profile.name}_{state.elder_profile.birth_year}",
        )
        _write_ms = (time.perf_counter() - _t) * 1000

        # ── Update narrative fragments in state ──
        fragment_candidates: List[NarrativeFragment] = []
        for entity in graph_extraction.event_entities:
            fragment = NarrativeFragment(
                fragment_id=f"frag_{uuid.uuid4().hex[:10]}",
                rich_text=entity.description,
                source_turn_ids=[turn_record.turn_id],
                theme_id=entity.properties.get("theme_id"),
                properties=entity.properties,
                confidence=graph_extraction.confidence,
            )
            state.narrative_fragments[fragment.fragment_id] = fragment
            fragment_candidates.append(fragment)

        turn_record.extraction_result = ExtractionResult(
            turn_id=turn_record.turn_id,
            metadata=ExtractionMetadata(
                extractor_version="graph_rag_v1",
                confidence=graph_extraction.confidence,
                source_spans=[user_response[:120]] if user_response else [],
            ),
            graph_delta=GraphDelta(
                fragment_candidates=fragment_candidates,
                graph_extraction=graph_extraction,
            ),
            debug_trace={
                "entity_count": len(graph_extraction.entities),
                "relationship_count": len(graph_extraction.relationships),
                "event_count": len(graph_extraction.event_entities),
            },
        )

        graph_changes = {
            "new_entities": write_result.new_entity_count if write_result else 0,
            "relationships": write_result.relationship_count if write_result else 0,
        }
        extraction_prompt_stats = getattr(self._graph_extraction_agent, "last_input_chars", {}) or {}

        # ── Append turn and update state ──
        state.transcript.append(turn_record)
        state.theme_state = self._build_theme_state_from_neo4j()

        # ── Update within-session conversation summary ──
        self._maybe_update_conversation_summary(state)

        # ── Planner retrieval from the updated graph ──
        # If query optimization is enabled, the decision context builder will
        # delegate retrieval to the extraction agent. Otherwise, use HybridRetriever.
        _graph_rag_context = None
        graph_rag_retrieval = None
        
        if not Config.QUERY_OPTIMIZATION_ENABLED:
            # Direct retrieval path
            graph_rag_retrieval = self._get_hybrid_retriever().retrieve(
                user_response, self.session_id
            )
            _graph_rag_context = graph_rag_retrieval.prompt_text

        # ── Build decision context and generate next question ──
        decision_ctx = self._get_decision_context_builder().build(
            state, 
            graph_extraction, 
            _graph_rag_context,
            session_id=self.session_id,
            user_response=user_response,
            enable_query_optimization=Config.QUERY_OPTIMIZATION_ENABLED,
        )
        _t = time.perf_counter()
        generated = self.interviewer_agent.generate_question(
            state.elder_profile,
            state.recent_transcript(3),
            decision_ctx,
            planner_tool_system=PlannerToolSystem(
                state.elder_profile,
                state.recent_transcript(3),
                decision_ctx,
                neo4j_manager=self._get_neo4j_manager(),
            ),
        )
        _interviewer_llm_ms = (time.perf_counter() - _t) * 1000
        planner_plan = generated.get("planner_plan", {})
        
        # If retrieval wasn't done earlier, do it now for metrics
        # (but only the decision context will be used for planning in optimization mode)
        if Config.QUERY_OPTIMIZATION_ENABLED and graph_rag_retrieval is None:
            graph_rag_retrieval = self._get_hybrid_retriever().retrieve(
                user_response, self.session_id
            )
        
        graph_rag_metrics = build_graph_rag_metrics(
            extraction=graph_extraction,
            write_result=write_result,
            planner_retrieval=graph_rag_retrieval,
            decision_ctx=decision_ctx,
            extraction_ms=_extraction_ms,
            write_ms=_write_ms,
        )

        _interviewer_llm_usage = generated.get("llm_usage") or {}
        _token_usage = TurnTokenUsage(
            interviewer_prompt_tokens=_interviewer_llm_usage.get("prompt_tokens"),
            interviewer_completion_tokens=_interviewer_llm_usage.get("completion_tokens"),
            extraction_prompt_tokens=_extraction_usage.get("prompt_tokens"),
            extraction_completion_tokens=_extraction_usage.get("completion_tokens"),
        )

        self._update_generation_metadata(state, generated, turn_record.interviewer_question)
        turn_debug_trace = {
            "extraction_ms": _extraction_ms,
            "write_ms": _write_ms,
            "retrieval_ms": graph_rag_retrieval.latency_ms if graph_rag_retrieval else 0.0,
            "interviewer_llm_ms": _interviewer_llm_ms,
            "extraction_prompt": extraction_prompt_stats,
            "pipeline": "graph_rag",
            "graph_changes": graph_changes,
            "decision_ctx": {
                "overall_coverage": decision_ctx.overall_coverage,
                "low_info_streak": decision_ctx.low_info_streak,
                "explorable_angles_count": len(decision_ctx.explorable_angles),
            },
            "planning": self._build_planning_trace(generated),
            "planner_plan": planner_plan,
            "graph_rag_metrics": graph_rag_metrics,
            "tool_trace": generated.get("tool_trace", []),
            "token_usage": _token_usage.to_dict(),
        }
        turn_record.debug_trace = turn_debug_trace
        state.pending_question = generated["question"]
        state.pending_action = generated["action"]
        state.metadata["pending_planner_plan"] = planner_plan
        if decision_ctx.current_focus_theme_id:
            state.current_focus_theme_id = decision_ctx.current_focus_theme_id
        state.session_metrics = self._compute_session_metrics()
        # ── Background profile update + synchronous turn evaluation ──
        self._schedule_dynamic_profile_update(state, turn_record)
        post_coverage = decision_ctx.overall_coverage
        turn_evaluation = self.evaluator_agent.evaluate_turn(
            state,
            turn_record,
            pre_coverage,
            post_coverage,
            current_interviewer_action,
        )
        turn_record.turn_evaluation = turn_evaluation
        state.evaluation_trace.append(turn_evaluation)
        state.session_metrics = self._compute_session_metrics()
        self.store.save(state)

        return {
            "question": state.pending_question,
            "action": state.pending_action,
            "graph_changes": graph_changes,
            "current_graph_state": self.get_graph_state(),
            "turn_count": state.turn_count,
            "turn_evaluation": {
                **turn_evaluation.to_dict(),
                "status": "completed",
            },
            "session_metrics": state.session_metrics.to_dict() if state.session_metrics else {},
            "planner_plan": planner_plan,
            "graph_rag_metrics": graph_rag_metrics,
            "debug_trace": turn_debug_trace,
            "extracted_events": [e.to_dict() for e in graph_extraction.entities],
        }

    def get_pending_question_result(self) -> Dict[str, Any]:
        state = self._require_state()
        return {
            "question": state.pending_question or "",
            "action": state.pending_action or "continue",
            "graph_changes": {},
            "current_graph_state": self.get_graph_state(),
            "turn_count": state.turn_count,
            "turn_evaluation": {},
            "session_metrics": state.session_metrics.to_dict() if state.session_metrics else {},
            "planner_plan": state.metadata.get("pending_planner_plan", {}),
            "debug_trace": {
                "planning": self._build_planning_trace(
                    {
                        "action": state.pending_action or "continue",
                        "planner_plan": state.metadata.get("pending_planner_plan", {}),
                    }
                )
            },
            "extracted_events": [],
        }

    def get_graph_state(self) -> Dict[str, Any]:
        state = self._require_state()
        neo4j = self._get_neo4j_manager()
        try:
            theme_coverage = self._coverage_calculator.compute_theme_coverage(neo4j)
        except Exception:
            theme_coverage = {}
        if not theme_coverage:
            theme_coverage = {tid: 0.0 for tid in state.theme_state}

        overall = sum(theme_coverage.values()) / len(theme_coverage) if theme_coverage else 0.0
        themes = [
            {"theme_id": tid, "title": ts.title, "status": ts.status,
             "narrative_richness": theme_coverage.get(tid, 0.0)}
            for tid, ts in state.theme_state.items()
        ]
        return {
            "session_id": state.session_id,
            "coverage_metrics": {
                "theme_richness": theme_coverage,
                "overall_richness": round(overall, 4),
            },
            "theme_nodes": themes,
            "narrative_fragments": {
                fid: frag.to_dict() for fid, frag in state.narrative_fragments.items()
            },
            "dynamic_profile": self._build_dynamic_profile_hint(state),
            "turn_count": state.turn_count,
            "timestamp": datetime.now().isoformat(),
        }

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
        return {
            "session_id": state.session_id,
            "turn_count": state.turn_count,
            "completed_turn_count": len(completed),
            "turn_evaluations": completed,
            "turns": turns,
            "latest_turn_evaluation": state.evaluation_trace[-1].to_dict() if state.evaluation_trace else None,
            "session_metrics": state.session_metrics.to_dict() if state.session_metrics else {},
            "dynamic_profile": self._build_dynamic_profile_hint(state),
        }

    def get_decision_weight_payload(self) -> Dict[str, Any]:
        """Compatibility payload for experiment UIs that still pass weights.

        GraphRAG currently routes decisions through explicit graph-derived
        context plus the interviewer model.  The payload is kept so callers can
        record which experiment settings were requested without reviving the
        deleted slot-based decision policy.
        """
        return {
            "mode": self.mode,
            "legacy_mode": self._legacy_mode,
            "decision_weights": self._decision_weights or {},
            "applied_to": "graph_rag_context",
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

        output_file = os.path.join(results_dir, f"graph_rag_{state.session_id}.txt")
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(f"=== GraphRAG Interview - Session {state.session_id} ===\n\n")
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

        state_path = os.path.join(results_dir, f"graph_rag_state_{state.session_id}.json")
        with open(state_path, "w", encoding="utf-8") as file:
            json.dump(state.to_dict(), file, ensure_ascii=False, indent=2)
        return output_file

    async def close(self) -> None:
        if self._neo4j_manager:
            self._neo4j_manager.close()

    # ── Coverage / metrics helpers ──

    def _compute_overall_coverage(self) -> float:
        try:
            coverage = self._coverage_calculator.compute_theme_coverage(self._get_neo4j_manager())
            return sum(coverage.values()) / len(coverage) if coverage else 0.0
        except Exception:
            return 0.0

    def _compute_session_metrics(self) -> Any:
        from src.state import SessionMetrics
        overall = self._compute_overall_coverage()
        return SessionMetrics(overall_theme_coverage=round(overall, 4))

    def _build_theme_state_from_neo4j(self) -> Dict[str, Any]:
        from src.state import ThemeState
        from src.core.theme_loader import ThemeLoader
        neo4j = self._get_neo4j_manager()
        theme_state: Dict[str, ThemeState] = {}
        try:
            rows = neo4j.driver.execute_query(
                """
                MATCH (t:Topic)
                OPTIONAL MATCH (t)-[:INCLUDES]->(e:Event)
                RETURN t.id AS theme_id, t.title AS title, t.status AS status,
                       t.priority AS priority, count(e) AS entity_count
                """
            )
            for row in rows:
                tid = row["theme_id"]
                if not tid:
                    continue
                theme_state[tid] = ThemeState(
                    theme_id=tid,
                    title=row.get("title", tid),
                    status=row.get("status", "pending") or "pending",
                    priority=int(row.get("priority", 5) or 5),
                    entity_count=int(row.get("entity_count", 0) or 0),
                )
        except Exception:
            logger.debug("Theme state query failed", exc_info=True)
        if not theme_state:
            try:
                themes = ThemeLoader().load()
                for tid, theme in themes.items():
                    theme_state[tid] = ThemeState(
                        theme_id=tid,
                        title=theme.title,
                        status=theme.status.value,
                        priority=theme.priority,
                        entity_count=0,
                    )
            except Exception:
                logger.debug("Local theme fallback failed", exc_info=True)
        return theme_state

    # ── Cross-session memory ──

    def _load_cross_session_history(self, state: SessionState):
        elder_id = f"{state.elder_profile.name}_{state.elder_profile.birth_year}"
        try:
            bridge = self._get_session_graph_bridge()
            result = bridge.load_previous_session(elder_id)
            if result.has_history:
                logger.info(
                    "Cross-session history loaded: %d entities for %s",
                    result.entity_count, elder_id,
                )
            return result
        except Exception:
            logger.debug("Cross-session history load failed", exc_info=True)
            return None

    # ── Conversation summary ──

    def _maybe_update_conversation_summary(self, state: SessionState) -> None:
        max_recent = Config.HISTORY_COMPRESS_MAX_RECENT_TURNS
        if state.turn_count <= max_recent:
            return
        old_turns = state.transcript[:-max_recent]
        total_chars = sum(
            len(t.interviewer_question or "") + len(t.interviewee_answer or "")
            for t in old_turns
        )
        if total_chars < Config.HISTORY_COMPRESS_MAX_CHAR_THRESHOLD // 3:
            return
        turns_data = [
            {"question": t.interviewer_question or "", "answer": t.interviewee_answer or ""}
            for t in old_turns
        ]
        try:
            compressor = self._get_compressor()
            new_summary = compressor.compress_qa_pairs(
                turns_data, state.conversation_summary,
            )
            if new_summary:
                state.conversation_summary = new_summary
                logger.info(
                    "Conversation summary updated: %d old turns → %d chars",
                    len(old_turns), len(new_summary),
                )
        except Exception as exc:
            logger.warning("Conversation summary update failed: %s", exc)

    # ── Dynamic profile (async) ──

    def _schedule_dynamic_profile_update(
        self, state: SessionState, turn_record: TurnRecord,
    ) -> None:
        if not Config.ENABLE_DYNAMIC_PROFILE_UPDATE:
            return
        try:
            should_update, reason = self.profile_projector.should_update(
                state, None, turn_record,
                min_turns_between_updates=Config.DYNAMIC_PROFILE_MIN_TURNS_BETWEEN_UPDATES,
                max_turns_between_updates=Config.DYNAMIC_PROFILE_MAX_TURNS_BETWEEN_UPDATES,
            )
            if not should_update:
                return
        except Exception:
            return

        job_id = f"profile_update_{turn_record.turn_id}"
        if not any(job.job_id == job_id for job in state.pending_jobs):
            state.pending_jobs.append(
                BackgroundJobStatus(job_id=job_id, job_type="dynamic_profile_update")
            )
            self.store.save(state)

        worker = threading.Thread(
            target=self._update_dynamic_profile_background,
            args=(turn_record.turn_id, job_id),
            daemon=True,
        )
        self._profile_threads[turn_record.turn_id] = worker
        worker.start()

    def _update_dynamic_profile_background(self, turn_id: str, job_id: str) -> None:
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
                state, turn_record, None, "scheduled",
            )
            state.metadata["dynamic_profile_last_turn_index"] = turn_record.turn_index
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

    # ── Turn evaluation (async) ──

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
                state, turn_record,
                pre_overall_coverage, post_overall_coverage,
                interviewer_action,
            )
            turn_record.turn_evaluation = evaluation
            state.evaluation_trace.append(evaluation)
            state.session_metrics = self._compute_session_metrics()
            self.store.save(state)
        finally:
            self._evaluation_threads.pop(turn_id, None)

    # ── Utility methods ──

    def _build_dynamic_profile_hint(self, state: SessionState) -> Dict[str, Any]:
        from src.services.graph_rag_decision_context import GraphRAGDecisionContextBuilder

        profile = state.dynamic_profile
        if not profile:
            return {}
        compact = GraphRAGDecisionContextBuilder._build_dynamic_profile_hint(profile)
        return {
            "schema_version": profile.schema_version,
            "update_count": profile.update_count,
            "last_updated_turn_id": profile.last_updated_turn_id,
            "profile_quality": dict(profile.profile_quality or {}),
            **compact,
        }

    def _update_generation_metadata(
        self, state: SessionState, generated: Dict[str, Any], last_question: str,
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

    def _build_planning_trace(self, generated: Dict[str, Any]) -> Dict[str, Any]:
        planner_plan = generated.get("planner_plan") or {}
        if not isinstance(planner_plan, dict):
            planner_plan = {}

        completeness = planner_plan.get("event_completeness") or {}
        if not isinstance(completeness, dict):
            completeness = {}

        focus = planner_plan.get("focus") or {}
        if not isinstance(focus, dict):
            focus = {"label": str(focus)}

        emotion = planner_plan.get("emotion_signal") or {}
        if not isinstance(emotion, dict):
            emotion = {}

        candidates = planner_plan.get("candidate_actions") or []
        if not isinstance(candidates, list):
            candidates = []

        return {
            "next_action": generated.get("action", "continue"),
            "selected_action": planner_plan.get("selected_action", ""),
            "stage": planner_plan.get("stage", ""),
            "focus": focus,
            "selected_slot_or_angle": planner_plan.get("selected_slot_or_angle", ""),
            "event_completeness_score": completeness.get("score"),
            "missing_dimensions": completeness.get("missing_dimensions", []),
            "emotion_energy": emotion.get("energy"),
            "emotion_valence": emotion.get("valence"),
            "candidate_actions": candidates[:4],
            "question_intent": planner_plan.get("question_intent", ""),
        }

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

    def _require_state(self) -> SessionState:
        state = self.store.get(self.session_id)
        if not state:
            raise RuntimeError(f"Session {self.session_id} has not been initialized.")
        return state
