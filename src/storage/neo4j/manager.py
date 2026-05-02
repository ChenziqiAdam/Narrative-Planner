"""Neo4j graph memory manager — adapted from anoversion for the main branch.

This module provides ``Neo4jGraphManager``, a synchronous wrapper around
``Neo4jGraphDriver`` that adds:

* **McAdams Topic support** — initialise, update, and query the 23
  life-story themes.
* **Event / Person / Location / Emotion node CRUD** — aligned with main
  branch's data model.
* **Vector dedup** — reuses main's ``EventVectorStore`` for semantic
  similarity checks before inserting new nodes.
* **Coverage computation** — Cypher-based aggregation that feeds into
  ``CoverageCache``.
* **Pattern detection** — finds recurring entities and themes across events.

The public API mirrors ``src.core.graph_manager.GraphManager`` so that the
``Neo4jGraphAdapter`` (Phase 2) can swap in transparently.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from src.storage.neo4j.driver import Neo4jGraphDriver
from src.storage.neo4j.models import (
    TopicNode,
    EventNodeNeo4j,
    PersonNodeNeo4j,
    LocationNodeNeo4j,
    EmotionNodeNeo4j,
)

logger = logging.getLogger(__name__)


def _sanitize_node_dict(node_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Convert complex Python types to Neo4j-compatible primitives.

    Neo4j cannot store nested dicts or datetime objects directly.
    This helper converts:
    - dict → JSON string
    - list of dicts → JSON string
    - datetime → ISO string
    - bool → kept as-is (Neo4j supports booleans)
    - None → removed
    """
    sanitized: Dict[str, Any] = {}
    for key, value in node_dict.items():
        if value is None:
            continue
        if isinstance(value, _dt):
            sanitized[key] = value.isoformat()
        elif isinstance(value, dict):
            sanitized[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            sanitized[key] = json.dumps(value, ensure_ascii=False)
        else:
            sanitized[key] = value
    return sanitized


class Neo4jGraphManager:
    """High-level synchronous manager for the interview knowledge graph."""

    # Relationship type constants (match the main-branch frontend edge types).
    REL_DEPENDS_ON = "DEPENDS_ON"
    REL_INCLUDES = "INCLUDES"
    REL_PARTICIPATES_IN = "PARTICIPATES_IN"
    REL_LOCATED_AT = "LOCATED_AT"
    REL_TRIGGERS = "TRIGGERS"
    REL_FAMILY_OF = "FAMILY_OF"
    REL_KNOWS = "KNOWS"
    REL_TEMPORAL_NEXT = "TEMPORAL_NEXT"

    def __init__(self, driver: Optional[Neo4jGraphDriver] = None):
        self.driver = driver or Neo4jGraphDriver()
        # Local cache for fast repeated lookups.
        self._node_cache: Dict[str, Dict[str, Any]] = {}

    # ────────────────────────────────────────────────────────────────
    # Lifecycle
    # ────────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Connect to Neo4j and ensure schema exists."""
        self.driver.connect()
        self.driver.initialize_schema()
        logger.info("Neo4jGraphManager initialised")

    def close(self) -> None:
        self.driver.close()

    # ────────────────────────────────────────────────────────────────
    # Topic (McAdams Theme) operations
    # ────────────────────────────────────────────────────────────────

    def upsert_topic(self, topic: TopicNode) -> bool:
        """Insert or update a McAdams Topic node."""
        node_dict = topic.to_dict()
        node_dict["id"] = topic.id or topic.theme_id
        node_dict["type"] = "Topic"
        node_dict["name"] = topic.name or topic.theme_id
        ok = self.driver.insert_node(node_dict)
        if ok:
            logger.debug("Upserted Topic %s", topic.theme_id)
        return ok

    def batch_upsert_topics(self, topics: List[TopicNode]) -> int:
        """Upsert multiple topics.  Returns count of successful writes."""
        count = 0
        for t in topics:
            if self.upsert_topic(t):
                count += 1
        # Create DEPENDS_ON edges between topics.
        for t in topics:
            for dep_id in t.depends_on:
                self.driver.insert_edge(
                    t.id or t.theme_id, dep_id, self.REL_DEPENDS_ON
                )
        return count

    def sync_themes_to_neo4j(self) -> int:
        """Load McAdams theme definitions and upsert them as ``:Topic`` nodes."""
        from src.core.theme_loader import ThemeLoader

        themes = ThemeLoader().load()
        topics = [TopicNode.from_theme_node(theme) for theme in themes.values()]
        return self.batch_upsert_topics(topics)

    def get_topic(self, theme_id: str) -> Optional[Dict[str, Any]]:
        """Read a single Topic node by its ``theme_id``."""
        result = self.driver.execute_query(
            "MATCH (t:Topic {id: $id}) RETURN t", {"id": theme_id}
        )
        if result:
            return dict(result[0]["t"])
        return None

    def get_all_topics(self) -> Dict[str, Dict[str, Any]]:
        """Return all Topic nodes as ``{theme_id: properties_dict}``."""
        rows = self.driver.execute_query("MATCH (t:Topic) RETURN t")
        if not rows:
            return {}
        return {dict(r["t"]).get("id", ""): dict(r["t"]) for r in rows}

    def update_topic_status(self, theme_id: str, status: str) -> bool:
        result = self.driver.execute_query(
            """
            MATCH (t:Topic {id: $id})
            SET t.status = $status
            RETURN t
            """,
            {"id": theme_id, "status": status},
        )
        return result is not None

    def update_topic_slots(self, theme_id: str, slots_filled: Dict[str, bool]) -> bool:
        import json
        result = self.driver.execute_query(
            """
            MATCH (t:Topic {id: $id})
            SET t.slots_filled = $slots
            RETURN t
            """,
            {"id": theme_id, "slots": json.dumps(slots_filled)},
        )
        return result is not None

    def increment_topic_depth(self, theme_id: str) -> bool:
        result = self.driver.execute_query(
            """
            MATCH (t:Topic {id: $id})
            SET t.exploration_depth = CASE
                WHEN t.exploration_depth IS NULL THEN 1
                ELSE min(t.exploration_depth + 1, 5)
            END
            RETURN t
            """,
            {"id": theme_id},
        )
        return result is not None

    def add_event_to_topic(self, theme_id: str, event_id: str) -> bool:
        """Add an event ID to the topic's extracted_events list and create INCLUDES edge."""
        self.driver.execute_query(
            """
            MATCH (t:Topic {id: $theme_id})
            SET t.extracted_events = CASE
                WHEN t.extracted_events IS NULL THEN [$event_id]
                WHEN NOT $event_id IN t.extracted_events
                    THEN t.extracted_events + [$event_id]
                ELSE t.extracted_events
            END
            RETURN t
            """,
            {"theme_id": theme_id, "event_id": event_id},
        )
        return self.driver.insert_edge(theme_id, event_id, self.REL_INCLUDES)

    # ────────────────────────────────────────────────────────────────
    # Event operations
    # ────────────────────────────────────────────────────────────────

    def upsert_event(self, event: EventNodeNeo4j, theme_id: str) -> bool:
        """Insert or update an Event node and link it to its Topic."""
        node_dict = event.to_dict()
        node_dict["id"] = event.id
        node_dict["type"] = "Event"
        node_dict["name"] = event.title or event.name or event.id
        ok = self.driver.insert_node(node_dict)
        if ok and theme_id:
            self.driver.insert_edge(theme_id, event.id, self.REL_INCLUDES)
        return ok

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        result = self.driver.execute_query(
            "MATCH (e:Event {id: $id}) RETURN e", {"id": event_id}
        )
        if result:
            return dict(result[0]["e"])
        return None

    def get_all_events(self) -> Dict[str, Dict[str, Any]]:
        rows = self.driver.execute_query("MATCH (e:Event) RETURN e")
        if not rows:
            return {}
        return {dict(r["e"]).get("id", ""): dict(r["e"]) for r in rows}

    # ────────────────────────────────────────────────────────────────
    # Person operations
    # ────────────────────────────────────────────────────────────────

    def upsert_person(self, person: PersonNodeNeo4j, event_id: Optional[str] = None) -> bool:
        node_dict = person.to_dict()
        node_dict["id"] = person.id
        node_dict["type"] = "Person"
        node_dict["name"] = person.name or person.id
        ok = self.driver.insert_node(node_dict)
        if ok and event_id:
            self.driver.insert_edge(event_id, person.id, self.REL_PARTICIPATES_IN)
        return ok

    def get_all_people(self) -> Dict[str, Dict[str, Any]]:
        rows = self.driver.execute_query("MATCH (p:Person) RETURN p")
        if not rows:
            return {}
        return {dict(r["p"]).get("id", ""): dict(r["p"]) for r in rows}

    # ────────────────────────────────────────────────────────────────
    # Location operations
    # ────────────────────────────────────────────────────────────────

    def upsert_location(self, location: LocationNodeNeo4j, event_id: Optional[str] = None) -> bool:
        node_dict = location.to_dict()
        node_dict["id"] = location.id
        node_dict["type"] = "Location"
        node_dict["name"] = location.name or location.id
        ok = self.driver.insert_node(node_dict)
        if ok and event_id:
            self.driver.insert_edge(event_id, location.id, self.REL_LOCATED_AT)
        return ok

    # ────────────────────────────────────────────────────────────────
    # Emotion operations
    # ────────────────────────────────────────────────────────────────

    def upsert_emotion(self, emotion: EmotionNodeNeo4j, event_id: Optional[str] = None) -> bool:
        node_dict = emotion.to_dict()
        node_dict["id"] = emotion.id
        node_dict["type"] = "Emotion"
        node_dict["name"] = emotion.name or emotion.id
        ok = self.driver.insert_node(node_dict)
        if ok and event_id:
            self.driver.insert_edge(event_id, emotion.id, self.REL_TRIGGERS)
        return ok

    # ────────────────────────────────────────────────────────────────
    # Coverage computation (Cypher aggregation)
    # ────────────────────────────────────────────────────────────────

    def calculate_theme_coverage(self) -> Dict[str, float]:
        """Return {domain: avg_completion_ratio} for all Topic nodes."""
        rows = self.driver.execute_query(
            """
            MATCH (t:Topic)
            RETURN t.domain AS domain, t.slots_filled AS slots,
                   t.exploration_depth AS depth
            """
        )
        if not rows:
            return {"overall": 0.0}

        domain_ratios: Dict[str, List[float]] = {}
        for row in rows:
            domain = row.get("domain", "unknown") or "unknown"
            # Parse slots_filled (may be stored as JSON string)
            import json
            slots_raw = row.get("slots", {})
            if isinstance(slots_raw, str):
                try:
                    slots_raw = json.loads(slots_raw)
                except (json.JSONDecodeError, TypeError):
                    slots_raw = {}
            if isinstance(slots_raw, dict) and slots_raw:
                filled = sum(1 for v in slots_raw.values() if v)
                ratio = filled / len(slots_raw)
            else:
                depth = row.get("depth", 0) or 0
                ratio = min(depth / 5.0, 1.0)
            domain_ratios.setdefault(domain, []).append(ratio)

        by_domain = {d: sum(v) / len(v) for d, v in domain_ratios.items()}
        all_ratios = [r for rs in domain_ratios.values() for r in rs]
        by_domain["overall"] = sum(all_ratios) / len(all_ratios) if all_ratios else 0.0
        return by_domain

    def calculate_slot_coverage(self) -> Dict[str, float]:
        """Compute per-slot fill rate across all Event nodes."""
        rows = self.driver.execute_query("MATCH (e:Event) RETURN e.slots AS slots")
        if not rows:
            return {}

        slot_names = ("time", "location", "people", "event", "reflection")
        counts: Dict[str, int] = {s: 0 for s in slot_names}
        total = 0
        for row in rows:
            slots = row.get("slots", {})
            if isinstance(slots, str):
                import json
                try:
                    slots = json.loads(slots)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(slots, dict):
                continue
            total += 1
            for s in slot_names:
                if slots.get(s) not in (None, "", []):
                    counts[s] += 1

        if total == 0:
            return {s: 0.0 for s in slot_names}
        return {s: counts[s] / total for s in slot_names}

    def get_coverage_metrics(self) -> Dict[str, Any]:
        """Combined coverage dict consumed by CoverageCache."""
        theme_cov = self.calculate_theme_coverage()
        slot_cov = self.calculate_slot_coverage()
        return {
            "overall": theme_cov.get("overall", 0.0),
            "by_domain": {k: v for k, v in theme_cov.items() if k != "overall"},
            "slot_coverage": slot_cov,
        }

    # ────────────────────────────────────────────────────────────────
    # N-hop queries / pattern detection
    # ────────────────────────────────────────────────────────────────

    def get_entity_by_hop(self, node_id: str, hop_count: int = 2) -> Dict[str, Any]:
        return self.driver.query_by_hop(node_id, hop_count)

    def get_related_themes(self, theme_id: str, hop: int = 2) -> List[Dict[str, Any]]:
        """Find themes connected to *theme_id* within *hop* hops."""
        rows = self.driver.execute_query(
            f"""
            MATCH (t:Topic {{id: $theme_id}})-[*1..{hop}]-(other:Topic)
            RETURN DISTINCT other.id AS id, other.name AS name,
                   other.status AS status, other.domain AS domain
            """,
            {"theme_id": theme_id},
        )
        return rows or []

    def detect_patterns(self) -> List[Dict[str, Any]]:
        """Find recurring people, locations, or emotions across events."""
        patterns: List[Dict[str, Any]] = []

        # People who appear in multiple events
        rows = self.driver.execute_query(
            """
            MATCH (p:Person)-[:PARTICIPATES_IN]-(e:Event)
            WITH p, COUNT(e) AS event_count
            WHERE event_count > 1
            RETURN p.id AS person_id, p.name AS name, event_count
            ORDER BY event_count DESC
            """
        )
        if rows:
            patterns.append({
                "pattern_type": "recurring_person",
                "items": rows,
            })

        # Emotions linked to multiple events
        rows = self.driver.execute_query(
            """
            MATCH (em:Emotion)<-[:TRIGGERS]-(e:Event)
            WITH em, COUNT(e) AS event_count
            WHERE event_count > 1
            RETURN em.id AS emotion_id, em.name AS name, event_count
            ORDER BY event_count DESC
            """
        )
        if rows:
            patterns.append({
                "pattern_type": "recurring_emotion",
                "items": rows,
            })

        return patterns

    # ────────────────────────────────────────────────────────────────
    # Dedup helper (uses EventVectorStore)
    # ────────────────────────────────────────────────────────────────

    def find_similar_event(
        self, text: str, vector_store: Any, threshold: float = 0.80
    ) -> Optional[str]:
        """Check if a semantically similar event already exists.

        *vector_store* should be an ``EventVectorStore`` instance.
        Returns the matching event_id or ``None``.
        """
        hits = vector_store.search(text, top_k=1)
        if hits:
            event_id, score = hits[0]
            if score >= threshold:
                logger.debug(
                    "Similar event found: %s (score=%.3f)", event_id, score
                )
                return event_id
        return None

    # ────────────────────────────────────────────────────────────────
    # Generic helpers (from anoversion)
    # ────────────────────────────────────────────────────────────────

    def _sanitize_and_write(self, node_dict: Dict[str, Any]) -> bool:
        """Sanitize complex types and write to Neo4j."""
        sanitized = _sanitize_node_dict(node_dict)
        ok = self.driver.insert_node(sanitized)
        if ok:
            self._node_cache[sanitized.get("id", "")] = sanitized
        return ok

    def get_node_by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Cache-first node lookup."""
        if node_id in self._node_cache:
            return self._node_cache[node_id]
        node = self.driver.get_node(node_id)
        if node:
            self._node_cache[node_id] = node
        return node

    def create_event_with_subnodes(
        self,
        event: EventNodeNeo4j,
        theme_id: str,
        participants: Optional[List[str]] = None,
        locations: Optional[List[str]] = None,
        emotional_tones: Optional[List[str]] = None,
    ) -> bool:
        """Create an Event node **and** auto-generate Person / Location / Emotion
        child nodes with appropriate edges.

        This is the anoversion "smart factory" pattern — one call creates the
        full sub-graph around an event.
        """
        # 1. Upsert the event itself.
        ok = self.upsert_event(event, theme_id)
        if not ok:
            return False

        # 2. Auto-create Person sub-nodes.
        for person_name in (participants or []):
            if not person_name:
                continue
            person_id = f"person_{uuid.uuid4().hex[:8]}"
            person = PersonNodeNeo4j(
                id=person_id,
                name=person_name,
                description=f"Participant in: {event.title or event.description}",
                role_in_story="mentioned",
            )
            self.upsert_person(person, event.id)

        # 3. Auto-create Location sub-nodes.
        for loc_name in (locations or []):
            if not loc_name:
                continue
            loc_id = f"loc_{uuid.uuid4().hex[:8]}"
            location = LocationNodeNeo4j(
                id=loc_id,
                name=loc_name,
                description=f"Location for: {event.title or event.description}",
            )
            self.upsert_location(location, event.id)

        # 4. Auto-create Emotion sub-nodes.
        for tone in (emotional_tones or []):
            if not tone:
                continue
            emotion_id = f"emot_{uuid.uuid4().hex[:8]}"
            emotion = EmotionNodeNeo4j(
                id=emotion_id,
                name=tone,
                description=f"Emotional tone of: {event.title or event.description}",
                emotion_category=tone,
            )
            self.upsert_emotion(emotion, event.id)

        return True

    def insert_memory(
        self,
        entity_type: str,
        entity_data: Dict[str, Any],
        relations: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[str]:
        """Generic insert-any-entity interface (from anoversion).

        Args:
            entity_type: "Event", "Person", "Location", "Emotion", "Topic", "Insight"
            entity_data: Flat dict of node properties.
            relations: Optional list of ``{"target_id": ..., "rel_type": ...}`` dicts.

        Returns:
            The created node ID, or None on failure.
        """
        node_id = entity_data.get("id") or f"{entity_type.lower()}_{uuid.uuid4().hex[:8]}"
        node_dict = {**entity_data, "id": node_id, "type": entity_type}
        node_dict.setdefault("name", node_id)

        ok = self._sanitize_and_write(node_dict)
        if not ok:
            return None

        if relations:
            for rel in relations:
                self.driver.insert_edge(
                    node_id,
                    rel["target_id"],
                    rel["rel_type"],
                )
        return node_id

    # ────────────────────────────────────────────────────────────────
    # Cross-session queries (by elder_id)
    # ────────────────────────────────────────────────────────────────

    def get_entities_by_elder(self, elder_id: str) -> List[Dict[str, Any]]:
        """Return all entity nodes belonging to *elder_id*."""
        rows = self.driver.execute_query(
            """
            MATCH (n)
            WHERE n.elder_id = $elder_id
              AND n.type IN ['Event', 'Person', 'Location', 'Emotion', 'Insight']
            RETURN n
            """,
            {"elder_id": elder_id},
        )
        if not rows:
            return []
        return [dict(r["n"]) for r in rows]

    def get_event_count_by_elder(self, elder_id: str) -> int:
        """Count Event nodes for *elder_id*."""
        rows = self.driver.execute_query(
            """
            MATCH (e:Event {elder_id: $elder_id})
            RETURN COUNT(e) AS cnt
            """,
            {"elder_id": elder_id},
        )
        if rows:
            return rows[0].get("cnt", 0) or 0
        return 0

    def get_elder_session_ids(self, elder_id: str) -> List[str]:
        """Return distinct session_ids associated with *elder_id*."""
        rows = self.driver.execute_query(
            """
            MATCH (n {elder_id: $elder_id})
            WHERE n.session_id IS NOT NULL
            RETURN DISTINCT n.session_id AS sid
            """,
            {"elder_id": elder_id},
        )
        if not rows:
            return []
        return [r["sid"] for r in rows if r.get("sid")]

    def get_entity_neighbors(
        self, entity_id: str, max_hops: int = 1
    ) -> List[Dict[str, Any]]:
        """Return 1-hop neighbours of an entity node.

        Each result dict contains ``id``, ``type``, ``name``,
        ``description`` and ``rel_type``.
        """
        rows = self.driver.execute_query(
            f"""
            MATCH (n {{id: $id}})-[r]-(neighbor)
            RETURN neighbor.id AS id, neighbor.type AS type,
                   neighbor.name AS name, neighbor.description AS description,
                   type(r) AS rel_type
            """,
            {"id": entity_id},
        )
        return rows or []

    def get_graph_gaps(self, elder_id: str) -> List[Dict[str, Any]]:
        """Find Events that lack Person/Location/Emotion connections.

        Returns entities with ``id``, ``name``, ``description`` plus
        ``person_count``, ``location_count``, ``emotion_count``.
        """
        rows = self.driver.execute_query(
            """
            MATCH (e:Event {elder_id: $elder_id})
            OPTIONAL MATCH (e)<-[:PARTICIPATES_IN]-(p:Person)
            OPTIONAL MATCH (e)-[:LOCATED_AT]->(l:Location)
            OPTIONAL MATCH (e)-[:TRIGGERS]->(em:Emotion)
            WITH e, count(DISTINCT p) AS person_count,
                     count(DISTINCT l) AS location_count,
                     count(DISTINCT em) AS emotion_count
            WHERE person_count + location_count + emotion_count < 2
            RETURN e.id AS id, e.name AS name, e.description AS description,
                   person_count, location_count, emotion_count
            ORDER BY e.name
            """,
            {"elder_id": elder_id},
        )
        return rows or []
