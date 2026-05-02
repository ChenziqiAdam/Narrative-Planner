"""GraphWriter — persists GraphExtraction results into Neo4j.

Iterates extracted entities, deduplicates via vector similarity, upserts
nodes, and creates relationships between them.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.services.embedding_service import EmbeddingService
from src.services.entity_vector_store import EntityVectorStore
from src.state.narrative_models import (
    ExtractedEntity,
    GraphExtraction,
)
from src.storage.neo4j.manager import Neo4jGraphManager, _sanitize_node_dict

logger = logging.getLogger(__name__)

# Cosine-similarity threshold for entity deduplication (inner-product on
# L2-normalised vectors stored by EntityVectorStore).
DEDUP_SIMILARITY_THRESHOLD = 0.85


@dataclass
class WriteResult:
    """Summary of a single ``write_extraction`` call."""

    entity_ids: List[str] = field(default_factory=list)
    new_entity_count: int = 0
    updated_entity_count: int = 0
    relationship_count: int = 0
    deduplicated_count: int = 0


class GraphWriter:
    """Writes ``GraphExtraction`` results to Neo4j with deduplication."""

    def __init__(
        self,
        neo4j_manager: Neo4jGraphManager,
        entity_vector_store: EntityVectorStore,
        embedding_service: Optional[EmbeddingService] = None,
    ) -> None:
        self._neo4j = neo4j_manager
        self._vector_store = entity_vector_store
        self._embedding = embedding_service or EmbeddingService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_extraction(
        self,
        extraction: GraphExtraction,
        session_id: str,
        elder_id: str = "",
    ) -> WriteResult:
        """Main entry point.  Upserts entities and creates relationships."""
        result = WriteResult()
        name_to_id: Dict[str, str] = {}

        for entity in extraction.entities:
            try:
                # Compute embedding from name + description.
                text = f"{entity.name}. {entity.description}"
                embedding = self._embedding.encode_single(text)

                # Dedup check — reuse existing node when possible.
                existing_id = self._deduplicate(entity, embedding)
                if existing_id:
                    node_id = existing_id
                    result.deduplicated_count += 1
                    result.updated_entity_count += 1
                else:
                    node_id = self._upsert_entity(
                        entity, session_id, elder_id, embedding
                    )
                    if node_id:
                        result.new_entity_count += 1

                if node_id:
                    result.entity_ids.append(node_id)
                    # Map *both* name and lowercased name for flexible lookup.
                    name_to_id[entity.name] = node_id
                    name_to_id[entity.name.lower()] = node_id
            except Exception:
                logger.exception(
                    "Failed to write entity %s (%s)",
                    entity.name,
                    entity.entity_type,
                )

        # Relationships.
        result.relationship_count = self._create_relationships(
            extraction.relationships, name_to_id
        )

        logger.info(
            "WriteResult: %d entities (%d new, %d updated, %d deduped), %d rels",
            len(result.entity_ids),
            result.new_entity_count,
            result.updated_entity_count,
            result.deduplicated_count,
            result.relationship_count,
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _upsert_entity(
        self,
        entity: ExtractedEntity,
        session_id: str,
        elder_id: str,
        embedding: List[float],
    ) -> Optional[str]:
        """Upsert a single entity into Neo4j and the vector store.

        Returns the Neo4j node ID, or ``None`` on failure.
        """
        node_id = self._generate_entity_id(entity.entity_type, entity.name)

        node_dict: Dict[str, dict] = {
            "id": node_id,
            "name": entity.name,
            "description": entity.description,
            "type": entity.entity_type,
            "session_id": session_id,
            "elder_id": elder_id,
            **entity.properties,
        }

        # Events carry a rich_text field with the full narrative.
        if entity.entity_type == "Event":
            node_dict.setdefault("rich_text", entity.description)

        # Store the embedding so Neo4j vector index can also be used.
        node_dict["embedding"] = embedding

        ok = self._neo4j.driver.insert_node(_sanitize_node_dict(node_dict))
        if not ok:
            logger.warning("Failed to upsert entity node %s", node_id)
            return None

        # Keep the in-memory vector store in sync.
        self._vector_store.add(
            entity_id=node_id,
            entity_type=entity.entity_type,
            text=f"{entity.name}. {entity.description}",
            embedding=embedding,
        )
        return node_id

    def _create_relationships(
        self,
        relationships: List,
        name_to_id: Dict[str, str],
    ) -> int:
        """Create edges for extracted relationships.

        Returns the count of successfully created edges.
        """
        count = 0
        for rel in relationships:
            source_id = name_to_id.get(rel.source_name) or name_to_id.get(
                rel.source_name.lower()
            )
            target_id = name_to_id.get(rel.target_name) or name_to_id.get(
                rel.target_name.lower()
            )
            if not source_id or not target_id:
                logger.debug(
                    "Skipping relationship %s — cannot resolve source=%s target=%s",
                    rel.relation_type,
                    rel.source_name,
                    rel.target_name,
                )
                continue
            try:
                ok = self._neo4j.driver.insert_edge(
                    source_id, target_id, rel.relation_type, rel.properties or None
                )
                if ok:
                    count += 1
            except Exception:
                logger.exception(
                    "Failed to create edge %s -[%s]-> %s",
                    source_id,
                    rel.relation_type,
                    target_id,
                )
        return count

    def _deduplicate(
        self,
        entity: ExtractedEntity,
        embedding: List[float],
    ) -> Optional[str]:
        """Check whether a similar entity already exists.

        Returns the existing entity ID or ``None``.
        """
        hits = self._vector_store.search(
            query_embedding=embedding,
            top_k=3,
            entity_type=entity.entity_type,
        )
        for existing_id, score in hits:
            if score < DEDUP_SIMILARITY_THRESHOLD:
                continue
            # Require a partial name overlap to avoid false positives.
            existing_emb = self._vector_store.get_embedding(existing_id)
            if existing_emb is None:
                continue
            # Name check: substring match (case-insensitive).
            if (
                entity.name.lower() in existing_id.lower()
                or any(entity.name.lower() in k.lower() for k in [existing_id])
            ):
                logger.debug(
                    "Dedup hit: %s matches existing %s (score=%.3f)",
                    entity.name,
                    existing_id,
                    score,
                )
                return existing_id
        return None

    @staticmethod
    def _generate_entity_id(entity_type: str, name: str) -> str:
        """Generate a stable, deterministic ID from entity type and name."""
        raw = f"{entity_type}:{name}"
        return f"{entity_type.lower()}_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"
