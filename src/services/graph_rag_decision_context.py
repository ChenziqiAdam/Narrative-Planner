"""GraphRAGDecisionContext — lightweight decision input built from graph + transcript.

Replaces the combined use of MemoryCapsule + GraphSummary + focus_event_payload
+ generation_hints in the GraphRAG pipeline.  Built directly from Neo4j Cypher
queries and transcript data, bypassing the slot-based legacy code path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.services.graph_coverage import GraphCoverageCalculator
from src.services.narrative_richness import NarrativeRichnessScorer
from src.state.models import EmotionalState


def estimate_valence(text: str) -> float:
    positive_keywords = ["开心", "高兴", "幸福", "自豪", "喜欢", "温暖", "快乐"]
    negative_keywords = ["难过", "伤心", "遗憾", "辛苦", "困难", "痛苦", "压抑"]
    pos_hits = sum(1 for word in positive_keywords if word in text)
    neg_hits = sum(1 for word in negative_keywords if word in text)
    if pos_hits == neg_hits == 0:
        return 0.0
    return max(min((pos_hits - neg_hits) / 3.0, 1.0), -1.0)


def infer_emotional_state_from_transcript(
    transcript: list,
    answer: str = "",
) -> EmotionalState:
    if not transcript and not answer:
        return EmotionalState(confidence=0.4, evidence=["No completed turns yet."])
    text = answer
    if transcript:
        text = text or transcript[-1].interviewee_answer or ""
    valence = estimate_valence(text)
    emotional_energy = min(max(len(text) / 180.0, 0.2), 1.0)
    cognitive_energy = min(max(len(text) / 140.0, 0.25), 1.0)
    evidence: List[str] = []
    if transcript:
        latest_turn = transcript[-1]
        if getattr(latest_turn, "extraction_result", None):
            for candidate in latest_turn.extraction_result.graph_delta.fragment_candidates:
                if hasattr(candidate, "rich_text") and candidate.rich_text:
                    evidence.append(candidate.rich_text[:80])
    if not evidence:
        evidence.append(text[:80] if text else "Short reply.")
    return EmotionalState(
        emotional_energy=round(emotional_energy, 3),
        cognitive_energy=round(cognitive_energy, 3),
        valence=round(valence, 3),
        confidence=0.65,
        evidence=evidence[:4],
    )

logger = logging.getLogger(__name__)


@dataclass
class GraphRAGDecisionContext:
    """All information needed by InterviewerAgent in GraphRAG mode."""

    # ── Coverage (from Cypher queries) ──
    overall_coverage: float = 0.0
    coverage_by_theme: Dict[str, float] = field(default_factory=dict)
    current_focus_theme_id: Optional[str] = None
    undercovered_themes: List[str] = field(default_factory=list)
    exhausted_themes: List[str] = field(default_factory=list)

    # ── Focus narrative (from narrative_fragments) ──
    focus_rich_text: Optional[str] = None
    focus_entity_id: Optional[str] = None
    connected_people: List[str] = field(default_factory=list)
    connected_locations: List[str] = field(default_factory=list)
    emotional_thread: Optional[str] = None
    explorable_angles: List[str] = field(default_factory=list)

    # ── Context (from transcript inline) ──
    emotional_state: Optional[EmotionalState] = None
    do_not_repeat: List[str] = field(default_factory=list)
    low_info_streak: int = 0

    # ── Retrieval result (from HybridRetriever) ──
    graph_rag_context: Optional[str] = None

    # ── Cross-session ──
    cross_session_summary: Optional[str] = None
    cross_session_open_loops: List[str] = field(default_factory=list)


class GraphRAGDecisionContextBuilder:
    """Builds a ``GraphRAGDecisionContext`` from graph + transcript."""

    def __init__(
        self,
        neo4j_manager: Optional[Any] = None,
        entity_vector_store: Optional[Any] = None,
    ) -> None:
        self._neo4j = neo4j_manager
        self._vector_store = entity_vector_store
        self._coverage_calc = GraphCoverageCalculator()
        self._richness_scorer = NarrativeRichnessScorer()

    def build(
        self,
        state: Any,
        graph_extraction: Optional[Any] = None,
        graph_rag_context: Optional[str] = None,
        bridge_result: Optional[Any] = None,
    ) -> GraphRAGDecisionContext:
        ctx = GraphRAGDecisionContext()

        # 1. Theme coverage from Cypher
        ctx.coverage_by_theme = self._compute_coverage()
        if not ctx.coverage_by_theme:
            theme_state = getattr(state, "theme_state", {}) or {}
            ctx.coverage_by_theme = {theme_id: 0.0 for theme_id in theme_state}
        if ctx.coverage_by_theme:
            ctx.overall_coverage = round(
                sum(ctx.coverage_by_theme.values()) / len(ctx.coverage_by_theme), 4
            )
        ctx.undercovered_themes = [
            tid for tid, cov in ctx.coverage_by_theme.items() if cov < 0.3
        ]

        # 2. Focus theme from state
        ctx.current_focus_theme_id = getattr(state, "current_focus_theme_id", None)

        # 3. Focus narrative from narrative_fragments
        self._populate_focus(ctx, state, graph_extraction)

        # 4. Graph gaps → explorable angles
        ctx.explorable_angles = self._compute_graph_gaps(state)

        # 5. Emotional state from transcript
        transcript = list(getattr(state, "transcript", []))
        ctx.emotional_state = infer_emotional_state_from_transcript(transcript)

        # 6. Do not repeat
        ctx.do_not_repeat = [
            t.interviewer_question
            for t in transcript[-3:]
            if getattr(t, "interviewer_question", None)
        ]

        # 7. Low info streak
        ctx.low_info_streak = self._count_low_info_streak(transcript)

        # 8. Retrieval context
        ctx.graph_rag_context = graph_rag_context

        # 9. Cross-session
        if bridge_result and getattr(bridge_result, "has_history", False):
            ctx.cross_session_summary = bridge_result.summary_text
            ctx.cross_session_open_loops = bridge_result.open_loops

        return ctx

    # ── Internal helpers ──

    def _compute_coverage(self) -> Dict[str, float]:
        if self._neo4j is None:
            return {}
        try:
            return self._coverage_calc.compute_theme_coverage(self._neo4j)
        except Exception:
            logger.debug("Theme coverage query failed", exc_info=True)
            return {}

    def _populate_focus(
        self,
        ctx: GraphRAGDecisionContext,
        state: Any,
        graph_extraction: Optional[Any],
    ) -> None:
        """Set focus narrative from the latest narrative fragment or extraction."""
        # Try narrative_fragments first
        fragments = getattr(state, "narrative_fragments", {})
        if fragments:
            latest = list(fragments.values())[-1]
            ctx.focus_rich_text = latest.rich_text
            ctx.focus_entity_id = latest.fragment_id
            props = getattr(latest, "properties", {})
            ctx.connected_people = props.get("people", [])
            ctx.connected_locations = [props.get("location", "")] if props.get("location") else []
            ctx.emotional_thread = props.get("emotional_tone")
            return

        # Fallback: use graph_extraction if available
        if graph_extraction and graph_extraction.event_entities:
            event = graph_extraction.event_entities[0]
            ctx.focus_rich_text = event.description
            ctx.focus_entity_id = None
            ctx.connected_people = event.properties.get("people", [])
            ctx.connected_locations = [event.properties.get("location", "")] if event.properties.get("location") else []
            ctx.emotional_thread = event.properties.get("emotional_tone")

        # Try to get neighbors from Neo4j for richer context
        if ctx.focus_entity_id and self._neo4j:
            self._enrich_focus_from_graph(ctx)

    def _enrich_focus_from_graph(self, ctx: GraphRAGDecisionContext) -> None:
        """Query Neo4j for 1-hop neighbors of the focus entity."""
        try:
            neighbors = self._neo4j.get_entity_neighbors(ctx.focus_entity_id)
            for nb in neighbors:
                ntype = nb.get("type", "")
                name = nb.get("name", "")
                if not name:
                    continue
                if ntype == "Person" and name not in ctx.connected_people:
                    ctx.connected_people.append(name)
                elif ntype == "Location" and name not in ctx.connected_locations:
                    ctx.connected_locations.append(name)
                elif ntype == "Emotion" and not ctx.emotional_thread:
                    ctx.emotional_thread = name
        except Exception:
            logger.debug("Focus enrichment query failed", exc_info=True)

    def _compute_graph_gaps(self, state: Any) -> List[str]:
        """Find events in the graph that lack Person/Location/Emotion connections."""
        if self._neo4j is None:
            return []
        elder_id = self._get_elder_id(state)
        if not elder_id:
            return []
        try:
            gaps = self._neo4j.get_graph_gaps(elder_id)
            angles: List[str] = []
            for gap in gaps[:8]:
                name = gap.get("name", "")
                desc = gap.get("description", "")[:40]
                missing = []
                if not gap.get("person_count"):
                    missing.append("人物")
                if not gap.get("location_count"):
                    missing.append("地点")
                if not gap.get("emotion_count"):
                    missing.append("情感")
                suffix = f"（缺少{'、'.join(missing)}）" if missing else ""
                angles.append(f"「{name}」{desc}{suffix}")
            return angles
        except Exception:
            logger.debug("Graph gaps query failed", exc_info=True)
            return []

    @staticmethod
    def _get_elder_id(state: Any) -> str:
        profile = getattr(state, "elder_profile", None)
        if profile is None:
            return ""
        name = getattr(profile, "name", "") or ""
        birth_year = getattr(profile, "birth_year", None) or ""
        return f"{name}_{birth_year}" if name else ""

    @staticmethod
    def _count_low_info_streak(transcript: list, max_window: int = 3) -> int:
        streak = 0
        for turn in reversed(transcript[-max_window:]):
            answer = getattr(turn, "interviewee_answer", "") or ""
            if len(answer) < 30:
                streak += 1
            else:
                break
        return streak
