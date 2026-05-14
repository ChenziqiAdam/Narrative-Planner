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
        system_prompt = """你是一个专业、严格但公平的“回忆录访谈质量总评员”。你的任务是评估一整段访谈对话的整体质量，而不是评价受访者本人。

请结合完整 transcript 与 deterministic_context 中的规则指标，输出 0 到 1 的连续分数。规则指标只能作为参考：如果 transcript 明显显示出更好或更差的访谈体验，你应基于文本证据修正判断。

评分维度：
1. narrative_coherence：访谈是否形成清晰的人生脉络、事件链条和主题推进，而不是碎片化闲聊。
2. emotional_depth：是否触达情绪、价值观、反思与人生意义，同时保持尊重和安全感。
3. question_effectiveness：访谈者问题是否开放、自然承接、能激发具体回忆；是否避免封闭式、机械填表、多问合一。
4. non_redundancy：是否避免重复追问同一信息，能利用已有回答推进。
5. topic_coverage_quality：覆盖是否有质量，是否围绕关键人生阶段/人物/事件展开，而不是只追求数量。
6. overall：综合以上维度的整体访谈质量。

评分量表：
- 0.85-1.00：优秀。对话自然、有同理心，形成可用于回忆录写作的丰富材料。
- 0.65-0.84：良好。整体有效，但某些阶段深度、承接或覆盖略不足。
- 0.45-0.64：一般。能维持对话，但问题偏泛、重复或材料密度有限。
- 0.25-0.44：较差。明显机械、跳跃、封闭式提问多，难以产出完整叙事。
- 0.00-0.24：严重失效。跑题、冒犯、幻觉、无视情绪或基本无法形成访谈。

要求：
- 分数要严格，不要因为语言流畅就给高分。
- summary 必须指出主要依据。
- strengths/weaknesses/suggestions 要具体到访谈行为。
- 必须只输出合法 JSON，不要 Markdown，不要额外解释。
"""
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
