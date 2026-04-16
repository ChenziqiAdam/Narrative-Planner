"""Neo4j node data models.

Defines the data structures for the six entity types stored in Neo4j:

- **Topic** — McAdams life-story themes (23 nodes pre-loaded).  This model is
  an extension of the anoversion ``TopicNode`` aligned with the main branch's
  ``ThemeNode`` fields so that Neo4j can serve as the *single source of truth*
  for theme status, slots, seed questions, and exploration depth.
- **Event** — extracted life events.
- **Person** — people mentioned in the interview.
- **Location** — geographic locations.
- **Emotion** — emotional states associated with events.
- **Insight** — AI-extracted patterns and higher-order observations.

Design note: ``TopicNode`` here is **not** the same class as
``src.core.theme_node.ThemeNode``.  It is a lightweight dataclass used
exclusively for serialisation to / from Neo4j properties.  The orchestrator
still keeps an in-memory ``ThemeNode`` for fast signal computation, but
persists state through this model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid


# ════════════════════════════════════════════════════════════════════
# TopicNode — McAdams theme, aligned with src.core.theme_node.ThemeNode
# ════════════════════════════════════════════════════════════════════

@dataclass
class TopicNode:
    """A McAdams life-story theme stored as a Neo4j ``:Topic`` node.

    Fields are a superset of ``ThemeNode`` fields so that the Neo4j node can
    fully replace the in-memory ThemeNode for persistence.
    """

    # ── identity ──
    id: str = ""
    name: str = ""                   # same as ThemeNode.title
    description: str = ""            # same as ThemeNode.description

    # ── McAdams alignment (maps 1:1 to ThemeNode) ──
    theme_id: str = ""               # e.g. "THEME_01_LIFE_CHAPTERS"
    domain: str = ""                 # e.g. "life_chapters"
    status: str = "pending"          # pending | mentioned | exhausted
    priority: int = 5                # 1-10, lower = higher priority
    exploration_depth: int = 0       # 0-5
    slots_filled: Dict[str, bool] = field(default_factory=dict)
    seed_questions: List[str] = field(default_factory=list)
    current_question_index: int = 0
    extracted_events: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)

    # ── topic-specific fields (from anoversion) ──
    topic_category: str = ""
    topic_priority: str = "medium"
    core_message: str = ""
    related_topics: List[str] = field(default_factory=list)

    # ── metadata ──
    type: str = field(default="Topic", init=False)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    first_mentioned_at: str = ""
    exhausted_at: str = ""

    # ── convenience ──

    def get_completion_ratio(self) -> float:
        if not self.slots_filled:
            return min(self.exploration_depth / 5.0, 1.0)
        filled = sum(1 for v in self.slots_filled.values() if v)
        total = len(self.slots_filled)
        if filled > 0:
            return filled / total
        return min(self.exploration_depth / 5.0, 1.0)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["completion_ratio"] = self.get_completion_ratio()
        return d

    @classmethod
    def from_theme_node(cls, theme_node: Any) -> "TopicNode":
        """Create a TopicNode from a ``src.core.theme_node.ThemeNode``."""
        return cls(
            id=theme_node.theme_id,
            name=theme_node.title,
            description=theme_node.description,
            theme_id=theme_node.theme_id,
            domain=theme_node.domain.value if hasattr(theme_node.domain, "value") else str(theme_node.domain),
            status=theme_node.status.value if hasattr(theme_node.status, "value") else str(theme_node.status),
            priority=theme_node.priority,
            exploration_depth=theme_node.exploration_depth,
            slots_filled=dict(theme_node.slots_filled),
            seed_questions=list(theme_node.seed_questions),
            current_question_index=theme_node.current_question_index,
            extracted_events=list(theme_node.extracted_events),
            depends_on=list(theme_node.depends_on),
            created_at=theme_node.created_at.isoformat() if theme_node.created_at else "",
            first_mentioned_at=(
                theme_node.first_mentioned_at.isoformat()
                if theme_node.first_mentioned_at
                else ""
            ),
            exhausted_at=(
                theme_node.exhausted_at.isoformat()
                if theme_node.exhausted_at
                else ""
            ),
        )


# ════════════════════════════════════════════════════════════════════
# EventNode — extracted life event
# ════════════════════════════════════════════════════════════════════

@dataclass
class EventNodeNeo4j:
    """An extracted life event stored as a Neo4j ``:Event`` node."""

    id: str = ""
    name: str = ""
    description: str = ""

    # ── main branch alignment ──
    theme_id: str = ""
    title: str = ""
    time_anchor: str = ""
    location: str = ""
    people_involved: List[str] = field(default_factory=list)
    slots: Dict[str, Any] = field(default_factory=dict)
    emotional_score: float = 0.0
    information_density: float = 0.0
    depth_level: int = 0

    # ── anoversion extras ──
    event_category: str = ""
    time_frame: str = ""
    significance_level: str = "medium"
    emotional_tone: List[str] = field(default_factory=list)

    # ── metadata ──
    type: str = field(default="Event", init=False)
    confidence: float = 0.8
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_canonical_event(cls, event: Any) -> "EventNodeNeo4j":
        """Create from a ``CanonicalEvent`` (src.state)."""
        return cls(
            id=event.event_id,
            name=event.title or event.summary or "",
            description=event.summary or "",
            theme_id=event.theme_id or "",
            title=event.title or "",
            time_anchor=event.time or "",
            location=event.location or "",
            people_involved=list(event.people_names or []),
            slots={
                "time": event.time,
                "location": event.location,
                "people": "、".join(event.people_names) if event.people_names else None,
                "event": event.event or event.summary,
                "reflection": event.reflection or event.feeling,
            },
            emotional_score=0.0,
            information_density=event.completeness_score or 0.0,
            depth_level=max(1, min(int(round((event.completeness_score or 0) * 5)), 5)),
            confidence=event.confidence or 0.8,
        )


# ════════════════════════════════════════════════════════════════════
# PersonNode — a person mentioned in the interview
# ════════════════════════════════════════════════════════════════════

@dataclass
class PersonNodeNeo4j:
    id: str = ""
    name: str = ""
    description: str = ""
    role_in_story: str = ""
    relationship_to_elder: str = ""
    traits: List[str] = field(default_factory=list)
    gender: Optional[str] = None
    current_status: Optional[str] = None
    type: str = field(default="Person", init=False)
    confidence: float = 0.8
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ════════════════════════════════════════════════════════════════════
# LocationNode — a geographic location
# ════════════════════════════════════════════════════════════════════

@dataclass
class LocationNodeNeo4j:
    id: str = ""
    name: str = ""
    description: str = ""
    location_type: str = ""
    characteristics: List[str] = field(default_factory=list)
    emotional_significance: str = ""
    type: str = field(default="Location", init=False)
    confidence: float = 0.8
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ════════════════════════════════════════════════════════════════════
# EmotionNode — emotional state
# ════════════════════════════════════════════════════════════════════

@dataclass
class EmotionNodeNeo4j:
    id: str = ""
    name: str = ""
    description: str = ""
    emotion_category: str = ""
    valence: str = "neutral"       # positive / negative / neutral
    intensity: float = 0.5
    type: str = field(default="Emotion", init=False)
    confidence: float = 0.8
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ════════════════════════════════════════════════════════════════════
# InsightNode — AI-extracted pattern or observation
# ════════════════════════════════════════════════════════════════════

@dataclass
class InsightNodeNeo4j:
    id: str = ""
    name: str = ""
    description: str = ""
    insight_type: str = ""
    title: str = ""
    supporting_events: List[str] = field(default_factory=list)
    confidence_score: float = 0.7
    type: str = field(default="Insight", init=False)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
