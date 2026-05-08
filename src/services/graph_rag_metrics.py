"""GraphRAG observability helpers.

The metrics here are intentionally deterministic and JSON-serialisable so the
same payload can be used by live debugging, batch experiments, and tests.
"""

from __future__ import annotations

from typing import Any, Dict


def _round_ms(value: float) -> float:
    return round(float(value or 0.0), 1)


def build_extraction_metrics(extraction: Any, latency_ms: float = 0.0) -> Dict[str, Any]:
    entities = list(getattr(extraction, "entities", []) or [])
    relationships = list(getattr(extraction, "relationships", []) or [])
    type_counts: Dict[str, int] = {}
    for entity in entities:
        entity_type = str(getattr(entity, "entity_type", "") or "Unknown")
        type_counts[entity_type] = type_counts.get(entity_type, 0) + 1

    answer_summary = str(getattr(extraction, "narrative_summary", "") or "")
    confidence = float(getattr(extraction, "confidence", 0.0) or 0.0)
    open_loops = list(getattr(extraction, "open_loops", []) or [])
    return {
        "latency_ms": _round_ms(latency_ms),
        "has_content": bool(getattr(extraction, "has_content", False)),
        "entity_count": len(entities),
        "event_count": type_counts.get("Event", 0),
        "person_count": type_counts.get("Person", 0),
        "location_count": type_counts.get("Location", 0),
        "emotion_count": type_counts.get("Emotion", 0),
        "insight_count": type_counts.get("Insight", 0),
        "relationship_count": len(relationships),
        "open_loops_count": len(open_loops),
        "confidence": round(confidence, 4),
        "narrative_summary_length": len(answer_summary),
        "entity_type_counts": type_counts,
        "empty_extraction": not bool(entities or answer_summary or open_loops),
    }


def build_write_metrics(write_result: Any, latency_ms: float = 0.0) -> Dict[str, Any]:
    if write_result is None:
        return {
            "latency_ms": _round_ms(latency_ms),
            "entity_ids_count": 0,
            "new_entity_count": 0,
            "updated_entity_count": 0,
            "deduplicated_count": 0,
            "relationship_count": 0,
            "write_empty": True,
        }

    entity_ids = list(getattr(write_result, "entity_ids", []) or [])
    return {
        "latency_ms": _round_ms(latency_ms),
        "entity_ids_count": len(entity_ids),
        "new_entity_count": int(getattr(write_result, "new_entity_count", 0) or 0),
        "updated_entity_count": int(getattr(write_result, "updated_entity_count", 0) or 0),
        "deduplicated_count": int(getattr(write_result, "deduplicated_count", 0) or 0),
        "relationship_count": int(getattr(write_result, "relationship_count", 0) or 0),
        "write_empty": not bool(entity_ids),
    }


def build_retrieval_metrics(retrieval_result: Any, latency_ms: float | None = None) -> Dict[str, Any]:
    if retrieval_result is None:
        return {
            "latency_ms": _round_ms(latency_ms or 0.0),
            "ranked_entity_count": 0,
            "token_count": 0,
            "context_empty": True,
            "context_length": 0,
            "channel_counts": {},
            "channel_errors": {},
            "top_entities": [],
        }

    trace = dict(getattr(retrieval_result, "trace", {}) or {})
    prompt_text = str(getattr(retrieval_result, "prompt_text", "") or "")
    entities = list(getattr(retrieval_result, "entities", []) or [])
    result_latency = getattr(retrieval_result, "latency_ms", 0.0)
    return {
        "latency_ms": _round_ms(result_latency if latency_ms is None else latency_ms),
        "ranked_entity_count": len(entities),
        "token_count": int(getattr(retrieval_result, "token_count", 0) or 0),
        "context_empty": not bool(prompt_text),
        "context_length": len(prompt_text),
        "channel_counts": trace.get("channel_counts", {}),
        "channel_errors": trace.get("channel_errors", {}),
        "top_entities": trace.get("top_entities", []),
    }


def build_decision_context_metrics(ctx: Any) -> Dict[str, Any]:
    if ctx is None:
        return {}
    coverage = dict(getattr(ctx, "coverage_by_theme", {}) or {})
    undercovered = list(getattr(ctx, "undercovered_themes", []) or [])
    exhausted = list(getattr(ctx, "exhausted_themes", []) or [])
    explorable = list(getattr(ctx, "explorable_angles", []) or [])
    emotional_state = getattr(ctx, "emotional_state", None)
    return {
        "overall_coverage": round(float(getattr(ctx, "overall_coverage", 0.0) or 0.0), 4),
        "theme_count": len(coverage),
        "undercovered_theme_count": len(undercovered),
        "exhausted_theme_count": len(exhausted),
        "current_focus_theme_id": getattr(ctx, "current_focus_theme_id", None),
        "focus_entity_id": getattr(ctx, "focus_entity_id", None),
        "has_focus_rich_text": bool(getattr(ctx, "focus_rich_text", None)),
        "connected_people_count": len(getattr(ctx, "connected_people", []) or []),
        "connected_locations_count": len(getattr(ctx, "connected_locations", []) or []),
        "explorable_angles_count": len(explorable),
        "low_info_streak": int(getattr(ctx, "low_info_streak", 0) or 0),
        "graph_rag_context_empty": not bool(getattr(ctx, "graph_rag_context", None)),
        "emotion_energy": getattr(emotional_state, "emotional_energy", None),
        "cognitive_energy": getattr(emotional_state, "cognitive_energy", None),
        "emotion_valence": getattr(emotional_state, "valence", None),
    }


def build_graph_rag_metrics(
    *,
    extraction: Any,
    write_result: Any,
    planner_retrieval: Any,
    decision_ctx: Any,
    extraction_ms: float,
    write_ms: float,
) -> Dict[str, Any]:
    return {
        "extraction": build_extraction_metrics(extraction, extraction_ms),
        "write": build_write_metrics(write_result, write_ms),
        "planner_retrieval": build_retrieval_metrics(planner_retrieval),
        "decision_context": build_decision_context_metrics(decision_ctx),
    }
