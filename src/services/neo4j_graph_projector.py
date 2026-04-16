"""Neo4jGraphProjector — drop-in replacement for GraphProjector.

Maintains the exact same public interface as ``GraphProjector`` so that
``SessionOrchestrator`` can swap it in without any code changes.  The key
difference is that it also:

1. Persists extracted entities (Person, Location, Emotion) to Neo4j.
2. Syncs updated theme slots_filled to Neo4j Topic nodes.
3. Refreshes the CoverageCache from Neo4j Cypher aggregation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.state import SessionState
from src.services.graph_projector import GraphProjector

logger = logging.getLogger(__name__)


class Neo4jGraphProjector(GraphProjector):
    """Extends GraphProjector with Neo4j persistence and cache refresh."""

    def __init__(self):
        super().__init__()

    def apply_projection(
        self,
        state: SessionState,
        graph_manager: Any,  # Neo4jGraphAdapter or GraphManager
        event_ids: List[str],
    ) -> Dict[str, Any]:
        """Apply projection, persist extras to Neo4j, then refresh cache."""
        result = super().apply_projection(state, graph_manager, event_ids)

        # Only run Neo4j-specific logic if the adapter supports it.
        from src.services.neo4j_graph_adapter import Neo4jGraphAdapter
        if isinstance(graph_manager, Neo4jGraphAdapter):
            neo4j_mgr = graph_manager.get_neo4j_manager()
            if neo4j_mgr:
                # 1. Persist Person, Location, Emotion nodes.
                self._persist_extra_entities(state, event_ids, neo4j_mgr)

                # 2. Sync updated theme slots to Neo4j.
                updated_themes = result.get("updated_themes", [])
                for theme_id in updated_themes:
                    theme = graph_manager.theme_nodes.get(theme_id)
                    if theme:
                        graph_manager._persist_theme_update(theme_id, theme)

                # 3. Refresh CoverageCache from Neo4j Cypher aggregation.
                graph_manager._refresh_coverage_cache()

        return result

    def _persist_extra_entities(
        self,
        state: SessionState,
        event_ids: List[str],
        neo4j_mgr: Any,
    ) -> None:
        """Extract and persist Person, Location, and Emotion nodes to Neo4j."""
        from src.storage.neo4j.models import PersonNodeNeo4j, LocationNodeNeo4j, EmotionNodeNeo4j

        for event_id in event_ids:
            event = state.canonical_events.get(event_id)
            if not event:
                continue

            # Persist Person nodes.
            for person_name in (event.people_names or []):
                person_id = f"person_{hash(person_name) & 0xFFFFFFFF:08x}"
                person = PersonNodeNeo4j(
                    id=person_id,
                    name=person_name,
                    description=f"Mentioned in event: {event.summary or event.title}",
                )
                try:
                    neo4j_mgr.upsert_person(person, event_id)
                except Exception:
                    logger.debug("Failed to persist person %s", person_name, exc_info=True)

            # Persist Location node.
            if event.location:
                loc_id = f"loc_{hash(event.location) & 0xFFFFFFFF:08x}"
                location = LocationNodeNeo4j(
                    id=loc_id,
                    name=event.location,
                    description=f"Location for event: {event.summary or event.title}",
                )
                try:
                    neo4j_mgr.upsert_location(location, event_id)
                except Exception:
                    logger.debug("Failed to persist location %s", event.location, exc_info=True)

            # Persist Emotion node.
            feeling_text = event.feeling or ""
            reflection_text = event.reflection or ""
            if feeling_text or reflection_text:
                emotion_text = f"{feeling_text} {reflection_text}".strip()
                emotion_id = f"emot_{hash(emotion_text) & 0xFFFFFFFF:08x}"
                emotion = EmotionNodeNeo4j(
                    id=emotion_id,
                    name=emotion_text[:50],
                    description=emotion_text,
                )
                try:
                    neo4j_mgr.upsert_emotion(emotion, event_id)
                except Exception:
                    logger.debug("Failed to persist emotion", exc_info=True)
