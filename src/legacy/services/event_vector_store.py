"""EventVectorStore - session-level event vector index (in-memory, FAISS cosine similarity)."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_INSTANCE = None


def _get_model(model_name: str):
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is None:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading SentenceTransformer: {model_name}")
        _MODEL_INSTANCE = SentenceTransformer(model_name)
    return _MODEL_INSTANCE


class EventVectorStore:
    DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self._model_name = model_name
        self._event_ids: List[str] = []
        self._id_to_index: Dict[str, int] = {}
        self._embeddings: Optional[np.ndarray] = None
        self._index = None  # faiss.IndexFlatIP, lazy init

    @property
    def size(self) -> int:
        return len(self._event_ids)

    def add(self, event_id: str, summary: str) -> None:
        model = _get_model(self._model_name)
        emb = model.encode([summary], convert_to_numpy=True, normalize_embeddings=True)
        if event_id in self._id_to_index:
            idx = self._id_to_index[event_id]
            self._embeddings[idx] = emb[0]
            self._rebuild_index()
        else:
            self._embeddings = emb if self._embeddings is None else np.vstack([self._embeddings, emb])
            self._id_to_index[event_id] = len(self._event_ids)
            self._event_ids.append(event_id)
            self._append_to_index(emb)

    def search(self, query: str, top_k: int = 2) -> List[Tuple[str, float]]:
        if self._index is None or self.size == 0:
            return []
        import faiss
        model = _get_model(self._model_name)
        q_emb = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
        k = min(top_k, self.size)
        scores, indices = self._index.search(q_emb.astype("float32"), k)
        return [
            (self._event_ids[idx], float(score))
            for score, idx in zip(scores[0], indices[0])
            if 0 <= idx < len(self._event_ids)
        ]

    def _append_to_index(self, emb: np.ndarray) -> None:
        import faiss
        dim = emb.shape[1]
        if self._index is None:
            self._index = faiss.IndexFlatIP(dim)
        self._index.add(emb.astype("float32"))

    def _rebuild_index(self) -> None:
        import faiss
        if self._embeddings is None:
            return
        dim = self._embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)
        self._index.add(self._embeddings.astype("float32"))
