"""Unified embedding service supporting local, OpenAI, and deterministic fallback vectors."""

import hashlib
import logging
import os
import re
from math import sqrt
from typing import List

# Prevent HuggingFace from attempting network downloads — fail fast if model not cached.
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from src.config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dimension lookup for known models
# ---------------------------------------------------------------------------
_MODEL_DIMENSIONS: dict[str, int] = {
    "paraphrase-multilingual-MiniLM-L12-v2": 384,
    "embedding-3": 2048,
    "text-embedding-3-small": 1536,
}

_FALLBACK_DEFAULT_DIMENSION = 384


class EmbeddingService:
    """Singleton-per-provider embedding service.

    Lazily loads the local model or initialises the OpenAI client on first use.
    """

    _instances: dict[str, "EmbeddingService"] = {}

    def __new__(cls, provider: str | None = None) -> "EmbeddingService":
        provider = provider or Config.EMBEDDING_PROVIDER
        if provider not in cls._instances:
            cls._instances[provider] = super().__new__(cls)
            cls._instances[provider]._initialized = False
        return cls._instances[provider]

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, provider: str | None = None) -> None:
        if self._initialized:
            return
        self._provider: str = provider or Config.EMBEDDING_PROVIDER
        self._model: object | None = None  # SentenceTransformer instance
        self._dimension: int | None = None
        self._fallback_active = False
        self._fallback_reason: str | None = None
        self._fallback_warned = False
        self._initialized = True

    # ------------------------------------------------------------------
    # Lazy loaders (private)
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        """Load the local SentenceTransformer model on first call."""
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        model_name = Config.EMBEDDING_MODEL_LOCAL
        logger.info("Loading local embedding model: %s", model_name)
        self._model = SentenceTransformer(model_name)
        self._dimension = self._model.get_sentence_embedding_dimension()
        logger.info("Embedding provider=%s, dimension=%s", self._provider, self._dimension)

    def _ensure_openai(self) -> None:
        """Validate OpenAI config on first call."""
        if self._dimension is not None:
            return
        if not Config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for the openai embedding provider")
        # Default dimension for text-embedding-3-small; will be overwritten after first call
        self._dimension = 1536
        logger.info("Embedding provider=%s, dimension=%s", self._provider, self._dimension)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Encode a batch of texts into embedding vectors."""
        if not texts:
            return []

        if self._fallback_active:
            return self._encode_fallback(texts)

        if self._provider == "local":
            return self._encode_local(texts)
        elif self._provider == "openai":
            return self._encode_openai(texts)
        else:
            raise ValueError(f"Unknown embedding provider: {self._provider}")

    def encode_single(self, text: str) -> List[float]:
        """Encode a single text string into an embedding vector."""
        return self.encode([text])[0]

    def get_dimension(self) -> int:
        """Return the embedding dimension for the current provider/model."""
        if self._dimension is not None:
            return self._dimension

        # Resolve dimension without a full encode call when possible
        if self._provider == "local":
            model_name = Config.EMBEDDING_MODEL_LOCAL
            return _MODEL_DIMENSIONS.get(model_name, _FALLBACK_DEFAULT_DIMENSION)
        return _MODEL_DIMENSIONS.get(Config.EMBEDDING_OPENAI_MODEL, 1536)

    def get_status(self) -> dict:
        """Return provider status for diagnostics and debug endpoints."""
        return {
            "provider": self._provider,
            "dimension": self.get_dimension(),
            "fallback_active": self._fallback_active,
            "fallback_reason": self._fallback_reason,
        }

    # ------------------------------------------------------------------
    # Provider-specific implementations (private)
    # ------------------------------------------------------------------

    def _encode_local(self, texts: List[str]) -> List[List[float]]:
        try:
            self._ensure_model()
            embeddings = self._model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception as exc:
            self._activate_fallback(exc)
            return self._encode_fallback(texts)

    def _encode_openai(self, texts: List[str]) -> List[List[float]]:
        try:
            self._ensure_openai()
            from openai import OpenAI

            client = OpenAI(
                api_key=Config.EMBEDDING_OPENAI_API_KEY,
                base_url=Config.EMBEDDING_OPENAI_BASE_URL,
            )
            response = client.embeddings.create(
                input=texts,
                model=Config.EMBEDDING_OPENAI_MODEL,
            )
            # Update dimension from actual response
            if response.data:
                self._dimension = len(response.data[0].embedding)
            sorted_data = sorted(response.data, key=lambda d: d.index)
            return [d.embedding for d in sorted_data]
        except Exception as exc:
            self._activate_fallback(exc)
            return self._encode_fallback(texts)

    def _activate_fallback(self, exc: Exception) -> None:
        self._fallback_active = True
        self._fallback_reason = str(exc)
        self._dimension = self.get_dimension() or _FALLBACK_DEFAULT_DIMENSION
        if not self._fallback_warned:
            logger.warning(
                "Embedding provider=%s unavailable; using deterministic lexical fallback vectors. "
                "Reason: %s",
                self._provider,
                exc,
            )
            self._fallback_warned = True

    def _encode_fallback(self, texts: List[str]) -> List[List[float]]:
        dimension = self._dimension or self.get_dimension() or _FALLBACK_DEFAULT_DIMENSION
        return [_lexical_hash_embedding(text, dimension) for text in texts]


def _lexical_hash_embedding(text: str, dimension: int) -> List[float]:
    """Deterministic bag-of-token hash embedding used only when providers fail."""
    dimension = max(1, int(dimension or _FALLBACK_DEFAULT_DIMENSION))
    vector = [0.0] * dimension
    tokens = _fallback_tokens(text)
    if not tokens:
        tokens = ["<empty>"]

    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % dimension
        vector[index] += 1.0

    norm = sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def _fallback_tokens(text: str) -> List[str]:
    normalized = (text or "").lower()
    compact = re.sub(r"\s+", "", normalized)
    tokens = re.findall(r"[a-z0-9_]+", normalized)
    tokens.extend(char for char in compact if not char.isspace())
    tokens.extend(compact[i:i + 2] for i in range(max(0, len(compact) - 1)))
    tokens.extend(compact[i:i + 3] for i in range(max(0, len(compact) - 2)))
    return [token for token in tokens if token]


# ---------------------------------------------------------------------------
# Module-level convenience singleton
# ---------------------------------------------------------------------------

_default_service: EmbeddingService | None = None


def _get_service() -> EmbeddingService:
    global _default_service
    if _default_service is None:
        _default_service = EmbeddingService()
    return _default_service


def encode(texts: List[str]) -> List[List[float]]:
    """Module-level convenience: encode a batch of texts."""
    return _get_service().encode(texts)


def encode_single(text: str) -> List[float]:
    """Module-level convenience: encode a single text."""
    return _get_service().encode_single(text)


def get_dimension() -> int:
    """Module-level convenience: get the embedding dimension."""
    return _get_service().get_dimension()
