"""Narrative richness scorer — replaces slot-based completeness_score.

Scores narrative fragments on 4 continuous dimensions:
1. connectivity   (0-1) — relationships in the knowledge graph
2. detail_depth   (0-1) — variety of entity types connected
3. emotional_richness (0-1) — presence of emotional content
4. temporal_grounding (0-1) — temporal specificity

Final score: 0.3*connectivity + 0.25*detail + 0.25*emotional + 0.2*temporal
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Weights for the four dimensions.
_W_CONNECTIVITY = 0.30
_W_DETAIL = 0.25
_W_EMOTIONAL = 0.25
_W_TEMPORAL = 0.20

# Regex for recognising a year-like token (e.g. 1992, 2020).
_YEAR_RE = re.compile(r"\b(19[4-9]\d|20[0-2]\d)\b")


class NarrativeRichnessScorer:
    """Score narrative fragments on 4 dimensions instead of slot fill rate."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_fragment_richness(
        self, fragment_properties: Dict[str, Any], neo4j_manager=None
    ) -> float:
        """Score a single fragment on 4 dimensions.

        Args:
            fragment_properties: The ``properties`` dict from a NarrativeFragment
                or an EventNode.  May contain time_anchor, location, people_names,
                emotional_tone, feeling, etc.
            neo4j_manager: Optional Neo4jGraphManager for graph-based connectivity.

        Returns:
            Weighted richness score in [0, 1].
        """
        connectivity = self._score_connectivity(fragment_properties, neo4j_manager)
        detail = self._score_detail_depth(fragment_properties)
        emotional = self._score_emotional_richness(fragment_properties)
        temporal = self._score_temporal_grounding(fragment_properties)

        score = (
            _W_CONNECTIVITY * connectivity
            + _W_DETAIL * detail
            + _W_EMOTIONAL * emotional
            + _W_TEMPORAL * temporal
        )
        return round(score, 4)

    def compute_theme_richness(
        self, theme_id: str, neo4j_manager
    ) -> float:
        """Average richness of all events under a theme.

        Returns 0.0 if Neo4j is unavailable or no events exist.
        """
        events = self._query_theme_events(theme_id, neo4j_manager)
        if not events:
            return 0.0

        scores: List[float] = []
        for event_props in events:
            scores.append(
                self.compute_fragment_richness(event_props, neo4j_manager)
            )
        return round(sum(scores) / len(scores), 4)

    def compute_overall_richness(self, neo4j_manager) -> float:
        """Global narrative quality score across all themes.

        Returns 0.0 if Neo4j is unavailable.
        """
        if neo4j_manager is None:
            return 0.0
        try:
            rows = neo4j_manager.driver.execute_query(
                "MATCH (t:Topic) RETURN t.id AS theme_id"
            )
            if not rows:
                return 0.0
            theme_ids = [r["theme_id"] for r in rows]
            scores = [
                self.compute_theme_richness(tid, neo4j_manager)
                for tid in theme_ids
            ]
            return round(sum(scores) / len(scores), 4) if scores else 0.0
        except Exception:
            logger.debug("Overall richness computation failed", exc_info=True)
            return 0.0

    # ------------------------------------------------------------------
    # Dimension scorers
    # ------------------------------------------------------------------

    def _score_connectivity(
        self, props: Dict[str, Any], neo4j_manager
    ) -> float:
        """How many relationships exist in the graph.

        Prefers pre-fetched ``__rel_count`` from batch queries.
        Falls back to Neo4j lookup, then to property estimation.
        """
        # Use pre-fetched rel_count if available (avoids extra query).
        rel_count = props.get("__rel_count")
        if rel_count is not None:
            return min(rel_count / 3.0, 1.0)

        # Try graph-based scoring.
        if neo4j_manager is not None:
            try:
                fragment_id = props.get("fragment_id") or props.get("event_id") or props.get("id")
                if fragment_id:
                    return self._graph_connectivity(fragment_id, neo4j_manager)
            except Exception:
                logger.debug("Graph connectivity lookup failed", exc_info=True)

        # Fallback: estimate from properties.
        score = 0.0
        people = props.get("people_names") or props.get("people_involved") or []
        if people and len(people) > 0:
            score += 0.3
        location = props.get("location") or props.get("location_name")
        if location:
            score += 0.3
        linked = props.get("related_events") or props.get("linked_event_ids") or []
        if linked and len(linked) > 0:
            score += 0.4
        return min(score, 1.0)

    def _score_detail_depth(self, props: Dict[str, Any]) -> float:
        """Count unique entity types mentioned in properties.

        time + location + people = 1.0, any 2 = 0.6, any 1 = 0.3.
        """
        has_time = bool(props.get("time_anchor") or props.get("time"))
        has_location = bool(props.get("location") or props.get("location_name"))
        people = props.get("people_names") or props.get("people_involved")
        has_people = bool(people and len(people) > 0)

        count = int(has_time) + int(has_location) + int(has_people)
        if count >= 3:
            return 1.0
        if count == 2:
            return 0.6
        if count == 1:
            return 0.3
        return 0.0

    def _score_emotional_richness(self, props: Dict[str, Any]) -> float:
        """Whether emotional content exists.

        Non-trivial content (> 5 chars): 1.0, exists but trivial: 0.5, none: 0.0.
        """
        tone = props.get("emotional_tone") or props.get("emotion") or ""
        feeling = props.get("feeling") or props.get("reflection") or ""
        score_raw = props.get("emotional_score")

        # Explicit emotional score from EventNode.
        if score_raw is not None:
            try:
                val = abs(float(score_raw))
                if val > 0.3:
                    return 1.0
                if val > 0.0:
                    return 0.5
            except (TypeError, ValueError):
                pass

        # Text-based check.
        combined = f"{tone} {feeling}".strip()
        if len(combined) > 5:
            return 1.0
        if len(combined) > 0:
            return 0.5
        return 0.0

    def _score_temporal_grounding(self, props: Dict[str, Any]) -> float:
        """Whether time_anchor exists and is specific.

        Has year: 1.0, has fuzzy time: 0.5, none: 0.0.
        """
        time_anchor = props.get("time_anchor") or props.get("time") or ""
        if not time_anchor:
            return 0.0
        if _YEAR_RE.search(str(time_anchor)):
            return 1.0
        return 0.5

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _graph_connectivity(
        self, node_id: str, neo4j_manager
    ) -> float:
        """Count actual relationships from Neo4j, normalise to [0, 1]."""
        try:
            rows = neo4j_manager.driver.execute_query(
                "MATCH (n {id: $id})-[r]-() RETURN count(r) AS rel_count",
                {"id": node_id},
            )
            rel_count = rows[0]["rel_count"] if rows else 0
            # 3+ relationships is considered fully connected.
            return min(rel_count / 3.0, 1.0)
        except Exception:
            return 0.0

    @staticmethod
    def _query_theme_events(
        theme_id: str, neo4j_manager
    ) -> List[Dict[str, Any]]:
        """Return property dicts for all events under a theme."""
        if neo4j_manager is None:
            return []
        try:
            rows = neo4j_manager.driver.execute_query(
                """
                MATCH (t:Topic {id: $theme_id})-[:INCLUDES]->(e:Event)
                RETURN e
                """,
                {"theme_id": theme_id},
            )
            if not rows:
                return []
            return [dict(r["e"]) for r in rows]
        except Exception:
            logger.debug("Theme event query failed for %s", theme_id, exc_info=True)
            return []
