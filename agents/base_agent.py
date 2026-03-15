import json
import logging
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config
from openai import OpenAI

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(self, system_prompt, tools=None, tool_callables=None):
        self.client = OpenAI(api_key=Config.MOONSHOT_API_KEY, base_url=Config.MOONSHOT_BASE_URL)
        self.system_prompt = system_prompt
        self.tools = tools  # list of OpenAI function schemas (dicts)
        self.tool_callables = tool_callables or {}  # {name: callable}
        self.conversation_history = [{"role": "system", "content": system_prompt}]

    def step(self, user_message) -> str:
        """Single-turn: append user message, call API (with tool loop), return final text."""
        self.conversation_history.append({"role": "user", "content": user_message})
        history_len = len(self.conversation_history)
        logger.debug(f"[step] user message ({len(user_message)} chars) | history depth: {history_len}")

        call_count = 0
        while True:
            call_count += 1
            kwargs = {"model": Config.MODEL_NAME, "messages": self.conversation_history}
            if self.tools:
                kwargs["tools"] = self.tools
                kwargs["tool_choice"] = "auto"

            logger.debug(
                f"[API call #{call_count}] model={Config.MODEL_NAME} "
                f"messages={len(self.conversation_history)} tools={len(self.tools) if self.tools else 0}"
            )
            response = self.client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            usage = response.usage
            logger.debug(
                f"[API call #{call_count}] finish_reason={response.choices[0].finish_reason} "
                f"prompt_tokens={usage.prompt_tokens} completion_tokens={usage.completion_tokens}"
            )

            if message.tool_calls:
                self.conversation_history.append(message.model_dump(exclude_unset=True))
                for tc in message.tool_calls:
                    fn_name = tc.function.name
                    fn_args = json.loads(tc.function.arguments)
                    logger.info(f"[tool call] {fn_name}({fn_args})")
                    callable_fn = self.tool_callables.get(fn_name)
                    if callable_fn:
                        result = callable_fn(**fn_args)
                        logger.debug(f"[tool result] {fn_name} → {str(result)[:200]}")
                    else:
                        result = f"Unknown tool: {fn_name}"
                        logger.warning(f"[tool call] unknown tool: {fn_name}")
                    self.conversation_history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                content = message.content or ""
                self.conversation_history.append({"role": "assistant", "content": content})
                logger.debug(f"[step] final response ({len(content)} chars) after {call_count} API call(s)")
                return content

    def reset(self):
        """Reset conversation history to just the system prompt."""
        self.conversation_history = [{"role": "system", "content": self.system_prompt}]
        logger.debug("[reset] conversation history cleared")
