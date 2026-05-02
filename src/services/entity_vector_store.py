"""EntityVectorStore — multi-type entity vector index (in-memory FAISS).

Extends the pattern from EventVectorStore to support multiple entity types
(Event, Person, Location, Emotion, Insight) with type-filtered retrieval.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class EntityVectorStore:
    """In-memory FAISS index supporting multiple entity types."""

    def __init__(self, dimension: int = 384):
        self._dimension = dimension
        self._ids: List[str] = []
        self._types: List[str] = []
        self._id_to_index: Dict[str, int] = {}
        self._embeddings: Optional[np.ndarray] = None
        self._index = None  # faiss.IndexFlatIP

    @property
    def size(self) -> int:
        return len(self._ids)

    def add(
        self,
        entity_id: str,
        entity_type: str,
        text: str,
        embedding: Optional[List[float]] = None,
    ) -> None:
        """Add or update an entity in the index.

        If embedding is None, it will be computed from text using EmbeddingService.
        """
        if embedding is None:
            from src.services.embedding_service import encode_single
            embedding = encode_single(text)

        emb = np.array([embedding], dtype="float32")
        # Normalize for cosine similarity via inner product
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        emb = emb / norms

        if entity_id in self._id_to_index:
            idx = self._id_to_index[entity_id]
            self._embeddings[idx] = emb[0]
            self._types[idx] = entity_type
            self._rebuild_index()
        else:
            self._embeddings = emb if self._embeddings is None else np.vstack([self._embeddings, emb])
            self._id_to_index[entity_id] = len(self._ids)
            self._ids.append(entity_id)
            self._types.append(entity_type)
            self._append_to_index(emb)

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        entity_type: Optional[str] = None,
    ) -> List[Tuple[str, float]]:
        """Search by embedding vector, optionally filtered by entity type."""
        if self._index is None or self.size == 0:
            return []

        import faiss

        q = np.array([query_embedding], dtype="float32")
        norms = np.linalg.norm(q, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        q = q / norms

        # Over-fetch to account for type filtering
        k = min(top_k * 3 if entity_type else top_k, self.size)
        scores, indices = self._index.search(q, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._ids):
                continue
            if entity_type and self._types[idx] != entity_type:
                continue
            results.append((self._ids[idx], float(score)))
            if len(results) >= top_k:
                break
        return results

    def search_by_text(
        self,
        query_text: str,
        top_k: int = 5,
        entity_type: Optional[str] = None,
    ) -> List[Tuple[str, str, float]]:
        """Search by text query. Returns (entity_id, entity_type, score)."""
        from src.services.embedding_service import encode_single
        embedding = encode_single(query_text)
        results = self.search(embedding, top_k, entity_type)
        return [
            (eid, self._types[self._id_to_index[eid]], score)
            for eid, score in results
        ]

    def get_embedding(self, entity_id: str) -> Optional[List[float]]:
        """Get the stored embedding for an entity."""
        idx = self._id_to_index.get(entity_id)
        if idx is None or self._embeddings is None:
            return None
        return self._embeddings[idx].tolist()

    def remove(self, entity_id: str) -> bool:
        """Remove an entity from the index."""
        idx = self._id_to_index.get(entity_id)
        if idx is None:
            return False
        self._ids.pop(idx)
        self._types.pop(idx)
        if self._embeddings is not None:
            self._embeddings = np.delete(self._embeddings, idx, axis=0)
        self._id_to_index = {eid: i for i, eid in enumerate(self._ids)}
        self._rebuild_index()
        return True

    def clear(self) -> None:
        self._ids.clear()
        self._types.clear()
        self._id_to_index.clear()
        self._embeddings = None
        self._index = None

    def _append_to_index(self, emb: np.ndarray) -> None:
        import faiss

        dim = emb.shape[1]
        if self._index is None:
            self._index = faiss.IndexFlatIP(dim)
        self._index.add(emb)

    def _rebuild_index(self) -> None:
        import faiss

        if self._embeddings is None or len(self._embeddings) == 0:
            self._index = None
            return
        dim = self._embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)
        self._index.add(self._embeddings.astype("float32"))
