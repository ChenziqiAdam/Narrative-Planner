"""SessionGraphBridge — cross-session memory bridge.

When starting a new interview session for an elder who has previously been
interviewed, this service loads historical graph data from Neo4j so the new
session can build on what was already captured.

Key capabilities:
- Query Neo4j for all entities / events belonging to a given elder_id
- Produce a text summary suitable for injection into the opening prompt
- Retrieve previous open_loops for follow-up questioning
- Pre-populate the EntityVectorStore with historical entity embeddings
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class HistoricalEntity:
    """Lightweight representation of an entity from a previous session."""

    node_id: str
    entity_type: str
    name: str
    description: str
    properties: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    embedding: Optional[List[float]] = None


@dataclass
class SessionBridgeResult:
    """Result returned by ``load_previous_session``."""

    elder_id: str
    has_history: bool = False
    entities: List[HistoricalEntity] = field(default_factory=list)
    summary_text: str = ""
    open_loops: List[str] = field(default_factory=list)
    theme_coverage: Dict[str, float] = field(default_factory=dict)
    entity_count: int = 0
    relationship_count: int = 0


class SessionGraphBridge:
    """Loads historical graph data for cross-session continuity."""

    def __init__(
        self,
        neo4j_manager: Optional[Any] = None,
        entity_vector_store: Optional[Any] = None,
    ) -> None:
        self._neo4j = neo4j_manager
        self._vector_store = entity_vector_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_previous_session(self, elder_id: str) -> SessionBridgeResult:
        """Load all historical data for *elder_id* from Neo4j.

        Returns a ``SessionBridgeResult`` even if no history exists
        (``has_history`` will be ``False``).
        """
        result = SessionBridgeResult(elder_id=elder_id)

        driver = self._get_driver()
        if driver is None:
            logger.warning("No Neo4j driver available — cannot load history")
            return result

        # 1. Load entities
        entities = self._query_entities(driver, elder_id)
        if not entities:
            return result

        result.entities = entities
        result.has_history = True
        result.entity_count = len(entities)

        # 2. Count relationships
        result.relationship_count = self._count_relationships(driver, elder_id)

        # 3. Pre-populate vector store
        self._populate_vector_store(entities)

        # 4. Generate summary text
        result.summary_text = self._generate_summary(entities, result.relationship_count)

        # 5. Extract open loops
        result.open_loops = self._extract_open_loops(entities)

        # 6. Load theme coverage
        result.theme_coverage = self._load_theme_coverage(driver, elder_id)

        logger.info(
            "Loaded history for %s: %d entities, %d relationships, %d open loops",
            elder_id,
            result.entity_count,
            result.relationship_count,
            len(result.open_loops),
        )
        return result

    def get_session_summary(self, elder_id: str) -> str:
        """Convenience: return just the summary text for prompt injection."""
        result = self.load_previous_session(elder_id)
        return result.summary_text

    def get_previous_open_loops(self, elder_id: str) -> List[str]:
        """Convenience: return just the open loops."""
        result = self.load_previous_session(elder_id)
        return result.open_loops

    # ------------------------------------------------------------------
    # Neo4j queries
    # ------------------------------------------------------------------

    def _get_driver(self):
        """Resolve the Neo4j driver from the manager."""
        if self._neo4j is None:
            return None
        if hasattr(self._neo4j, "driver"):
            return self._neo4j.driver
        return None

    @staticmethod
    def _query_entities(driver, elder_id: str) -> List[HistoricalEntity]:
        """Fetch all entity nodes for *elder_id* from Neo4j."""
        rows = driver.execute_query(
            """
            MATCH (n)
            WHERE n.elder_id = $elder_id
              AND n.type IN ['Event', 'Person', 'Location', 'Emotion', 'Insight']
            RETURN n.id AS id, n.type AS type, n.name AS name,
                   n.description AS description, n.session_id AS session_id,
                   n.properties AS props, n.embedding AS embedding,
                   n.open_loops AS open_loops
            ORDER BY n.type, n.name
            """,
            {"elder_id": elder_id},
        )
        if not rows:
            return []

        entities: List[HistoricalEntity] = []
        for row in rows:
            props = row.get("props") or {}
            if isinstance(props, str):
                try:
                    props = json.loads(props)
                except (json.JSONDecodeError, TypeError):
                    props = {}

            emb = row.get("embedding")
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except (json.JSONDecodeError, TypeError):
                    emb = None

            entities.append(HistoricalEntity(
                node_id=row.get("id", ""),
                entity_type=row.get("type", "Entity"),
                name=row.get("name", ""),
                description=row.get("description", ""),
                properties=props,
                session_id=row.get("session_id", ""),
                embedding=emb,
            ))
        return entities

    @staticmethod
    def _count_relationships(driver, elder_id: str) -> int:
        """Count relationships between entities of the given elder."""
        rows = driver.execute_query(
            """
            MATCH (a)-[r]-(b)
            WHERE a.elder_id = $elder_id AND b.elder_id = $elder_id
            RETURN COUNT(DISTINCT r) AS cnt
            """,
            {"elder_id": elder_id},
        )
        if rows:
            return rows[0].get("cnt", 0) or 0
        return 0

    @staticmethod
    def _load_theme_coverage(driver, elder_id: str) -> Dict[str, float]:
        """Load per-theme coverage for the elder's events."""
        rows = driver.execute_query(
            """
            MATCH (t:Topic)-[:INCLUDES]->(e:Event)
            WHERE e.elder_id = $elder_id
            RETURN t.id AS theme_id, t.domain AS domain,
                   COUNT(e) AS event_count
            """,
            {"elder_id": elder_id},
        )
        if not rows:
            return {}
        coverage: Dict[str, float] = {}
        for row in rows:
            theme_id = row.get("theme_id", "")
            count = row.get("event_count", 0) or 0
            # Normalize: 3+ events = fully covered for a theme
            coverage[theme_id] = min(count / 3.0, 1.0)
        return coverage

    # ------------------------------------------------------------------
    # Vector store population
    # ------------------------------------------------------------------

    def _populate_vector_store(self, entities: List[HistoricalEntity]) -> None:
        """Load historical entity embeddings into the in-memory vector store."""
        if self._vector_store is None:
            return

        loaded = 0
        for entity in entities:
            if entity.embedding is None:
                # Re-encode from text if no stored embedding
                try:
                    from src.services.embedding_service import encode_single
                    entity.embedding = encode_single(
                        f"{entity.name}. {entity.description}"
                    )
                except Exception:
                    logger.debug("Cannot encode entity %s, skipping", entity.name)
                    continue

            self._vector_store.add(
                entity_id=entity.node_id,
                entity_type=entity.entity_type,
                text=f"{entity.name}. {entity.description}",
                embedding=entity.embedding,
            )
            loaded += 1

        if loaded:
            logger.info("Pre-populated vector store with %d historical entities", loaded)

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_summary(entities: List[HistoricalEntity], rel_count: int) -> str:
        """Generate a human-readable summary of previous session data.

        This text is injected into the opening prompt so the interviewer
        knows what has already been covered.
        """
        if not entities:
            return ""

        # Group by type
        by_type: Dict[str, List[HistoricalEntity]] = {}
        for e in entities:
            by_type.setdefault(e.entity_type, []).append(e)

        type_labels = {
            "Event": "事件",
            "Person": "人物",
            "Location": "地点",
            "Emotion": "情感",
            "Insight": "人生感悟",
        }

        lines = [f"该老人此前已有访谈记录，共记录了 {len(entities)} 个实体和 {rel_count} 条关联关系。\n"]

        # Events section
        events = by_type.get("Event", [])
        if events:
            lines.append("## 已记录的主要事件")
            for ev in events[:8]:  # Cap to avoid overwhelming the prompt
                time_anchor = ev.properties.get("time_anchor", "")
                loc = ev.properties.get("location", "")
                detail = f"（{time_anchor}" + (f"，{loc}" if loc else "") + "）" if time_anchor or loc else ""
                lines.append(f"- {ev.name}{detail}: {ev.description[:80]}")
            if len(events) > 8:
                lines.append(f"- ...及其他 {len(events) - 8} 个事件")

        # People section
        people = by_type.get("Person", [])
        if people:
            lines.append("\n## 已提及的人物")
            for p in people[:10]:
                role = p.properties.get("relationship_to_elder", p.properties.get("role", ""))
                suffix = f"（{role}）" if role else ""
                lines.append(f"- {p.name}{suffix}")

        # Locations
        locations = by_type.get("Location", [])
        if locations:
            lines.append("\n## 已提及的地点")
            for loc in locations[:6]:
                loc_type = loc.properties.get("location_type", "")
                suffix = f"（{loc_type}）" if loc_type else ""
                lines.append(f"- {loc.name}{suffix}")

        # Emotions (brief)
        emotions = by_type.get("Emotion", [])
        if emotions:
            lines.append("\n## 已表达的情感")
            emotion_names = [e.name for e in emotions[:8]]
            lines.append("、".join(emotion_names))
            if len(emotions) > 8:
                lines.append(f"等 {len(emotions)} 种")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Open loop extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_open_loops(entities: List[HistoricalEntity]) -> List[str]:
        """Extract follow-up leads from historical entities.

        Sources:
        - Event entities whose description is short or vague (detail gap)
        - Person entities with no relationship_to_elder (identity gap)
        - Location entities with no emotional_significance (depth gap)
        """
        loops: List[str] = []

        for entity in entities:
            if entity.entity_type == "Event":
                # Events with short descriptions are under-explored
                if len(entity.description) < 30:
                    loops.append(f"「{entity.name}」的细节尚未充分展开")

            elif entity.entity_type == "Person":
                rel = entity.properties.get("relationship_to_elder", "")
                if not rel:
                    loops.append(f"人物「{entity.name}」与老人的关系尚不明确")

            elif entity.entity_type == "Location":
                sig = entity.properties.get("emotional_significance", "")
                if not sig:
                    loops.append(f"地点「{entity.name}」对老人的情感意义尚未探索")

        return loops[:15]  # Cap to avoid prompt bloat
