"""Neo4jRelationService — N-hop relationship discovery for the planner.

This service provides *supplementary* intelligence to the deterministic
PlannerDecisionPolicy.  It is only invoked when the policy decides to
switch topics (``preferred_action == 'next_phase'``), at which point it
suggests the most connected next theme and generates a suggested angle
for the next question.

Chain A (deterministic): "what to do"  → continue / next_phase / end
Chain B (this service):  "where to go" → which theme, what angle
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.storage.neo4j.driver import Neo4jGraphDriver
from src.storage.neo4j.manager import Neo4jGraphManager

logger = logging.getLogger(__name__)


class Neo4jRelationService:
    """N-hop query service consumed by PlannerDecisionPolicy."""

    def __init__(self, neo4j_manager: Neo4jGraphManager):
        self._mgr = neo4j_manager

    # ────────────────────────────────────────────────────────
    # Public API — used by PlannerDecisionPolicy
    # ────────────────────────────────────────────────────────

    def query_related_themes(
        self, current_theme_id: str, hop: int = 2
    ) -> List[Dict[str, Any]]:
        """Find themes linked to *current_theme_id* via shared events / people."""
        return self._mgr.get_related_themes(current_theme_id, hop)

    def query_person_overlap(
        self, theme_a: str, theme_b: str
    ) -> List[str]:
        """Return person names that appear in events from both themes."""
        rows = self._mgr.driver.execute_query(
            """
            MATCH (t1:Topic {id: $t1})-[:INCLUDES]->(e1:Event)
                  -[:PARTICIPATES_IN]-(p:Person)
                  <-[:PARTICIPATES_IN]-(e2:Event)
                  <-[:INCLUDES]-(t2:Topic {id: $t2})
            RETURN DISTINCT p.name AS name
            """,
            {"t1": theme_a, "t2": theme_b},
        )
        return [r["name"] for r in (rows or []) if r.get("name")]

    def detect_temporal_gaps(self) -> List[Dict[str, Any]]:
        """Find time ranges that are not covered by any event."""
        rows = self._mgr.driver.execute_query(
            """
            MATCH (e:Event)
            WHERE e.time_anchor IS NOT NULL AND e.time_anchor <> ''
            RETURN e.id AS event_id, e.time_anchor AS time_anchor,
                   e.title AS title, e.theme_id AS theme_id
            ORDER BY e.time_anchor
            """
        )
        if not rows:
            return []
        return rows

    def query_unexplored_relations(self) -> List[Dict[str, Any]]:
        """Find people mentioned in only one event (potential for deeper exploration)."""
        rows = self._mgr.driver.execute_query(
            """
            MATCH (p:Person)-[:PARTICIPATES_IN]-(e:Event)
            WITH p, COUNT(e) AS event_count, COLLECT(e.id) AS events
            WHERE event_count = 1
            RETURN p.id AS person_id, p.name AS name, events
            ORDER BY p.name
            LIMIT 20
            """
        )
        return rows or []

    def suggest_next_theme(
        self,
        current_theme_id: str,
        candidate_theme_ids: List[str],
        hop: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Pick the best next theme considering graph relationships.

        Returns ``{"theme_id": ..., "angle": ..., "overlap_persons": [...]}``
        or ``None`` if no relationship-based suggestion can be made.
        """
        related = self.query_related_themes(current_theme_id, hop)
        if not related:
            return None

        # Filter to candidates that are actually related.
        related_ids = {r["id"] for r in related if r.get("id")}
        best_candidates = [tid for tid in candidate_theme_ids if tid in related_ids]

        if not best_candidates:
            return None

        # Pick the first candidate that has graph connections.
        chosen_id = best_candidates[0]

        # Try to generate an angle from person overlap.
        overlap = self.query_person_overlap(current_theme_id, chosen_id)
        angle = ""
        if overlap:
            angle = f"可以聊聊{', '.join(overlap[:2])}在这段经历中的角色"

        return {
            "theme_id": chosen_id,
            "angle": angle,
            "overlap_persons": overlap,
        }

    def detect_patterns(self) -> List[Dict[str, Any]]:
        """Delegate to Neo4jGraphManager.detect_patterns()."""
        return self._mgr.detect_patterns()
