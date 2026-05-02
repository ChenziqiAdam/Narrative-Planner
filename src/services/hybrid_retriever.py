"""Hybrid retrieval service combining vector search, graph traversal, and full-text search.

Uses Reciprocal Rank Fusion (RRF) to merge results from three retrieval
channels into a single ranked list, then formats the top results into a
prompt section for the interviewer agent.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set

from src.services.retrieval_models import (
    ConnectedEntity,
    RankedEntity,
    RetrievalResult,
    ScoredEntity,
)

logger = logging.getLogger(__name__)

# RRF constant (standard value from Cormack, Clarke & Butt, 2009)
_RRF_K = 60

# Approximate chars-per-token for Chinese text
_CHARS_PER_TOKEN = 2.0

# Entity-type labels used in prompt formatting
_TYPE_LABELS = {
    "Event": "事件",
    "Person": "人物",
    "Location": "地点",
    "Emotion": "情感",
    "Insight": "感悟",
    "Topic": "主题",
}


class HybridRetriever:
    """Retrieve relevant narrative context via vector + graph + fulltext channels."""

    def __init__(
        self,
        neo4j_manager,
        entity_vector_store,
        alpha: float = 0.5,
        beta: float = 0.3,
        gamma: float = 0.2,
    ):
        self._neo4j = neo4j_manager
        self._vector_store = entity_vector_store
        self.alpha = alpha   # vector weight
        self.beta = beta     # graph weight
        self.gamma = gamma   # fulltext weight

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        session_id: str,
        max_tokens: int = 400,
    ) -> RetrievalResult:
        """Run all retrieval channels, fuse with RRF, format for prompt."""
        t0 = time.monotonic()

        # 1. Vector search (always available — in-memory FAISS)
        vector_results = self._vector_search(query)

        # 2. Graph expansion from top vector hits
        graph_results: List[ConnectedEntity] = []
        try:
            seed_ids = [r.entity_id for r in vector_results[:3]]
            if seed_ids:
                graph_results = self._graph_expand(seed_ids)
        except Exception:
            logger.warning("Graph expand failed, continuing without it", exc_info=True)

        # 3. Full-text search (requires Neo4j)
        fulltext_results: List[ScoredEntity] = []
        try:
            fulltext_results = self._fulltext_search(query)
        except Exception:
            logger.warning("Fulltext search failed, continuing without it", exc_info=True)

        # 4. Merge and rank with RRF
        ranked = self._merge_and_rank(vector_results, graph_results, fulltext_results)

        # 5. Format for prompt
        prompt_text = self._format_for_prompt(ranked, max_tokens)
        token_count = int(len(prompt_text) / _CHARS_PER_TOKEN)

        latency_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "Hybrid retrieval: %d entities, %d tokens, %.1f ms",
            len(ranked), token_count, latency_ms,
        )

        return RetrievalResult(
            entities=ranked,
            prompt_text=prompt_text,
            token_count=token_count,
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------
    # Channel 1: Vector search (in-memory FAISS)
    # ------------------------------------------------------------------

    def _vector_search(self, query: str, top_k: int = 5) -> List[ScoredEntity]:
        """Semantic search via EntityVectorStore."""
        hits = self._vector_store.search_by_text(query, top_k=top_k)
        results: List[ScoredEntity] = []
        for entity_id, entity_type, score in hits:
            results.append(ScoredEntity(
                entity_id=entity_id,
                entity_type=entity_type,
                name=entity_id,  # name not returned by search_by_text
                description="",
                score=score,
            ))
        return results

    # ------------------------------------------------------------------
    # Channel 2: Graph expansion (Neo4j N-hop traversal)
    # ------------------------------------------------------------------

    def _graph_expand(
        self,
        entity_ids: List[str],
        max_hops: int = 2,
    ) -> List[ConnectedEntity]:
        """Expand seed entities via N-hop graph traversal."""
        seen: Set[str] = set(entity_ids)
        results: List[ConnectedEntity] = []

        driver = self._neo4j.driver
        for seed_id in entity_ids:
            try:
                hop_data = driver.query_by_hop(seed_id, hop_count=max_hops)
            except Exception:
                logger.debug("query_by_hop failed for %s", seed_id, exc_info=True)
                continue

            neighbors_by_hop = hop_data.get("neighbors_by_hop", {})
            relationships = hop_data.get("relationships", [])

            # Build a quick lookup for relationship paths
            rel_map: Dict[str, str] = {}
            for rel in relationships:
                src = rel.get("source_id", "")
                tgt = rel.get("target_id", "")
                rtype = rel.get("relation_type", "")
                rel_map[f"{src}->{tgt}"] = rtype
                rel_map[f"{tgt}->{src}"] = rtype

            for hop_str, neighbors in neighbors_by_hop.items():
                hop = int(hop_str) if isinstance(hop_str, str) else hop_str
                for nb in neighbors:
                    nb_id = nb.get("id", "")
                    if not nb_id or nb_id in seen:
                        continue
                    seen.add(nb_id)

                    # Build a short path label
                    path_key = f"{seed_id}->{nb_id}"
                    rel_label = rel_map.get(path_key, "RELATED")
                    path_desc = f"{seed_id} -[{rel_label}]-> {nb_id}"

                    results.append(ConnectedEntity(
                        entity_id=nb_id,
                        entity_type=nb.get("type", "Entity"),
                        name=nb.get("name", nb_id),
                        relationship_path=path_desc,
                        hop_distance=hop,
                    ))

        return results

    # ------------------------------------------------------------------
    # Channel 3: Full-text search (Neo4j fulltext index)
    # ------------------------------------------------------------------

    def _fulltext_search(self, query: str, top_k: int = 5) -> List[ScoredEntity]:
        """Keyword search via Neo4j fulltext index."""
        driver = self._neo4j.driver
        rows = driver.fulltext_search(query, top_k=top_k)
        results: List[ScoredEntity] = []
        for row in (rows or []):
            results.append(ScoredEntity(
                entity_id=row.get("id", ""),
                entity_type=row.get("entity_type", "Entity"),
                name=row.get("name", ""),
                description=row.get("description", ""),
                score=float(row.get("score", 0.0)),
            ))
        return results

    # ------------------------------------------------------------------
    # Reciprocal Rank Fusion
    # ------------------------------------------------------------------

    def _merge_and_rank(
        self,
        vector_results: List[ScoredEntity],
        graph_results: List[ConnectedEntity],
        fulltext_results: List[ScoredEntity],
    ) -> List[RankedEntity]:
        """Fuse results from all channels using Reciprocal Rank Fusion."""
        # Collect per-entity scores and metadata
        entity_scores: Dict[str, float] = {}
        entity_meta: Dict[str, dict] = {}
        entity_sources: Dict[str, Set[str]] = {}

        def _ensure(eid: str, etype: str, name: str, desc: str) -> None:
            if eid not in entity_meta:
                entity_meta[eid] = {"type": etype, "name": name, "desc": desc}
                entity_sources[eid] = set()

        # Vector channel
        for rank, entity in enumerate(vector_results):
            eid = entity.entity_id
            _ensure(eid, entity.entity_type, entity.name, entity.description)
            entity_scores[eid] = entity_scores.get(eid, 0.0) + self.alpha / (_RRF_K + rank + 1)
            entity_sources[eid].add("vector")

        # Graph channel (rank by hop distance — closer = better rank)
        sorted_graph = sorted(graph_results, key=lambda e: e.hop_distance)
        for rank, entity in enumerate(sorted_graph):
            eid = entity.entity_id
            _ensure(eid, entity.entity_type, entity.name, "")
            entity_scores[eid] = entity_scores.get(eid, 0.0) + self.beta / (_RRF_K + rank + 1)
            entity_sources[eid].add("graph")

        # Fulltext channel
        for rank, entity in enumerate(fulltext_results):
            eid = entity.entity_id
            _ensure(eid, entity.entity_type, entity.name, entity.description)
            entity_scores[eid] = entity_scores.get(eid, 0.0) + self.gamma / (_RRF_K + rank + 1)
            entity_sources[eid].add("fulltext")

        # Build ranked list
        ranked = []
        for eid, score in entity_scores.items():
            meta = entity_meta[eid]
            ranked.append(RankedEntity(
                entity_id=eid,
                entity_type=meta["type"],
                name=meta["name"],
                description=meta["desc"],
                combined_score=score,
                sources=sorted(entity_sources[eid]),
            ))

        ranked.sort(key=lambda e: e.combined_score, reverse=True)
        return ranked

    # ------------------------------------------------------------------
    # Prompt formatting
    # ------------------------------------------------------------------

    def _format_for_prompt(
        self,
        ranked: List[RankedEntity],
        max_tokens: int = 400,
    ) -> str:
        """Format top-ranked entities into a prompt section."""
        max_chars = int(max_tokens * _CHARS_PER_TOKEN)
        lines: List[str] = ["## 叙事记忆脉络"]

        current_len = len(lines[0])
        for entity in ranked:
            label = _TYPE_LABELS.get(entity.entity_type, entity.entity_type)
            desc = entity.description or entity.name or entity.entity_id
            line = f"- [{label}] {desc}"
            # Keep the line within budget
            if current_len + len(line) + 1 > max_chars:
                break
            lines.append(line)
            current_len += len(line) + 1

        if len(lines) <= 1:
            return ""  # No entities found

        return "\n".join(lines)
