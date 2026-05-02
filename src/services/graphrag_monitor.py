from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional

from src.state import GraphSummary, SessionState, TurnRecord


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _average(values: Iterable[float]) -> float:
    collected = [float(value) for value in values]
    return float(mean(collected)) if collected else 0.0


@dataclass
class GraphRAGTurnMetrics:
    """Observe GraphRAG-style retrieval, graph context, and decision influence."""

    turn_id: str
    schema_version: str = "graphrag_monitor_v1"
    enabled_signals: Dict[str, bool] = field(default_factory=dict)
    retrieval: Dict[str, Any] = field(default_factory=dict)
    graph_context: Dict[str, Any] = field(default_factory=dict)
    grounding: Dict[str, Any] = field(default_factory=dict)
    decision_influence: Dict[str, Any] = field(default_factory=dict)
    quality_flags: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "enabled_signals": self.enabled_signals,
            "retrieval": self.retrieval,
            "graph_context": self.graph_context,
            "grounding": self.grounding,
            "decision_influence": self.decision_influence,
            "quality_flags": self.quality_flags,
        }


class GraphRAGMonitor:
    """Build monitoring metrics for the planner's graph + retrieval control path.

    The project does not currently have a single module named "GraphRAG".
    These metrics monitor the GraphRAG-style path that combines semantic event
    retrieval, graph summary/context, memory capsule, and planner decisions.
    """

    def build_turn_metrics(
        self,
        *,
        state: SessionState,
        turn_record: TurnRecord,
        pre_graph_summary: GraphSummary,
        post_graph_summary: GraphSummary,
        generation_hints: Dict[str, Any],
        focus_event_payload: Optional[Dict[str, Any]] = None,
        event_vector_store: Optional[Any] = None,
        retrieval_query: str = "",
    ) -> GraphRAGTurnMetrics:
        retrieval = self._build_retrieval_metrics(
            state=state,
            focus_event_payload=focus_event_payload,
            event_vector_store=event_vector_store,
            retrieval_query=retrieval_query or turn_record.interviewee_answer or turn_record.interviewer_question,
        )
        graph_context = self._build_graph_context_metrics(
            state=state,
            pre_graph_summary=pre_graph_summary,
            post_graph_summary=post_graph_summary,
            focus_event_payload=focus_event_payload,
        )
        grounding = self._build_grounding_metrics(state)
        decision_influence = self._build_decision_influence_metrics(generation_hints)
        quality_flags = self._build_quality_flags(
            turn_record=turn_record,
            retrieval=retrieval,
            graph_context=graph_context,
            decision_influence=decision_influence,
        )

        return GraphRAGTurnMetrics(
            turn_id=turn_record.turn_id,
            enabled_signals={
                "semantic_event_retrieval": bool(event_vector_store is not None),
                "graph_summary": bool(post_graph_summary is not None),
                "memory_capsule": bool(state.memory_capsule is not None),
                "decision_scoring": bool(generation_hints.get("decision_scores")),
            },
            retrieval=retrieval,
            graph_context=graph_context,
            grounding=grounding,
            decision_influence=decision_influence,
            quality_flags=quality_flags,
        )

    def build_session_metrics(self, state: SessionState) -> Dict[str, Any]:
        turn_metrics = [
            (turn.debug_trace.get("graphrag", {}) or {})
            for turn in state.transcript
            if isinstance(turn.debug_trace, dict) and turn.debug_trace.get("graphrag")
        ]
        if not turn_metrics:
            return {
                "schema_version": "graphrag_session_monitor_v1",
                "turn_count": 0,
                "uses_graphrag_style_path": False,
            }

        retrievals = [item.get("retrieval", {}) or {} for item in turn_metrics]
        graphs = [item.get("graph_context", {}) or {} for item in turn_metrics]
        decisions = [item.get("decision_influence", {}) or {} for item in turn_metrics]
        flags = [item.get("quality_flags", {}) or {} for item in turn_metrics]

        action_counts: Dict[str, int] = {}
        focus_counts: Dict[str, int] = {}
        for decision in decisions:
            action = str(decision.get("preferred_action", "") or "")
            focus = str(decision.get("preferred_focus", "") or "")
            if action:
                action_counts[action] = action_counts.get(action, 0) + 1
            if focus:
                focus_counts[focus] = focus_counts.get(focus, 0) + 1

        return {
            "schema_version": "graphrag_session_monitor_v1",
            "turn_count": len(turn_metrics),
            "uses_graphrag_style_path": True,
            "semantic_retrieval_turn_rate": _average(
                1.0 if item.get("retrieved_count", 0) else 0.0 for item in retrievals
            ),
            "average_top_similarity": round(_average(
                float(item.get("top_score", 0.0) or 0.0) for item in retrievals
            ), 4),
            "focus_event_retrieval_hit_rate": round(_average(
                float(item.get("focus_event_retrieved", 0.0) or 0.0) for item in retrievals
            ), 4),
            "average_graph_coverage_delta": round(_average(
                float(item.get("coverage_delta", 0.0) or 0.0) for item in graphs
            ), 4),
            "average_active_event_count": round(_average(
                float(item.get("active_event_count", 0.0) or 0.0) for item in graphs
            ), 4),
            "decision_action_counts": action_counts,
            "decision_focus_counts": focus_counts,
            "average_action_margin": round(_average(
                float(item.get("action_score_margin", 0.0) or 0.0) for item in decisions
            ), 4),
            "stale_or_empty_context_turns": sum(
                1 for item in flags if item.get("empty_graph_context") or item.get("retrieval_empty_with_index")
            ),
        }

    def _build_retrieval_metrics(
        self,
        *,
        state: SessionState,
        focus_event_payload: Optional[Dict[str, Any]],
        event_vector_store: Optional[Any],
        retrieval_query: str,
    ) -> Dict[str, Any]:
        index_size = int(getattr(event_vector_store, "size", 0) or 0) if event_vector_store else 0
        retrieved: List[tuple[str, float]] = []
        error = ""
        if event_vector_store and index_size > 0 and retrieval_query:
            try:
                retrieved = list(event_vector_store.search(retrieval_query, top_k=5) or [])
            except Exception as exc:  # retrieval should never break planning
                error = exc.__class__.__name__

        retrieved_ids = [str(item[0]) for item in retrieved]
        active_ids = set(state.memory_capsule.active_event_ids if state.memory_capsule else [])
        focus_event_id = str((focus_event_payload or {}).get("event_id", "") or "")
        overlap = active_ids.intersection(retrieved_ids)

        return {
            "vector_index_size": index_size,
            "query_chars": len(retrieval_query or ""),
            "retrieved_count": len(retrieved),
            "retrieved_event_ids": retrieved_ids,
            "top_score": round(float(retrieved[0][1]), 4) if retrieved else 0.0,
            "active_event_hit_rate": round(len(overlap) / max(1, len(active_ids)), 4),
            "focus_event_retrieved": 1.0 if focus_event_id and focus_event_id in retrieved_ids else 0.0,
            "retrieval_error": error,
        }

    def _build_graph_context_metrics(
        self,
        *,
        state: SessionState,
        pre_graph_summary: GraphSummary,
        post_graph_summary: GraphSummary,
        focus_event_payload: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        missing_slots = (focus_event_payload or {}).get("missing_slots", [])
        if not isinstance(missing_slots, list):
            missing_slots = []
        pending_count = len(post_graph_summary.pending_themes)
        mentioned_count = len(post_graph_summary.mentioned_themes)
        exhausted_count = len(post_graph_summary.exhausted_themes)
        total_theme_count = len(post_graph_summary.all_themes)

        return {
            "coverage_before": round(pre_graph_summary.overall_coverage, 4),
            "coverage_after": round(post_graph_summary.overall_coverage, 4),
            "coverage_delta": round(post_graph_summary.overall_coverage - pre_graph_summary.overall_coverage, 4),
            "active_event_count": len(post_graph_summary.active_event_ids),
            "active_people_count": len(state.memory_capsule.active_people_ids if state.memory_capsule else []),
            "focus_event_id": (focus_event_payload or {}).get("event_id"),
            "focus_missing_slot_count": len(missing_slots),
            "theme_status_counts": {
                "pending": pending_count,
                "mentioned": mentioned_count,
                "exhausted": exhausted_count,
            },
            "undercovered_theme_rate": round((pending_count + mentioned_count) / max(1, total_theme_count), 4),
        }

    def _build_grounding_metrics(self, state: SessionState) -> Dict[str, Any]:
        events = list(state.canonical_events.values())
        if not events:
            return {
                "canonical_event_count": 0,
                "source_linkage_rate": 0.0,
                "average_event_completeness": 0.0,
                "people_linkage_rate": 0.0,
            }
        return {
            "canonical_event_count": len(events),
            "source_linkage_rate": round(
                sum(1 for event in events if event.source_turn_ids) / len(events),
                4,
            ),
            "average_event_completeness": round(
                _average(float(event.completeness_score or 0.0) for event in events),
                4,
            ),
            "people_linkage_rate": round(
                sum(1 for event in events if event.people_ids or event.people_names) / len(events),
                4,
            ),
        }

    def _build_decision_influence_metrics(self, generation_hints: Dict[str, Any]) -> Dict[str, Any]:
        action_scores = ((generation_hints.get("decision_scores", {}) or {}).get("action", {}) or {})
        focus_scores = ((generation_hints.get("decision_scores", {}) or {}).get("focus", {}) or {})
        slot_rankings = list(generation_hints.get("slot_rankings", []) or [])
        theme_rankings = list(generation_hints.get("theme_rankings", []) or [])

        return {
            "preferred_action": generation_hints.get("preferred_action"),
            "preferred_focus": generation_hints.get("preferred_focus"),
            "action_score_margin": self._score_margin(action_scores),
            "focus_score_margin": self._score_margin(focus_scores),
            "top_slot": slot_rankings[0].get("slot") if slot_rankings and isinstance(slot_rankings[0], dict) else None,
            "top_theme_id": theme_rankings[0].get("theme_id") if theme_rankings and isinstance(theme_rankings[0], dict) else None,
            "top_theme_score": theme_rankings[0].get("score") if theme_rankings and isinstance(theme_rankings[0], dict) else 0.0,
            "graph_recommended_theme_used": bool(generation_hints.get("recommended_theme_id")),
        }

    def _build_quality_flags(
        self,
        *,
        turn_record: TurnRecord,
        retrieval: Dict[str, Any],
        graph_context: Dict[str, Any],
        decision_influence: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "retrieval_empty_with_index": (
                retrieval.get("vector_index_size", 0) > 0
                and retrieval.get("retrieved_count", 0) == 0
                and not retrieval.get("retrieval_error")
            ),
            "retrieval_error": bool(retrieval.get("retrieval_error")),
            "empty_graph_context": (
                graph_context.get("active_event_count", 0) == 0
                and graph_context.get("focus_event_id") in (None, "")
            ),
            "low_decision_margin": (
                _clamp01(float(decision_influence.get("action_score_margin", 0.0) or 0.0)) < 0.05
            ),
            "answer_without_grounded_event": (
                len((turn_record.interviewee_answer or "").strip()) >= 40
                and graph_context.get("active_event_count", 0) == 0
            ),
        }

    def _score_margin(self, scores: Dict[str, Any]) -> float:
        numeric_scores = sorted(
            [float(value) for value in scores.values() if isinstance(value, (int, float))],
            reverse=True,
        )
        if len(numeric_scores) < 2:
            return 0.0
        return round(numeric_scores[0] - numeric_scores[1], 4)
