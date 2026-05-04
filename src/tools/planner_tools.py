"""Read-only planner tools for interviewer-side tool calling.

These tools expose compact evidence already available in GraphRAG decision
context.  They do not choose the next action; the LLM remains responsible for
weighing the evidence and producing ``planner_plan``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.services.graph_rag_decision_context import GraphRAGDecisionContext
from src.state import ElderProfile, TurnRecord
from src.tools.neo4j_tools import Neo4jQuerySystem


class PlannerToolSystem:
    def __init__(
        self,
        elder_profile: ElderProfile,
        recent_transcript: List[TurnRecord],
        decision_ctx: GraphRAGDecisionContext,
        neo4j_manager: Optional[Any] = None,
    ) -> None:
        self.elder_profile = elder_profile
        self.recent_transcript = list(recent_transcript or [])
        self.ctx = decision_ctx
        self._neo4j_manager = neo4j_manager
        self._neo4j_query = Neo4jQuerySystem(neo4j_manager) if neo4j_manager is not None else None

    @property
    def has_graph_tools(self) -> bool:
        return self._neo4j_query is not None

    def get_theme_coverage(self) -> Dict[str, Any]:
        coverage = dict(self.ctx.coverage_by_theme or {})
        undercovered = list(self.ctx.undercovered_themes or [])
        ranked = [
            {"theme_id": theme_id, "coverage": round(float(value or 0.0), 4)}
            for theme_id, value in sorted(coverage.items(), key=lambda item: item[1])
        ]
        return {
            "overall_coverage": round(float(self.ctx.overall_coverage or 0.0), 4),
            "current_focus_theme_id": self.ctx.current_focus_theme_id,
            "undercovered_themes": undercovered[:8],
            "lowest_coverage_themes": ranked[:8],
            "exhausted_themes": list(self.ctx.exhausted_themes or [])[:8],
        }

    def get_current_focus_snapshot(self) -> Dict[str, Any]:
        latest_turn = self.recent_transcript[-1] if self.recent_transcript else None
        return {
            "focus_rich_text": _truncate(self.ctx.focus_rich_text, 500),
            "focus_entity_id": self.ctx.focus_entity_id,
            "connected_people": list(self.ctx.connected_people or [])[:6],
            "connected_locations": list(self.ctx.connected_locations or [])[:5],
            "emotional_thread": self.ctx.emotional_thread,
            "explorable_angles": list(self.ctx.explorable_angles or [])[:6],
            "low_info_streak": int(self.ctx.low_info_streak or 0),
            "latest_question": getattr(latest_turn, "interviewer_question", "") if latest_turn else "",
            "latest_answer": _truncate(getattr(latest_turn, "interviewee_answer", ""), 360) if latest_turn else "",
            "do_not_repeat": list(self.ctx.do_not_repeat or [])[:3],
        }

    def assess_event_completeness(self) -> Dict[str, Any]:
        text = self._event_text()
        filled: List[str] = []
        weak: List[str] = []

        checks = {
            "time": self._has_time(text),
            "location": bool(self.ctx.connected_locations) or self._has_location_hint(text),
            "people": bool(self.ctx.connected_people) or self._has_people_hint(text),
            "sequence": self._has_sequence(text),
            "cause": any(token in text for token in ("因为", "原因", "为了", "由于", "所以")),
            "result": any(token in text for token in ("后来", "结果", "最后", "影响", "变成", "就这样")),
            "feeling": bool(self.ctx.emotional_thread) or self._has_feeling_hint(text),
            "reflection": any(token in text for token in ("现在想", "回头看", "觉得", "明白", "人生", "一辈子", "最重要")),
        }
        for name, present in checks.items():
            if present:
                filled.append(name)
            elif name in {"cause", "result", "reflection"} and len(text) >= 80:
                weak.append(name)

        dimensions = list(checks.keys())
        missing = [name for name in dimensions if name not in filled and name not in weak]
        score = (len(filled) + 0.5 * len(weak)) / max(1, len(dimensions))
        recommended = self._recommended_probe_dimensions(missing, weak)

        return {
            "score": round(min(max(score, 0.0), 1.0), 3),
            "filled_dimensions": filled,
            "weak_dimensions": weak,
            "missing_dimensions": missing,
            "recommended_probe_dimensions": recommended,
            "evidence_excerpt": _truncate(text, 240),
        }

    def retrieve_related_context(self, query: str = "") -> Dict[str, Any]:
        return {
            "query": query,
            "graph_rag_context": _truncate(self.ctx.graph_rag_context, 700),
            "cross_session_summary": _truncate(self.ctx.cross_session_summary, 400),
            "cross_session_open_loops": list(self.ctx.cross_session_open_loops or [])[:5],
        }

    def detect_open_loops_and_conflicts(self) -> Dict[str, Any]:
        loops = list(self.ctx.explorable_angles or [])[:6]
        loops.extend(list(self.ctx.cross_session_open_loops or [])[:4])
        return {
            "open_loops": loops[:8],
            "possible_conflicts": [],
            "do_not_repeat": list(self.ctx.do_not_repeat or [])[:3],
            "low_info_streak": int(self.ctx.low_info_streak or 0),
        }

    def get_entity_context(self, entity_id: str = "", hop_count: int = 2) -> Dict[str, Any]:
        if self._neo4j_query is None:
            return {"error": "graph tools unavailable"}
        entity_id = (entity_id or self.ctx.focus_entity_id or "").strip()
        if not entity_id:
            return {
                "error": "entity_id is required and no current focus entity is available",
                "focus_entity_id": self.ctx.focus_entity_id,
            }
        result = self._neo4j_query.get_entity_context(entity_id, hop_count=hop_count)
        return _compact_graph_context(result)

    def query_graph_entities(
        self,
        entity_type: str = "all",
        query_text: str = "",
        max_results: int = 8,
    ) -> List[Dict[str, Any]]:
        if self._neo4j_query is None:
            return [{"error": "graph tools unavailable"}]
        rows = self._neo4j_query.query_graph_entities(
            entity_type=entity_type,
            query_text=query_text,
            max_results=max(1, min(int(max_results or 8), 12)),
        )
        return [_compact_node(row) for row in rows[:12]]

    def detect_graph_patterns(self, pattern_type: str = "all") -> List[Dict[str, Any]]:
        if self._neo4j_query is None:
            return [{"error": "graph tools unavailable"}]
        patterns = self._neo4j_query.detect_patterns(pattern_type=pattern_type)
        return [_compact_pattern(item) for item in patterns[:8]]

    def get_graph_summary(self) -> Dict[str, Any]:
        if self._neo4j_query is None:
            return {"error": "graph tools unavailable"}
        return self._neo4j_query.get_graph_summary()

    def get_theme_detail(self, theme_id: str = "") -> Dict[str, Any]:
        if self._neo4j_manager is None:
            return {"error": "graph tools unavailable"}
        theme_id = (theme_id or self.ctx.current_focus_theme_id or "").strip()
        if not theme_id:
            return {"error": "theme_id is required and no current focus theme is available"}
        try:
            topic = self._neo4j_manager.get_topic(theme_id)
        except Exception:
            return {"error": f"failed to query theme {theme_id}"}
        if not topic:
            return {"found": False, "theme_id": theme_id}
        return {
            "found": True,
            "theme_id": theme_id,
            "title": topic.get("title") or topic.get("name"),
            "status": topic.get("status"),
            "priority": topic.get("priority"),
            "domain": topic.get("domain"),
            "description": _truncate(topic.get("description"), 360),
            "exploration_depth": topic.get("exploration_depth"),
        }

    def _event_text(self) -> str:
        parts = [self.ctx.focus_rich_text or ""]
        if self.recent_transcript:
            parts.append(self.recent_transcript[-1].interviewee_answer or "")
        return "\n".join(part for part in parts if part).strip()

    @staticmethod
    def _has_time(text: str) -> bool:
        return bool(re.search(r"\d{4}年|\d{1,2}岁|小时候|年轻|后来|当时|那年|以前|现在", text or ""))

    @staticmethod
    def _has_location_hint(text: str) -> bool:
        return any(token in text for token in ("家", "村", "城", "厂", "学校", "成都", "街", "院", "地方", "那里"))

    @staticmethod
    def _has_people_hint(text: str) -> bool:
        return any(token in text for token in ("父", "母", "爸", "妈", "哥", "姐", "弟", "妹", "老师", "同事", "朋友", "孩子", "老伴"))

    @staticmethod
    def _has_sequence(text: str) -> bool:
        return len(text or "") >= 45 or any(token in text for token in ("先", "然后", "后来", "接着", "那时候"))

    @staticmethod
    def _has_feeling_hint(text: str) -> bool:
        return any(token in text for token in ("开心", "高兴", "难过", "辛苦", "害怕", "自豪", "遗憾", "喜欢", "舍不得"))

    @staticmethod
    def _recommended_probe_dimensions(missing: List[str], weak: List[str]) -> List[str]:
        priority = ["feeling", "people", "location", "result", "cause", "reflection", "time", "sequence"]
        candidates = list(missing) + list(weak)
        return [name for name in priority if name in candidates][:3]


def _truncate(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _compact_node(node: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(node, dict):
        return {"value": _truncate(node, 220)}
    return {
        "id": node.get("id") or node.get("n.id") or node.get("node_id"),
        "type": node.get("type") or node.get("n.type"),
        "name": node.get("name") or node.get("n.name") or node.get("title"),
        "description": _truncate(node.get("description") or node.get("summary"), 260),
        "score": node.get("score") or node.get("similarity_score"),
    }


def _compact_graph_context(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {"value": _truncate(result, 400)}
    if result.get("error"):
        return {"error": result.get("error")}
    neighbors = result.get("neighbors_by_hop") or {}
    compact_neighbors: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(neighbors, dict):
        for hop, nodes in neighbors.items():
            compact_neighbors[str(hop)] = [_compact_node(node) for node in list(nodes or [])[:8]]
    return {
        "center": _compact_node(result.get("center") or {}),
        "neighbors_by_hop": compact_neighbors,
        "relationships": list(result.get("relationships") or [])[:16],
    }


def _compact_pattern(pattern: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(pattern, dict):
        return {"value": _truncate(pattern, 300)}
    compact = dict(pattern)
    for key in ("items", "events", "nodes"):
        if isinstance(compact.get(key), list):
            compact[key] = compact[key][:8]
    return compact


def get_planner_tool_schemas(include_graph_tools: bool = False) -> List[Dict[str, Any]]:
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "get_theme_coverage",
                "description": "获取当前人生主题覆盖情况，用于判断是否需要继续当前主题或自然切换方向。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_focus_snapshot",
                "description": "获取当前叙事焦点、相关人物地点、待探索线索和最近问答摘要。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "assess_event_completeness",
                "description": "评估当前事件在时间、地点、人物、经过、原因、结果、感受、反思上的完整度。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "retrieve_related_context",
                "description": "读取当前 GraphRAG 相关上下文和跨会话开放线索，可传入自然语言查询说明。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "想要核对或联想的自然语言查询，可为空。",
                            "default": "",
                        }
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "detect_open_loops_and_conflicts",
                "description": "获取尚未展开的线索、可能需要避免重复的问题和低信息轮次提示。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    if not include_graph_tools:
        return schemas

    schemas.extend(
        [
            {
                "type": "function",
                "function": {
                    "name": "get_entity_context",
                    "description": "查询当前或指定图谱实体的 1-3 跳关联，用于沿人物、地点、事件关系自然延展。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entity_id": {
                                "type": "string",
                                "description": "中心实体 ID；为空时尝试使用当前焦点实体。",
                                "default": "",
                            },
                            "hop_count": {
                                "type": "integer",
                                "description": "查询跳数，建议 1-2。",
                                "default": 2,
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_graph_entities",
                    "description": "按类型和文本搜索图谱实体，适合在跳转前核对人物、地点、事件或主题。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entity_type": {
                                "type": "string",
                                "description": "Event、Person、Location、Emotion、Topic 或 all。",
                                "default": "all",
                            },
                            "query_text": {
                                "type": "string",
                                "description": "搜索文本，可为空。",
                                "default": "",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "最大返回数量。",
                                "default": 8,
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "detect_graph_patterns",
                    "description": "检测图谱中重复出现的人物、情绪或主题模式，用于寻找自然延展方向。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern_type": {
                                "type": "string",
                                "description": "recurring_person、recurring_emotion 或 all。",
                                "default": "all",
                            }
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_graph_summary",
                    "description": "获取图谱节点和关系统计，用于判断当前访谈图谱是否稀疏。",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_theme_detail",
                    "description": "读取当前或指定主题节点详情，用于理解主题状态、优先级和探索深度。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "theme_id": {
                                "type": "string",
                                "description": "主题 ID；为空时使用当前焦点主题。",
                                "default": "",
                            }
                        },
                        "required": [],
                    },
                },
            },
        ]
    )
    return schemas


def get_planner_tool_callables(system: PlannerToolSystem) -> Dict[str, Any]:
    callables = {
        "get_theme_coverage": system.get_theme_coverage,
        "get_current_focus_snapshot": system.get_current_focus_snapshot,
        "assess_event_completeness": system.assess_event_completeness,
        "retrieve_related_context": system.retrieve_related_context,
        "detect_open_loops_and_conflicts": system.detect_open_loops_and_conflicts,
    }
    if system.has_graph_tools:
        callables.update(
            {
                "get_entity_context": system.get_entity_context,
                "query_graph_entities": system.query_graph_entities,
                "detect_graph_patterns": system.detect_graph_patterns,
                "get_graph_summary": system.get_graph_summary,
                "get_theme_detail": system.get_theme_detail,
            }
        )
    return callables
