"""Neo4j synchronous graph database driver.

Thin wrapper around the official ``neo4j`` Python driver that provides:
- Auto-connect on first query
- Schema initialisation (constraints + indexes)
- CRUD helpers for nodes and edges
- N-hop neighbourhood queries
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.config import Config

logger = logging.getLogger(__name__)


class Neo4jGraphDriver:
    """Synchronous Neo4j driver with convenience helpers."""

    # Labels that receive unique-id constraints during schema init.
    MANAGED_LABELS = ("Topic", "Event", "Person", "Location", "Emotion", "Insight")

    def __init__(
        self,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self.uri = uri or Config.NEO4J_URI
        self.username = username or Config.NEO4J_USERNAME
        self.password = password or Config.NEO4J_PASSWORD
        self.database = database or Config.NEO4J_DATABASE
        self.driver = None
        self._connected = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open a driver connection and verify it works."""
        try:
            from neo4j import GraphDatabase  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "neo4j package not installed. Run: pip install neo4j"
            ) from exc

        self.driver = GraphDatabase.driver(
            self.uri,
            auth=(self.username, self.password),
            max_connection_pool_size=50,
        )
        # Smoke-test the connection.
        with self.driver.session(database=self.database) as session:
            session.run("RETURN 1").consume()
        self._connected = True
        logger.info("Connected to Neo4j at %s", self.uri)

    def close(self) -> None:
        if self.driver:
            self.driver.close()
            self.driver = None
            self._connected = False
            logger.info("Neo4j connection closed")

    def _ensure_connected(self) -> None:
        if self.driver is None and not self._connected:
            self.connect()

    # ------------------------------------------------------------------
    # Low-level query execution
    # ------------------------------------------------------------------

    def execute_query(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Run a Cypher query and return records as list-of-dicts."""
        self._ensure_connected()
        if self.driver is None:
            logger.error("Neo4j driver not initialised — cannot execute query")
            return None
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, params or {})
                records = [dict(record) for record in result]
            return records
        except Exception:
            logger.exception("Cypher query failed")
            return None

    # ------------------------------------------------------------------
    # Node helpers
    # ------------------------------------------------------------------

    def insert_node(self, node_dict: Dict[str, Any]) -> bool:
        """Insert or update a node using its ``type`` field as the Neo4j label."""
        node_id = node_dict.get("id", "")
        node_type = node_dict.get("type", "Entity")

        label_map = {
            "Event": "Event",
            "Person": "Person",
            "Location": "Location",
            "Emotion": "Emotion",
            "Topic": "Topic",
            "Insight": "Insight",
            "Time_Period": "TimePeriod",
            "TimePeriod": "TimePeriod",
        }
        label = label_map.get(node_type, "Entity")

        query = f"""
        MERGE (n:{label} {{id: $id}})
        SET n += $properties
        RETURN n
        """
        result = self.execute_query(
            query, {"id": node_id, "properties": node_dict}
        )
        ok = result is not None
        if ok:
            logger.debug("Upserted node %s (%s)", node_id, label)
        else:
            logger.warning("Failed to upsert node %s", node_id)
        return ok

    def node_exists(self, node_id: str) -> bool:
        result = self.execute_query(
            "MATCH (n {id: $id}) RETURN n LIMIT 1", {"id": node_id}
        )
        return bool(result)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        result = self.execute_query(
            "MATCH (n {id: $id}) RETURN n LIMIT 1", {"id": node_id}
        )
        if result:
            return dict(result[0]["n"])
        return None

    # ------------------------------------------------------------------
    # Edge helpers
    # ------------------------------------------------------------------

    def insert_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Create (or merge) a relationship between two existing nodes."""
        if not self.node_exists(source_id):
            logger.warning("Source node not found: %s", source_id)
            return False
        if not self.node_exists(target_id):
            logger.warning("Target node not found: %s", target_id)
            return False

        query = f"""
        MATCH (source) WHERE source.id = $source_id
        MATCH (target) WHERE target.id = $target_id
        MERGE (source)-[r:{relation_type}]->(target)
        SET r += $properties
        RETURN r
        """
        result = self.execute_query(
            query,
            {
                "source_id": source_id,
                "target_id": target_id,
                "properties": properties or {},
            },
        )
        ok = result is not None
        if ok:
            logger.debug(
                "Created edge %s -[%s]-> %s", source_id, relation_type, target_id
            )
        return ok

    # ------------------------------------------------------------------
    # Hop-based queries
    # ------------------------------------------------------------------

    def query_by_hop(
        self,
        node_id: str,
        hop_count: int = 1,
        max_nodes: int = 100,
    ) -> Dict[str, Any]:
        """Return the N-hop neighbourhood of *node_id*.

        Returns a dict with keys: ``center``, ``neighbors_by_hop``, ``relationships``.
        """
        hop_count = max(1, min(hop_count, 5))
        result: Dict[str, Any] = {
            "center": None,
            "neighbors_by_hop": {},
            "relationships": [],
            "total_nodes": 0,
            "total_relations": 0,
        }

        # Centre node
        centre = self.execute_query(
            "MATCH (center {id: $node_id}) RETURN center", {"node_id": node_id}
        )
        if not centre:
            return result
        result["center"] = dict(centre[0]["center"])

        # Per-hop neighbours
        for hop in range(1, hop_count + 1):
            query = f"""
            MATCH (center {{id: $node_id}})
            MATCH (center)-[*{hop}]-(neighbor)
            WHERE neighbor.id <> $node_id
            WITH DISTINCT neighbor
            LIMIT $max_nodes
            RETURN
                neighbor.id as id,
                neighbor.type as type,
                neighbor.name as name,
                neighbor.description as description
            """
            rows = self.execute_query(
                query, {"node_id": node_id, "max_nodes": max_nodes}
            )
            if rows:
                result["neighbors_by_hop"][hop] = rows
                result["total_nodes"] += len(rows)

        # Relationships
        rel_query = f"""
        MATCH (center {{id: $node_id}})
        MATCH path = (center)-[*1..{hop_count}]-(neighbor)
        WHERE neighbor.id <> $node_id
        UNWIND relationships(path) as rel
        WITH DISTINCT
            startNode(rel).id as source_id,
            type(rel) as relation_type,
            endNode(rel).id as target_id
        RETURN source_id, relation_type, target_id
        LIMIT 1000
        """
        rels = self.execute_query(rel_query, {"node_id": node_id})
        if rels:
            result["relationships"] = rels
            result["total_relations"] = len(rels)

        return result

    def get_neighbors(
        self,
        node_id: str,
        max_depth: int = 1,
        relation_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get all neighbours up to *max_depth* hops."""
        if relation_types:
            rel_pattern = "|".join(relation_types)
            rel_str = f"[:{rel_pattern}]*1..{max_depth}"
        else:
            rel_str = f"*1..{max_depth}"

        query = f"""
        MATCH (center {{id: $node_id}})
        MATCH (center)-[{rel_str}]-(neighbor)
        RETURN DISTINCT neighbor
        """
        rows = self.execute_query(query, {"node_id": node_id})
        if not rows:
            return []
        return [dict(r["neighbor"]) for r in rows]

    # ------------------------------------------------------------------
    # Statistics / search helpers
    # ------------------------------------------------------------------

    def get_graph_statistics(self) -> Dict[str, Any]:
        stats_query = """
        MATCH (n)
        RETURN
            COUNT(n) as total_nodes,
            COUNT(DISTINCT n.type) as unique_types
        """
        stats = self.execute_query(stats_query)
        if not stats:
            return {"total_nodes": 0, "unique_types": 0}
        result = dict(stats[0])

        type_query = "MATCH (n) RETURN n.type as type, COUNT(n) as count"
        type_rows = self.execute_query(type_query)
        result["entities_by_type"] = (
            {r["type"]: r["count"] for r in type_rows} if type_rows else {}
        )

        rel_query = (
            "MATCH ()-[r]->() RETURN type(r) as relation_type, COUNT(r) as count"
        )
        rel_rows = self.execute_query(rel_query)
        result["relations_by_type"] = (
            {r["relation_type"]: r["count"] for r in rel_rows} if rel_rows else {}
        )
        return result

    def query_by_text_similarity(
        self,
        text: str,
        entity_type: Optional[str] = None,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        where_clauses = [
            "(toLower(n.name) CONTAINS toLower($text) OR "
            "toLower(n.description) CONTAINS toLower($text))"
        ]
        if entity_type:
            where_clauses.append("n.type = $entity_type")
        where_str = " AND ".join(where_clauses)

        query = f"""
        MATCH (n)
        WHERE {where_str}
        RETURN n.id as id, n.type as type, n.name as name,
               n.description as description
        LIMIT $max_results
        """
        params: Dict[str, Any] = {"text": text, "max_results": max_results}
        if entity_type:
            params["entity_type"] = entity_type
        result = self.execute_query(query, params)
        return result or []

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def initialize_schema(self) -> None:
        """Create uniqueness constraints and indexes for managed labels."""
        if self.driver is None:
            self.connect()
        with self.driver.session(database=self.database) as session:  # type: ignore[union-attr]
            for label in self.MANAGED_LABELS:
                try:
                    session.run(
                        f"CREATE CONSTRAINT unique_{label}_id IF NOT EXISTS "
                        f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                    )
                    session.run(
                        f"CREATE INDEX idx_{label}_type IF NOT EXISTS "
                        f"FOR (n:{label}) ON (n.type)"
                    )
                    session.run(
                        f"CREATE INDEX idx_{label}_name IF NOT EXISTS "
                        f"FOR (n:{label}) ON (n.name)"
                    )
                    logger.debug("Schema ensured for label :%s", label)
                except Exception:
                    logger.debug(
                        "Schema already exists for :%s (or cannot create)", label
                    )
        logger.info("Neo4j schema initialised")
