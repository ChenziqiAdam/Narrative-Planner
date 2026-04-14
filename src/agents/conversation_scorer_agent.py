from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from openai import OpenAI

from src.config import Config

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover
    def repair_json(text: str) -> str:
        return text


logger = logging.getLogger(__name__)


class ConversationScorerAgent:
    """
    LLM-based holistic scorer for interview conversation quality.

    Output schema:
    {
      "scores": {
        "narrative_coherence": 0-1,
        "emotional_depth": 0-1,
        "question_effectiveness": 0-1,
        "non_redundancy": 0-1,
        "topic_coverage_quality": 0-1,
        "overall": 0-1
      },
      "summary": "...",
      "strengths": ["..."],
      "weaknesses": ["..."],
      "suggestions": ["..."]
    }
    """

    SCORE_KEYS = (
        "narrative_coherence",
        "emotional_depth",
        "question_effectiveness",
        "non_redundancy",
        "topic_coverage_quality",
        "overall",
    )

    def __init__(self):
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.model = Config.get_model_name("structured")

    def score(
        self,
        transcript_text: str,
        deterministic_context: Dict[str, Any],
        max_chars: int = 8000,
    ) -> Dict[str, Any]:
        truncated = (transcript_text or "")[:max_chars]
        system_prompt = (
            "你是访谈质量评估员。请根据对话内容给出严格 JSON。"
            "分数范围是0到1，越高越好。"
            "避免夸张，不要输出JSON以外内容。"
        )
        user_payload = {
            "task": "评估访谈整体质量",
            "scoring_dimensions": list(self.SCORE_KEYS),
            "deterministic_context": deterministic_context,
            "transcript": truncated,
            "output_schema": {
                "scores": {key: "float(0-1)" for key in self.SCORE_KEYS},
                "summary": "string",
                "strengths": ["string"],
                "weaknesses": ["string"],
                "suggestions": ["string"],
            },
        }

        raw = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            max_tokens=1200,
        ).choices[0].message.content or ""

        return self._parse(raw)

    def _parse(self, text: str) -> Dict[str, Any]:
        payload = (text or "").strip()
        if "```json" in payload:
            payload = payload.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in payload:
            payload = payload.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            parsed = json.loads(repair_json(payload))
        except Exception as exc:
            raise ValueError(f"ConversationScorerAgent parse failed: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ValueError("ConversationScorerAgent returned non-dict JSON.")

        scores = parsed.get("scores", {})
        if not isinstance(scores, dict):
            raise ValueError("ConversationScorerAgent missing scores dict.")

        normalized_scores: Dict[str, float] = {}
        for key in self.SCORE_KEYS:
            value = scores.get(key, 0.0)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = 0.0
            normalized_scores[key] = max(0.0, min(1.0, numeric))

        return {
            "scores": normalized_scores,
            "summary": str(parsed.get("summary", "")).strip(),
            "strengths": [str(item) for item in parsed.get("strengths", []) if str(item).strip()][:5],
            "weaknesses": [str(item) for item in parsed.get("weaknesses", []) if str(item).strip()][:5],
            "suggestions": [str(item) for item in parsed.get("suggestions", []) if str(item).strip()][:5],
        }

    def safe_score(
        self,
        transcript_text: str,
        deterministic_context: Dict[str, Any],
        max_chars: int = 8000,
    ) -> Optional[Dict[str, Any]]:
        try:
            return self.score(transcript_text, deterministic_context, max_chars=max_chars)
        except Exception as exc:  # pragma: no cover
            logger.warning("ConversationScorerAgent failed: %s", exc)
            return None
