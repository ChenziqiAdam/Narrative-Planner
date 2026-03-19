#!/usr/bin/env python3
"""
Baseline Agent - a clean interview agent without planner integrations.
"""

import logging
import os
import sys
from datetime import datetime

project_root = os.path.join(os.path.dirname(__file__), "..", "..")
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from openai import OpenAI

from src.config import Config


logging.basicConfig(
    level=Config.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/baseline_agent.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class BaselineAgent:
    """A standalone baseline interview agent with no planner-side backends."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.conversation_history: list[dict[str, str]] = []

        prompt_path = os.path.join(Config.PROMPTS_DIR, "baseline_system_prompt.txt")
        with open(prompt_path, "r", encoding="utf-8") as file:
            self.system_prompt = file.read()

        logger.info("Baseline Agent initialized (session=%s)", self.session_id)

    def initialize_conversation(self, basic_info: str):
        system_message = self.system_prompt.replace("[用户的基本生平信息]", basic_info)
        self.conversation_history = [{"role": "system", "content": system_message}]
        logger.info("Baseline conversation initialized")

    def get_next_question(self, user_response: str | None = None):
        if user_response:
            self.conversation_history.append({"role": "user", "content": user_response})

        try:
            response = self.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=self.conversation_history,
                max_tokens=4096,
            )
            question = response.choices[0].message.content or ""
            self.conversation_history.append({"role": "assistant", "content": question})
            logger.info("Baseline generated next turn")
            return question
        except Exception as exc:
            logger.error("Baseline API call failed: %s", exc)
            return "抱歉，我遇到了一些技术问题，请稍后再试。"

    def save_conversation(self):
        results_dir = "results/conversations"
        os.makedirs(results_dir, exist_ok=True)

        output_file = os.path.join(results_dir, f"baseline_{self.session_id}.txt")
        with open(output_file, "w", encoding="utf-8") as file:
            for message in self.conversation_history:
                file.write(f"[{message['role']}]: {message['content']}\n\n")

        logger.info("Baseline conversation saved to %s", output_file)


if __name__ == "__main__":
    if not Config.get_api_key():
        print("错误: 请先在 .env 文件中设置 OPENAI_API_KEY")
        sys.exit(1)

    agent = BaselineAgent()
    basic_info = input("基本信息: ").strip()
    agent.initialize_conversation(basic_info)
    print(agent.get_next_question())
