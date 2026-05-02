"""Data classes for hybrid retrieval results."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class ScoredEntity:
    """An entity with a relevance score from a single retrieval channel."""

    entity_id: str
    entity_type: str
    name: str
    description: str
    score: float


@dataclass
class ConnectedEntity:
    """An entity discovered via graph traversal from a seed entity."""

    entity_id: str
    entity_type: str
    name: str
    relationship_path: str
    hop_distance: int


@dataclass
class RankedEntity:
    """An entity ranked after Reciprocal Rank Fusion across all channels."""

    entity_id: str
    entity_type: str
    name: str
    description: str
    combined_score: float
    sources: List[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    """Complete result from a hybrid retrieval pass."""

    entities: List[RankedEntity] = field(default_factory=list)
    prompt_text: str = ""
    token_count: int = 0
    latency_ms: float = 0.0
