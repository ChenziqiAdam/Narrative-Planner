"""Graph-based coverage calculator — replaces slot-based coverage.

Uses Neo4j Cypher queries and narrative richness scores to compute
theme-level, entity-level, and overall coverage.  Gracefully returns
zeros when Neo4j is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.services.narrative_richness import NarrativeRichnessScorer

logger = logging.getLogger(__name__)


class GraphCoverageCalculator:
    """Replaces slot-based coverage with graph-based coverage.

    Designed as a drop-in replacement that the existing
    ``CoverageCalculator.build_graph_summary`` can delegate to.
    """

    def __init__(self, scorer: Optional[NarrativeRichnessScorer] = None) -> None:
        self._scorer = scorer or NarrativeRichnessScorer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_theme_coverage(self, neo4j_manager) -> Dict[str, float]:
        """Per-theme coverage weighted by narrative richness.

        Returns:
            ``{theme_id: coverage_float}`` where coverage is the average
            richness of events under that theme (0.0 if no events).
        """
        if neo4j_manager is None:
            return {}
        try:
            rows = neo4j_manager.driver.execute_query(
                """
                MATCH (t:Topic)
                OPTIONAL MATCH (t)-[:INCLUDES]->(e:Event)
                RETURN t.id AS theme_id, count(e) AS event_count,
                       collect(e) AS events
                """
            )
        except Exception:
            logger.debug("Theme coverage query failed", exc_info=True)
            return {}

        result: Dict[str, float] = {}
        for row in rows:
            theme_id = row["theme_id"]
            event_count = row.get("event_count", 0)
            if not event_count:
                result[theme_id] = 0.0
                continue
            # Score each event via richness scorer.
            events = row.get("events", [])
            scores = []
            for event_node in events:
                props = dict(event_node)
                scores.append(
                    self._scorer.compute_fragment_richness(props, neo4j_manager)
                )
            result[theme_id] = round(sum(scores) / len(scores), 4) if scores else 0.0
        return result

    def compute_entity_coverage(self, neo4j_manager) -> Dict[str, float]:
        """What fraction of themes have events with Person + Location + Emotion.

        For each theme that has at least one event, check whether its events
        connect to Person, Location, and Emotion nodes.  A theme is "entity
        complete" when it has all three entity types.

        Returns:
            ``{theme_id: entity_completeness}`` in [0, 1].
        """
        if neo4j_manager is None:
            return {}
        try:
            rows = neo4j_manager.driver.execute_query(
                """
                MATCH (t:Topic)-[:INCLUDES]->(e:Event)
                OPTIONAL MATCH (e)<-[:PARTICIPATES_IN]-(p:Person)
                OPTIONAL MATCH (e)-[:LOCATED_AT]->(l:Location)
                OPTIONAL MATCH (e)-[:TRIGGERS]->(em:Emotion)
                RETURN t.id AS theme_id,
                       count(DISTINCT p) AS person_count,
                       count(DISTINCT l) AS location_count,
                       count(DISTINCT em) AS emotion_count
                """
            )
        except Exception:
            logger.debug("Entity coverage query failed", exc_info=True)
            return {}

        result: Dict[str, float] = {}
        for row in rows:
            theme_id = row["theme_id"]
            has_person = row["person_count"] > 0
            has_location = row["location_count"] > 0
            has_emotion = row["emotion_count"] > 0
            completeness = (
                int(has_person) + int(has_location) + int(has_emotion)
            ) / 3.0
            result[theme_id] = round(completeness, 4)
        return result

    def build_graph_summary(
        self, state: Any, graph_manager: Any
    ) -> Dict[str, Any]:
        """Build a coverage summary compatible with GraphSummary interface.

        This method can be called by ``CoverageCalculator.build_graph_summary``
        as a drop-in replacement for the slot-based logic.

        Args:
            state: SessionState (used for theme list and focus).
            graph_manager: Neo4jGraphAdapter or compatible object that
                provides ``get_neo4j_manager()`` and in-memory theme dicts.

        Returns:
            Dict with overall_coverage, theme_coverage, entity_coverage.
        """
        neo4j_mgr = self._get_neo4j_manager(graph_manager)
        if neo4j_mgr is None:
            return self._empty_summary()

        theme_coverage = self.compute_theme_coverage(neo4j_mgr)
        entity_coverage = self.compute_entity_coverage(neo4j_mgr)

        # Overall = average of theme coverages.
        overall = (
            round(sum(theme_coverage.values()) / len(theme_coverage), 4)
            if theme_coverage
            else 0.0
        )

        return {
            "overall_coverage": overall,
            "theme_coverage": theme_coverage,
            "entity_coverage": entity_coverage,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_neo4j_manager(graph_manager: Any) -> Optional[Any]:
        """Extract a usable Neo4jGraphManager from the graph adapter."""
        if graph_manager is None:
            return None
        # Neo4jGraphAdapter exposes get_neo4j_manager().
        getter = getattr(graph_manager, "get_neo4j_manager", None)
        if getter:
            return getter()
        # Direct Neo4jGraphManager.
        if hasattr(graph_manager, "driver"):
            return graph_manager
        return None

    @staticmethod
    def _empty_summary() -> Dict[str, Any]:
        """Return a zero-valued summary when Neo4j is unavailable."""
        return {
            "overall_coverage": 0.0,
            "theme_coverage": {},
            "entity_coverage": {},
        }
