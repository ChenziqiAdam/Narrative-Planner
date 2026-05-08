"""Compress old conversation turns into a concise summary to stay within token limits."""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from src.config import Config
from src.services.llm_retry import is_transient_llm_error, sleep_before_retry

logger = logging.getLogger(__name__)

SUMMARIZATION_SYSTEM_PROMPT = """\
你是一位专业的访谈记录整理助手。你的任务是将一段访谈对话历史压缩成结构化的摘要。

请按以下格式输出（如果已有旧摘要，请与新对话整合为一份更新后的摘要）：

【话题脉络】按时间顺序列出已讨论的主要话题（每条一句话）
【关键事实】受访者提到的人名、地名、时间节点、重要事件
【情感走向】受访者的情绪变化轨迹
【叙事进展】故事推进到了哪个阶段、当前焦点

要求：
- 只从原文中提取事实，不要编造
- 每个板块内容简洁，合并同类信息
- 总字数控制在400-600字"""


class HistoryCompressor:
    """Compress old Q/A turns into a short summary via an LLM call."""

    def __init__(
        self,
        client: OpenAI,
        model_candidates: list[str] | None = None,
    ) -> None:
        self.client = client
        self.model_candidates = model_candidates or Config.get_model_candidates("summarizer")
        self.max_retries = max(1, Config.MAX_RETRIES)

    # ── Public API ──────────────────────────────────────────────────────────

    def compress_qa_pairs(
        self,
        old_turns: list[dict[str, str]],
        existing_summary: str = "",
    ) -> str:
        """Compress a list of ``{"question": ..., "answer": ...}`` dicts.

        Returns the new summary string, or an empty string on failure (graceful
        degradation — caller keeps old summary and more original turns).
        """
        turns_text = "\n".join(
            f"问：{t['question']}\n答：{t['answer']}" for t in old_turns
        )
        user_content = self._build_user_content(turns_text, existing_summary)
        return self._call_llm(user_content)

    def compress_messages(
        self,
        old_messages: list[dict[str, str]],
    ) -> str:
        """Compress old user/assistant message pairs into a summary string."""
        parts: list[str] = []
        for msg in old_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            prefix = "访谈者" if role == "assistant" else "受访者"
            parts.append(f"{prefix}：{content}")
        turns_text = "\n".join(parts)
        return self._call_llm(turns_text)

    # ── Internals ───────────────────────────────────────────────────────────

    def _build_user_content(self, turns_text: str, existing_summary: str) -> str:
        parts: list[str] = []
        if existing_summary:
            parts.append(f"之前的对话摘要：\n{existing_summary}\n")
        parts.append(f"以下是新的对话记录，请一并整合为更新后的摘要：\n{turns_text}")
        return "\n".join(parts)

    def _call_llm(self, user_content: str) -> str:
        messages = [
            {"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        last_error: Exception | None = None
        for model_name in self.model_candidates:
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        max_tokens=1024,
                    )
                    summary = (response.choices[0].message.content or "").strip()
                    if summary:
                        logger.info(
                            "History compressed with model=%s (%d chars → %d chars)",
                            model_name,
                            len(user_content),
                            len(summary),
                        )
                        return summary
                except Exception as exc:
                    last_error = exc
                    if is_transient_llm_error(exc):
                        if attempt < self.max_retries:
                            sleep_before_retry(exc, attempt)
                            continue
                        break
                    logger.warning("History compression failed with model=%s: %s", model_name, exc)
                    break
        if last_error:
            logger.warning("All summarization attempts failed: %s", last_error)
        return ""
