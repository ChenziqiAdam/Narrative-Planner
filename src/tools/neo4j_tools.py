"""Neo4j graph query tools — OpenAI function-calling format.

Rewrites the high-value CAMEL-based tools from anoversion into the same
3-layer pattern used by ``src/tools/elder_tools.py``:

1. ``Neo4jQuerySystem`` — implementation (calls Neo4jGraphManager)
2. ``get_neo4j_tool_schemas()`` — OpenAI function schema declarations
3. ``get_neo4j_tool_callables()`` — name → method dispatch dict

Tools provided:
- **detect_patterns** — find recurring people / emotions across events
- **get_entity_context** — N-hop neighbourhood around a node
- **check_node_conflict** — detect contradictions between existing and new data
- **query_graph_entities** — search nodes by type and text
- **get_graph_summary** — overall graph statistics (node/relation counts)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from src.config import Config

logger = logging.getLogger(__name__)


class Neo4jQuerySystem:
    """Thin wrapper over ``Neo4jGraphManager`` for tool-style queries."""

    def __init__(self, neo4j_manager: Any):
        """
        Args:
            neo4j_manager: A ``Neo4jGraphManager`` instance (must be connected).
        """
        self._mgr = neo4j_manager

    # ────────────────────────────────────────────────────────
    # Tool implementations
    # ────────────────────────────────────────────────────────

    def detect_patterns(self, pattern_type: str = "all") -> List[Dict[str, Any]]:
        """Detect recurring patterns in the interview graph.

        Returns a list of pattern groups, each containing a type and items.
        """
        try:
            all_patterns = self._mgr.detect_patterns()
        except Exception:
            logger.debug("detect_patterns failed", exc_info=True)
            return []

        if pattern_type == "all":
            return all_patterns

        return [p for p in all_patterns if p.get("pattern_type") == pattern_type]

    def get_entity_context(
        self,
        entity_id: str,
        hop_count: int = 2,
    ) -> Dict[str, Any]:
        """Get the N-hop neighbourhood context around an entity.

        Returns the centre node, its neighbours at each hop level, and
        all relationships within range.
        """
        try:
            hop_count = max(1, min(hop_count, 5))
            result = self._mgr.get_entity_by_hop(entity_id, hop_count)

            # Truncate large result sets for LLM consumption.
            capped_neighbors: Dict[str, List] = {}
            for hop, nodes in result.get("neighbors_by_hop", {}).items():
                capped_neighbors[str(hop)] = nodes[:20]
            result["neighbors_by_hop"] = capped_neighbors
            result["relationships"] = result.get("relationships", [])[:50]

            return result
        except Exception:
            logger.debug("get_entity_context failed for %s", entity_id, exc_info=True)
            return {"error": f"Failed to query context for {entity_id}"}

    def check_node_conflict(
        self,
        existing_node_id: str,
        new_entity_name: str,
        new_entity_description: str,
    ) -> Dict[str, Any]:
        """Check if a new entity conflicts with an existing node.

        Returns conflict analysis with mergeability score and recommendation.
        """
        try:
            existing = self._mgr.get_node_by_id(existing_node_id)
            if not existing:
                return {
                    "found": False,
                    "recommendation": "new",
                    "reason": "Existing node not found — create new.",
                }

            existing_name = existing.get("name", "")
            existing_desc = existing.get("description", "")

            # Simple text overlap check.
            name_match = (
                existing_name.lower() in new_entity_name.lower()
                or new_entity_name.lower() in existing_name.lower()
            )

            # Check for factual contradiction by comparing key fields.
            conflicts: List[str] = []
            overlap_fields = []
            for field in ("time_frame", "location", "description"):
                old_val = str(existing.get(field, "")).strip()
                if not old_val:
                    continue
                new_val = new_entity_description if field == "description" else ""
                if new_val and old_val and old_val not in new_val and new_val not in old_val:
                    conflicts.append(f"{field}: existing='{old_val[:60]}' vs new='{new_val[:60]}'")
                else:
                    overlap_fields.append(field)

            if conflicts:
                return {
                    "found": True,
                    "conflict": True,
                    "mergeability": 0.3,
                    "recommendation": "conflict",
                    "conflicts": conflicts,
                    "reason": f"{len(conflicts)} field(s) contradict.",
                }

            if name_match:
                return {
                    "found": True,
                    "conflict": False,
                    "mergeability": 0.85,
                    "recommendation": "merge",
                    "overlap_fields": overlap_fields,
                    "reason": "Names match, no contradictions — merge.",
                }

            return {
                "found": True,
                "conflict": False,
                "mergeability": 0.5,
                "recommendation": "review",
                "reason": "Node exists but relationship unclear — manual review.",
            }
        except Exception:
            logger.debug("check_node_conflict failed", exc_info=True)
            return {"found": False, "recommendation": "error", "reason": "Query failed."}

    def query_graph_entities(
        self,
        entity_type: str = "all",
        query_text: str = "",
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search graph nodes by type and/or text.

        entity_type: "Event", "Person", "Location", "Emotion", "Topic", "all"
        """
        try:
            if query_text:
                return self._mgr.driver.query_by_text_similarity(
                    text=query_text,
                    entity_type=entity_type if entity_type != "all" else None,
                    max_results=max_results,
                )

            # No text query — return all nodes of the given type.
            if entity_type == "all":
                rows = self._mgr.driver.execute_query("MATCH (n) RETURN n.id, n.type, n.name LIMIT $max", {"max": max_results})
            else:
                rows = self._mgr.driver.execute_query(
                    f"MATCH (n:{entity_type}) RETURN n.id as id, n.type as type, n.name as name LIMIT $max",
                    {"max": max_results},
                )
            return rows or []
        except Exception:
            logger.debug("query_graph_entities failed", exc_info=True)
            return []

    def get_graph_summary(self) -> Dict[str, Any]:
        """Return overall graph statistics: node counts by type, relation counts."""
        try:
            return self._mgr.driver.get_graph_statistics()
        except Exception:
            logger.debug("get_graph_summary failed", exc_info=True)
            return {"error": "Graph unavailable"}


# ════════════════════════════════════════════════════════════════════
# OpenAI function-calling schema declarations
# ════════════════════════════════════════════════════════════════════

_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "detect_patterns",
            "description": "检测访谈图谱中的重复模式，例如出现在多个事件中的人物或反复出现的情感主题",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern_type": {
                        "type": "string",
                        "description": "模式类型：recurring_person（重复人物）、recurring_emotion（重复情感）、all（全部）",
                        "default": "all",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_context",
            "description": "查询图谱中某个实体的N-hop关联上下文，发现隐含关系",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "中心实体ID",
                    },
                    "hop_count": {
                        "type": "integer",
                        "description": "跳数（1-5），默认2",
                        "default": 2,
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_node_conflict",
            "description": "检查新实体与已有节点是否存在冲突或矛盾，返回合并建议",
            "parameters": {
                "type": "object",
                "properties": {
                    "existing_node_id": {
                        "type": "string",
                        "description": "已有节点ID",
                    },
                    "new_entity_name": {
                        "type": "string",
                        "description": "新实体名称",
                    },
                    "new_entity_description": {
                        "type": "string",
                        "description": "新实体描述",
                    },
                },
                "required": ["existing_node_id", "new_entity_name", "new_entity_description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_graph_entities",
            "description": "按类型和文本搜索图谱中的实体节点",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "实体类型：Event、Person、Location、Emotion、Topic、all",
                        "default": "all",
                    },
                    "query_text": {
                        "type": "string",
                        "description": "搜索文本（可选，留空则返回指定类型的所有节点）",
                        "default": "",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回数量",
                        "default": 10,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_graph_summary",
            "description": "获取图谱整体统计信息：各类型节点数量、关系数量等",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


def get_neo4j_tool_schemas() -> List[Dict[str, Any]]:
    """Return OpenAI function-call tool schemas for Neo4j queries."""
    return _TOOL_SCHEMAS


def get_neo4j_tool_callables(query_system: Neo4jQuerySystem) -> Dict[str, Any]:
    """Return name → callable mapping for Neo4j tools."""
    return {
        "detect_patterns": query_system.detect_patterns,
        "get_entity_context": query_system.get_entity_context,
        "check_node_conflict": query_system.check_node_conflict,
        "query_graph_entities": query_system.query_graph_entities,
        "get_graph_summary": query_system.get_graph_summary,
    }
