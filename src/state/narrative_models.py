"""GraphRAG 叙事数据模型 — 替代槽位机制的自由叙事结构。

核心设计原则：
- 不再有固定的 8 槽位 schema
- 实体和关系自由提取，字段全部可选
- rich_text 保存完整叙事，properties 保存可选结构化信息
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class NarrativeFragment:
    """替代 CanonicalEvent 的核心叙事单元。

    存储一段完整的叙事文本及其可选的结构化属性。
    properties dict 可包含 time_anchor, location_name, people_names,
    emotional_tone, significance 等字段，但全部可选。
    """

    fragment_id: str
    rich_text: str
    source_turn_ids: List[str] = field(default_factory=list)
    theme_id: Optional[str] = None
    confidence: float = 0.0
    narrative_richness: float = 0.0
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    merge_status: str = "new"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fragment_id": self.fragment_id,
            "rich_text": self.rich_text,
            "source_turn_ids": list(self.source_turn_ids),
            "theme_id": self.theme_id,
            "confidence": self.confidence,
            "narrative_richness": self.narrative_richness,
            "properties": dict(self.properties),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "merge_status": self.merge_status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NarrativeFragment":
        created = data.get("created_at")
        updated = data.get("updated_at")
        return cls(
            fragment_id=data["fragment_id"],
            rich_text=data["rich_text"],
            source_turn_ids=data.get("source_turn_ids", []),
            theme_id=data.get("theme_id"),
            confidence=float(data.get("confidence", 0.0)),
            narrative_richness=float(data.get("narrative_richness", 0.0)),
            properties=data.get("properties", {}),
            created_at=datetime.fromisoformat(created) if isinstance(created, str) else created,
            updated_at=datetime.fromisoformat(updated) if isinstance(updated, str) else updated,
            merge_status=data.get("merge_status", "new"),
        )


@dataclass
class ExtractedEntity:
    """从对话中自由提取的实体。"""

    entity_type: str  # Event / Person / Location / Emotion / Insight
    name: str
    description: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "name": self.name,
            "description": self.description,
            "properties": dict(self.properties),
        }


@dataclass
class ExtractedRelationship:
    """从对话中提取的实体间关系。"""

    source_name: str
    target_name: str
    relation_type: str  # PARTICIPATES_IN, LOCATED_AT, TRIGGERS, etc.
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_name": self.source_name,
            "target_name": self.target_name,
            "relation_type": self.relation_type,
            "properties": dict(self.properties),
        }


@dataclass
class GraphExtraction:
    """图提取 Agent 的完整输出。"""

    entities: List[ExtractedEntity] = field(default_factory=list)
    relationships: List[ExtractedRelationship] = field(default_factory=list)
    narrative_summary: str = ""
    open_loops: List[str] = field(default_factory=list)
    emotional_state: Optional[Dict[str, Any]] = None
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "relationships": [r.to_dict() for r in self.relationships],
            "narrative_summary": self.narrative_summary,
            "open_loops": list(self.open_loops),
            "emotional_state": self.emotional_state,
            "confidence": self.confidence,
        }

    @property
    def has_content(self) -> bool:
        return bool(self.entities) or bool(self.narrative_summary)

    @property
    def event_entities(self) -> List[ExtractedEntity]:
        return [e for e in self.entities if e.entity_type == "Event"]

    @property
    def person_entities(self) -> List[ExtractedEntity]:
        return [e for e in self.entities if e.entity_type == "Person"]

    @property
    def location_entities(self) -> List[ExtractedEntity]:
        return [e for e in self.entities if e.entity_type == "Location"]

    @property
    def emotion_entities(self) -> List[ExtractedEntity]:
        return [e for e in self.entities if e.entity_type == "Emotion"]
