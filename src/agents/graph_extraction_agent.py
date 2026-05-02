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

    def _load_prompt_template(self) -> str:
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
    ) -> GraphExtraction:
        """从当前对话轮次中提取图谱实体和关系。"""
        prompt = self._build_prompt(state, turn_record, graph_context)
        response_text = self._call_llm(prompt)

        if not response_text:
            return self._build_fallback_extraction(turn_record)

        extraction = self._parse_response(response_text)
        if extraction is None:
            return self._build_fallback_extraction(turn_record)

        return extraction

    def _build_prompt(
        self,
        state: SessionState,
        turn_record: TurnRecord,
        graph_context: Optional[str] = None,
    ) -> str:
        """组装提取 prompt 的输入 JSON。"""
        current_turn = {
            "interviewer": turn_record.interviewer_question or "",
            "respondent": turn_record.interviewee_answer or "",
        }

        context = []
        for turn in state.recent_transcript(3):
            context.append({
                "turn": -(3 - len(context)),
                "interviewer": turn.interviewer_question or "",
                "respondent": turn.interviewee_answer or "",
            })

        existing_context = []
        if graph_context:
            existing_context.append({"raw_context": graph_context})

        input_data = {
            "current_turn": current_turn,
            "context": context,
            "existing_graph_context": existing_context,
        }

        template = self._load_prompt_template()
        return f"{template}\n\n## 当前输入\n```json\n{json.dumps(input_data, ensure_ascii=False, indent=2)}\n```"

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM 获取提取结果。"""
        try:
            client = self._get_client()
            model = Config.EXTRACTOR_MODEL_NAME
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是叙事提取助手。只输出 JSON，不要其他文字。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception:
            logger.exception("Graph extraction LLM call failed")
            return ""

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
            entities.append(ExtractedEntity(
                entity_type=e.get("entity_type", "Event"),
                name=e.get("name", ""),
                description=e.get("description", ""),
                properties=e.get("properties", {}),
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

    async def close(self) -> None:
        pass
