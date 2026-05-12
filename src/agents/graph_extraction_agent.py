"""GraphExtractionAgent — 自由格式图谱提取 Agent。

从访谈对话中提取实体和关系，不使用固定槽位 schema。
替代原有的 ExtractionAgent (8槽位机制)。
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import Config
from src.state import SessionState, TurnRecord
from src.state.narrative_models import (
    ExtractedEntity,
    ExtractedRelationship,
    GraphExtraction,
    NarrativeFragment,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "graph_extraction_prompt_v1.md"


class GraphExtractionAgent:
    """从对话中自由提取实体和关系，构建知识图谱。"""

    def __init__(self) -> None:
        self._prompt_template: Optional[str] = None
        self._client = None
        self.last_prompt_chars: int = 0
        self.last_input_chars: Dict[str, int] = {}

    def _load_prompt_template(self) -> str:
        if getattr(Config, "GRAPH_EXTRACTION_COMPACT_PROMPT", True):
            return self._compact_prompt()
        if self._prompt_template is None:
            if _PROMPT_PATH.exists():
                self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
            else:
                self._prompt_template = self._default_prompt()
        return self._prompt_template

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(**Config.get_openai_client_kwargs())
        return self._client

    async def extract(
        self,
        state: SessionState,
        turn_record: TurnRecord,
        graph_context: Optional[str] = None,
        neo4j_manager: Optional[Any] = None,
    ) -> GraphExtraction:
        """从当前对话轮次中提取图谱实体和关系。"""
        prompt = self._build_prompt(state, turn_record, graph_context, neo4j_manager)
        response_text, _extraction_usage = self._call_llm(prompt)

        if not response_text:
            return self._build_fallback_extraction(turn_record), {}

        extraction = self._parse_response(response_text)
        if extraction is None:
            return self._build_fallback_extraction(turn_record), {}

        return extraction, _extraction_usage

    def _build_prompt(
        self,
        state: SessionState,
        turn_record: TurnRecord,
        graph_context: Optional[str] = None,
        neo4j_manager: Optional[Any] = None,
    ) -> str:  # noqa: ARG002 graph_context kept for call-site compat
        """组装提取 prompt 的输入 JSON。"""
        max_turn_chars = max(300, int(getattr(Config, "GRAPH_EXTRACTION_MAX_TURN_CHARS", 1200)))
        current_turn = {
            "interviewer": self._clip_text(turn_record.interviewer_question or "", max_turn_chars),
            "respondent": self._clip_text(turn_record.interviewee_answer or "", max_turn_chars),
        }

        context = []
        context_limit = max(0, int(getattr(Config, "GRAPH_EXTRACTION_CONTEXT_TURNS", 1)))
        for turn in state.recent_transcript(context_limit):
            context.append({
                "turn": -(context_limit - len(context)),
                "interviewer": self._clip_text(turn.interviewer_question or "", max_turn_chars),
                "respondent": self._clip_text(turn.interviewee_answer or "", max_turn_chars),
            })

        existing_context = []
        max_graph_context_chars = max(
            0,
            int(getattr(Config, "GRAPH_EXTRACTION_MAX_GRAPH_CONTEXT_CHARS", 1500)),
        )
        existing_context_chars = 0

        # 从 Neo4j 查询该老人的已有实体摘要；按字符预算截断，避免 extraction prompt 随图谱增长而膨胀。
        if neo4j_manager and max_graph_context_chars > 0:
            try:
                profile = getattr(state, "elder_profile", None)
                if profile:
                    elder_id = f"{getattr(profile, 'name', '')}_{getattr(profile, 'birth_year', '')}"
                    all_entities = neo4j_manager.get_entities_by_elder(elder_id)
                    for ent in all_entities[:60]:
                        item = {
                            "id": ent.get("id", ""),
                            "entity_type": ent.get("type", ""),
                            "name": ent.get("name", ""),
                            "description": self._clip_text(ent.get("description") or "", 80),
                        }
                        item_chars = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
                        if existing_context_chars + item_chars > max_graph_context_chars:
                            break
                        existing_context.append(item)
                        existing_context_chars += item_chars
            except Exception:
                logger.debug("Failed to query existing entities for extraction context", exc_info=True)

        if graph_context and existing_context_chars < max_graph_context_chars:
            raw_context = self._clip_text(graph_context, max_graph_context_chars - existing_context_chars)
            existing_context.append({"raw_context": raw_context})
            existing_context_chars += len(raw_context)

        input_data = {
            "current_turn": current_turn,
            "context": context,
            "existing_graph_context": existing_context,
        }

        template = self._load_prompt_template()
        input_json = json.dumps(input_data, ensure_ascii=False, separators=(",", ":"))
        prompt = f"{template}\n\n## 当前输入\n```json\n{input_json}\n```"
        self.last_prompt_chars = len(prompt)
        self.last_input_chars = {
            "prompt_chars": len(prompt),
            "template_chars": len(template),
            "input_json_chars": len(input_json),
            "current_question_chars": len(current_turn["interviewer"]),
            "current_answer_chars": len(current_turn["respondent"]),
            "context_turns": len(context),
            "graph_context_chars": existing_context_chars,
        }
        return prompt

    def _call_llm(self, prompt: str) -> tuple:
        """调用 LLM 获取提取结果。Returns (response_text, usage_dict)."""
        try:
            client = self._get_client()
            model = Config.EXTRACTOR_MODEL_NAME
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是叙事提取助手。只输出 JSON，不要其他文字。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max(400, int(getattr(Config, "GRAPH_EXTRACTION_MAX_OUTPUT_TOKENS", 1200))),
                temperature=0.2,
            )
            _usage: dict = {}
            if response.usage:
                _usage = {
                    "prompt_tokens": response.usage.prompt_tokens or 0,
                    "completion_tokens": response.usage.completion_tokens or 0,
                }
            return response.choices[0].message.content or "", _usage
        except Exception:
            logger.exception("Graph extraction LLM call failed")
            return "", {}

    def _parse_response(self, text: str) -> Optional[GraphExtraction]:
        """解析 LLM 返回的 JSON。"""
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse extraction JSON")
            return None

        if not data.get("has_content", True) and not data.get("entities"):
            return GraphExtraction(
                narrative_summary=data.get("narrative_summary", ""),
                open_loops=data.get("open_loops", []),
                confidence=data.get("confidence", 0.0),
            )

        entities = []
        for e in data.get("entities", []):
            action = e.get("merge_action", "new")
            if action not in ("new", "update", "skip"):
                action = "new"
            entities.append(ExtractedEntity(
                entity_type=e.get("entity_type", "Event"),
                name=e.get("name", ""),
                description=e.get("description", ""),
                properties=e.get("properties", {}),
                merge_action=action,
                merge_target_id=e.get("merge_target_id"),
            ))

        relationships = []
        for r in data.get("relationships", []):
            relationships.append(ExtractedRelationship(
                source_name=r.get("source_name", ""),
                target_name=r.get("target_name", ""),
                relation_type=r.get("relation_type", "RELATES_TO"),
                properties=r.get("properties", {}),
            ))

        return GraphExtraction(
            entities=entities,
            relationships=relationships,
            narrative_summary=data.get("narrative_summary", ""),
            open_loops=data.get("open_loops", []),
            emotional_state=data.get("emotional_state"),
            confidence=data.get("confidence", 0.5),
        )

    def _build_fallback_extraction(self, turn_record: TurnRecord) -> GraphExtraction:
        """当 LLM 提取失败时的降级处理。"""
        answer = (turn_record.interviewee_answer or "").strip()
        if len(answer) < 25:
            return GraphExtraction()

        # 尝试从回答中提取最基本的实体
        event_desc = answer[:120]
        entities = []
        properties: Dict[str, Any] = {}

        time_hint = self._extract_time_hint(answer)
        if time_hint:
            properties["time_anchor"] = time_hint

        location_hint = self._extract_location_hint(answer)
        if location_hint:
            properties["location"] = location_hint

        if event_desc:
            entities.append(ExtractedEntity(
                entity_type="Event",
                name=event_desc[:20],
                description=event_desc,
                properties=properties,
            ))

        return GraphExtraction(
            entities=entities,
            narrative_summary=event_desc,
            confidence=0.25,
        )

    @staticmethod
    def _extract_time_hint(text: str) -> Optional[str]:
        match = re.search(r"(?:18|19|20)\d{2}年?(?:\d{1,2}月)?", text)
        if match:
            return match.group(0)
        for pattern in [r"\d{1,2}岁(?:那年)?", "小时候", "年轻时候", "后来", "当时"]:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def _extract_location_hint(text: str) -> Optional[str]:
        match = re.search(r"在([^，。；]{2,18}(?:厂|学校|车间|村|县|城|站|家))", text)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        text = text or ""
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."

    @staticmethod
    def _compact_prompt() -> str:
        return """# 叙事图谱提取器

你从当前访谈轮次中抽取明确出现的人生叙事实体和关系。只输出 JSON，不输出解释。

## 实体类型
- Event: 具体经历、转折、场景或可继续追问的事件
- Person: 明确提到的人物或关系称呼
- Location: 明确地点
- Emotion: 老人明确表达或强烈暗示的情绪
- Insight: 明确的人生感悟、回望、评价

## 关系类型
- PARTICIPATES_IN: Person -> Event
- LOCATED_AT: Event -> Location
- TRIGGERS / CAUSES: 事件、情绪或洞见之间的触发/因果
- TEMPORAL_NEXT: Event -> Event 的时间先后
- FAMILY_OF / KNOWS: 人物关系
- RELATES_TO: 其他明确关联

## 规则
- 只提取老人明确说出的内容，不补历史背景，不编造。
- 当前轮优先；上下文只用于消解“他/那里/那时候”等指代。
- 已有图谱上下文只用于避免重复命名或补充已有实体。
- 实体 name 要短，description 用一句话，properties 只放明确字段。
- 信息很少时可返回 has_content=false 和空数组。

## 输出 JSON
{
  "has_content": true,
  "entities": [
    {
      "entity_type": "Event|Person|Location|Emotion|Insight",
      "name": "短名称",
      "description": "一句话描述",
      "properties": {
        "time_anchor": "可选",
        "location": "可选",
        "people": ["可选"],
        "emotional_tone": "可选",
        "significance": "可选"
      }
    }
  ],
  "relationships": [
    {
      "source_name": "源实体名称",
      "target_name": "目标实体名称",
      "relation_type": "关系类型",
      "properties": {}
    }
  ],
  "narrative_summary": "1句话概括",
  "open_loops": ["值得追问的问题"],
  "emotional_state": "可选",
  "confidence": 0.0
}"""

    @staticmethod
    def _default_prompt() -> str:
        return """# 叙事提取助手

从老人的访谈对话中提取实体和关系。

## 输出格式
返回 JSON:
{
  "has_content": true,
  "entities": [{"entity_type": "Event|Person|Location|Emotion|Insight", "name": "...", "description": "...", "properties": {}}],
  "relationships": [{"source_name": "...", "target_name": "...", "relation_type": "..."}],
  "narrative_summary": "...",
  "open_loops": ["..."],
  "confidence": 0.85
}

所有字段可选，有什么提什么。"""

    def query_memory(
        self,
        query: str,
        session_id: str,
        neo4j_manager: Optional[Any] = None,
        entity_vector_store: Optional[Any] = None,
    ) -> str:
        """Query graph RAG memory for retrieval context.
        
        This method is called by the decision context builder when
        QUERY_OPTIMIZATION_ENABLED is True, consolidating memory queries
        through the extraction agent.
        
        Args:
            query: User's latest response or question
            session_id: Current session ID
            neo4j_manager: Neo4j connection for graph queries
            entity_vector_store: Vector store for semantic search
            
        Returns:
            Formatted prompt text with retrieved context
        """
        if neo4j_manager is None or entity_vector_store is None:
            logger.debug("query_memory: missing neo4j_manager or entity_vector_store")
            return ""
        
        try:
            # Import HybridRetriever locally to avoid circular imports
            from src.services.hybrid_retriever import HybridRetriever
            
            retriever = HybridRetriever(
                neo4j_manager=neo4j_manager,
                entity_vector_store=entity_vector_store,
            )
            result = retriever.retrieve(query, session_id, max_tokens=400)
            
            logger.info(
                "Memory query succeeded: %d entities, %.1f ms",
                len(result.entities), result.latency_ms
            )
            return result.prompt_text or ""
        except Exception as exc:
            logger.warning("Memory query failed for session %s: %s", session_id, exc, exc_info=True)
            return ""

    async def close(self) -> None:
        pass
