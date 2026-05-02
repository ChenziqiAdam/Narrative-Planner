"""Unified embedding service supporting local (sentence-transformers) and OpenAI providers."""

import logging
import os
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
}


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

        try:
            if self._provider == "local":
                return self._encode_local(texts)
            elif self._provider == "openai":
                return self._encode_openai(texts)
            else:
                raise ValueError(f"Unknown embedding provider: {self._provider}")
        except Exception:
            logger.exception("Embedding failed (provider=%s), falling back to local", self._provider)
            if self._provider != "local":
                original_provider = self._provider
                self._provider = "local"
                try:
                    return self._encode_local(texts)
                except Exception:
                    self._provider = original_provider
                    raise
            raise

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
            return _MODEL_DIMENSIONS.get(model_name, 384)
        return 1536  # OpenAI default

    # ------------------------------------------------------------------
    # Provider-specific implementations (private)
    # ------------------------------------------------------------------

    def _encode_local(self, texts: List[str]) -> List[List[float]]:
        self._ensure_model()
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def _encode_openai(self, texts: List[str]) -> List[List[float]]:
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
