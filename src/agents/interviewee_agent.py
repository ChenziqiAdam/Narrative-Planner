import json
import logging
import os
import re
import sys
from copy import deepcopy
from datetime import datetime
from typing import Any

from openai import OpenAI

try:
    from json_repair import repair_json
except ImportError:  # pragma: no cover - optional until dependencies are installed
    repair_json = None

project_root = os.path.join(os.path.dirname(__file__), "..", "..")
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.config import Config
from src.prompts.roles.elderly_promot import ElderPromptGenerator
from src.services.history_compressor import HistoryCompressor
from src.services.llm_retry import is_transient_llm_error, sleep_before_retry
from src.tools.elder_tools import ElderMemorySystem, get_tool_callables, get_tool_schemas

logger = logging.getLogger(__name__)


REPLY_KEYS = ("reply", "response", "answer")
DEFAULT_REPLY_FALLBACK = "这个问题我得再想想。"


def _strip_code_fences(raw: str) -> str:
    return re.sub(r"```(?:json)?|```", "", raw or "").strip()


def _parse_json_like(raw: str) -> Any | None:
    cleaned = _strip_code_fences(raw)
    if not cleaned:
        return None

    parse_candidates = [cleaned]
    if repair_json is not None:
        try:
            repaired = repair_json(cleaned)
        except Exception:
            repaired = None
        if repaired and repaired not in parse_candidates:
            parse_candidates.append(repaired)

    for candidate in parse_candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    return None


def extract_interviewee_reply(raw: str) -> str:
    cleaned = _strip_code_fences(raw)
    if not cleaned:
        return DEFAULT_REPLY_FALLBACK

    parsed = _parse_json_like(cleaned)
    if parsed is None:
        return cleaned

    if isinstance(parsed, dict):
        for key in REPLY_KEYS:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return DEFAULT_REPLY_FALLBACK

    if isinstance(parsed, str):
        return parsed.strip() or DEFAULT_REPLY_FALLBACK

    return cleaned


def _clip_text(text: str, max_chars: int) -> str:
    text = text or ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[-max_chars:]


class IntervieweeAgent:
    def __init__(self, profile_path, save_path=None):
        self.profile_path = profile_path
        self.save_path = save_path
        self.history = ""
        self.basic_info = ""
        self._history_summary = ""
        self._history_turns: list[dict[str, str]] = []
        self.model_candidates = Config.get_model_candidates("interviewee")
        self.model = self.model_candidates[0]
        self._prompt_generator = ElderPromptGenerator(template_path=Config.INTERVIEWEE_PROMPT_TEMPLATE)
        self._base_profile_data = self._prompt_generator.load_elder_profile(self.profile_path)

        self._load_sys_prompt()
        self._load_tools()
        self._init_client()
        client = getattr(self, "client", None)
        self._compressor = HistoryCompressor(client, self.model_candidates) if client else None

    def initialize_conversation(self, basic_info: str | dict[str, Any] = ""):
        self.basic_info = self._stringify_basic_info(basic_info)
        self.history = f"受访者基本信息: {self.basic_info}\n" if self.basic_info else ""
        self._history_summary = ""
        self._history_turns = []
        self._load_sys_prompt(basic_info if isinstance(basic_info, dict) else None)

    def _load_tools(self):
        self.memory_system = ElderMemorySystem(self.profile_path)
        self.tools = get_tool_schemas()
        self.tool_callables = get_tool_callables(self.memory_system)

    def _load_sys_prompt(self, basic_info: dict[str, Any] | None = None):
        profile_data = deepcopy(self._base_profile_data)
        if basic_info:
            profile_data = self._apply_basic_info_overrides(profile_data, basic_info)
        self.sys_prompt = self._prompt_generator.generate_prompt(profile_data)

    def _load_step_prompt(self, history, question):  # noqa: ARG002 - history kept for compatibility
        max_recent = max(1, int(getattr(Config, "INTERVIEWEE_HISTORY_MAX_TURNS", Config.HISTORY_COMPRESS_MAX_RECENT_TURNS)))
        all_turns = list(getattr(self, "_history_turns", []) or [])
        recent_turns = all_turns[-max_recent:]
        omitted_turns = max(0, len(all_turns) - len(recent_turns))
        recent_text = "\n".join(
            f"Q: {t['question']}\nA: {t['answer']}" for t in recent_turns
        )

        sections = []
        basic_info = getattr(self, "basic_info", "")
        history_summary = getattr(self, "_history_summary", "")
        if basic_info:
            sections.append(f"受访者基本信息：{basic_info}")
        if history_summary:
            sections.append(f"访谈历史摘要：{history_summary}")
        if omitted_turns > 0:
            sections.append(f"（前面还有 {omitted_turns} 轮对话已省略，请保持人物设定和叙事连续性。）")
        if recent_text:
            sections.append(f"近期对话：\n{recent_text}")
        sections.append(f"访谈问题：{question}")
        return self._clip_step_prompt("\n\n".join(sections))

    def _clip_step_prompt(self, prompt: str) -> str:
        """Keep interviewee simulation context bounded for long batch runs."""
        max_chars = max(500, int(getattr(Config, "INTERVIEWEE_HISTORY_MAX_CHARS", 6000)))
        if len(prompt) <= max_chars:
            return prompt
        prefix = "（较早对话已省略，请保持人物设定和叙事连续性。）\n"
        return prefix + _clip_text(prompt, max_chars - len(prefix))

    def _init_client(self):
        self.client = OpenAI(**Config.get_openai_client_kwargs())

    def _stringify_basic_info(self, basic_info: str | dict[str, Any]) -> str:
        if isinstance(basic_info, str):
            return basic_info.strip()

        if not isinstance(basic_info, dict):
            return ""

        parts = []
        if basic_info.get("name"):
            parts.append(f"姓名：{basic_info['name']}")
        if basic_info.get("birth_year"):
            parts.append(f"出生年份：{basic_info['birth_year']}")
        elif basic_info.get("age"):
            parts.append(f"年龄：{basic_info['age']}")
        if basic_info.get("hometown"):
            parts.append(f"家乡：{basic_info['hometown']}")
        if basic_info.get("background"):
            parts.append(f"背景：{basic_info['background']}")

        return "；".join(parts)

    def _apply_basic_info_overrides(
        self,
        profile_data: dict[str, Any],
        basic_info: dict[str, Any],
    ) -> dict[str, Any]:
        profile_root = profile_data.setdefault("elder_profile", {})
        basic_profile = profile_root.setdefault("basic_info", {})

        name = (basic_info.get("name") or "").strip()
        hometown = (basic_info.get("hometown") or "").strip()
        background = (basic_info.get("background") or "").strip()
        residence = (basic_info.get("current_residence") or hometown).strip()
        age = basic_info.get("age")
        birth_year = basic_info.get("birth_year")

        if not age and birth_year:
            try:
                age = datetime.now().year - int(birth_year)
            except (TypeError, ValueError):
                age = None

        if name:
            basic_profile["name"] = name
        if hometown:
            basic_profile["hometown"] = hometown
        if residence:
            basic_profile["current_residence"] = residence
        if age:
            basic_profile["age"] = age
        if background:
            basic_profile["life_background_summary"] = background
            if not basic_profile.get("identity_experience"):
                basic_profile["identity_experience"] = background

        return profile_data

    def _normalize_reply(self, raw: str) -> str:
        return extract_interviewee_reply(raw)

    def record_turn(self, question: str, answer: str, *, allow_compression: bool = True):
        question = (question or "").strip()
        answer = (answer or "").strip()
        if question or answer:
            self.history += f"Q: {question}\nA: {answer}\n"
            self._history_turns.append({"question": question, "answer": answer})
            if allow_compression:
                self._maybe_compress_history()

    def _maybe_compress_history(self):
        max_recent = Config.HISTORY_COMPRESS_MAX_RECENT_TURNS
        if len(self._history_turns) <= max_recent:
            return
        split = len(self._history_turns) - max_recent
        old_turns = self._history_turns[:split]
        total_chars = sum(len(t["question"]) + len(t["answer"]) for t in old_turns)
        if total_chars < Config.HISTORY_COMPRESS_MAX_CHAR_THRESHOLD // 3:
            return
        compressor = getattr(self, "_compressor", None)
        if compressor is None:
            return
        try:
            new_summary = compressor.compress_qa_pairs(
                old_turns, self._history_summary,
            )
            if new_summary:
                self._history_summary = new_summary
                self._history_turns = self._history_turns[split:]
                logger.info(
                    "Interviewee history compressed: %d old turns → %d-char summary",
                    split, len(new_summary),
                )
        except Exception as exc:
            logger.warning("History compression failed, keeping raw turns: %s", exc)

    def step(self, prompt: str) -> str:
        """Send a prompt and return the text reply, executing any tool calls."""
        reply, _ = self.step_with_metadata(prompt)
        return reply

    def step_with_metadata(self, prompt: str) -> tuple[str, list[dict]]:
        """Send a prompt and return (reply, tool_calls_metadata).

        tool_calls_metadata is a list of dicts:
          {"tool": str, "args": dict, "result": any}
        """
        messages = [
            {"role": "system", "content": self.sys_prompt},
            {"role": "user", "content": prompt},
        ]
        tool_calls_log: list[dict] = []

        while True:
            try:
                response = self._create_completion(messages)
            except Exception as exc:
                if is_transient_llm_error(exc):
                    return DEFAULT_REPLY_FALLBACK, tool_calls_log
                raise
            message = response.choices[0].message

            if not message.tool_calls:
                return self._normalize_reply(message.content or ""), tool_calls_log

            assistant_message = {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    for tool_call in message.tool_calls
                ],
            }
            if hasattr(message, "reasoning_content") and getattr(message, "reasoning_content", None):
                assistant_message["reasoning_content"] = getattr(message, "reasoning_content")
            messages.append(assistant_message)

            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args_raw = tool_call.function.arguments or "{}"
                if repair_json is not None:
                    try:
                        fn_args_raw = repair_json(fn_args_raw)
                    except Exception:
                        pass
                fn_args = json.loads(fn_args_raw)
                fn = self.tool_callables.get(fn_name)
                result = fn(**fn_args) if fn else {"error": f"unknown tool: {fn_name}"}
                tool_calls_log.append({"tool": fn_name, "args": fn_args, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

    def _create_completion(self, messages):
        last_error = None
        max_attempts = max(1, Config.MAX_RETRIES)
        for model_name in self.model_candidates:
            for attempt in range(1, max_attempts + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        tools=self.tools,
                        tool_choice="auto",
                        max_tokens=max(200, int(getattr(Config, "INTERVIEWEE_REPLY_MAX_TOKENS", 900))),
                    )
                    self.model = model_name
                    return response
                except Exception as exc:
                    last_error = exc
                    if is_transient_llm_error(exc):
                        if attempt < max_attempts:
                            sleep_before_retry(exc, attempt)
                            continue
                        break
                    if self._should_fallback_model(exc):
                        break
                    raise
        raise last_error

    def _should_fallback_model(self, error: Exception) -> bool:
        message = str(error).lower()
        return (
            "not found the model" in message
            or "permission denied" in message
            or "resource_not_found_error" in message
        )

    def answer_questions(self, questions, save_path=None, test=False):
        target_path = save_path or self.save_path
        responses = []

        if test:
            while True:
                question = input("请输入问题（输入 exit 退出）：")
                if question.lower() == "exit":
                    break
                prompt = self._load_step_prompt(self.history, question)
                answer = self.step(prompt)
                print(f"问题：{question}\n回答：{answer}\n")
                self.record_turn(question, answer)
        else:
            for index, question in enumerate(questions):
                history = "" if index == 0 else self.history
                prompt = self._load_step_prompt(history, question)
                answer = self.step(prompt)
                self.record_turn(question, answer)
                responses.append(answer)
                print(f"问题：{question}\n回答：{answer}\n")

        if target_path:
            with open(target_path, "w", encoding="utf-8") as file:
                file.write(self.history)
            print(f"已保存到 {target_path}")

        return responses


if __name__ == "__main__":
    if not Config.get_api_key():
        print("错误: 请先在 .env 文件中设置 OPENAI_API_KEY")
        raise SystemExit(1)

    agent = IntervieweeAgent(
        profile_path=os.path.join(os.path.dirname(__file__), "../prompts/roles/elder_profile_example.json"),
        save_path=os.path.join(os.path.dirname(__file__), "../data/raw/interviewee_answers.txt"),
    )
    agent.initialize_conversation("一位 1942 年出生的成都老人")
    agent.answer_questions(["您叫什么名字？", "您有什么故事要分享？"])
