#!/usr/bin/env python3
import json
import os
import logging
import re
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config
from agents.base_agent import BaseAgent

logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/interviewer_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class InterviewerAgent:
    """负责提问的访谈者 Agent"""

    def __init__(self):
        with open(Config.INTERVIEWER_SYSTEM_PROMPT, 'r', encoding='utf-8') as f:
            self.system_prompt = f.read()

        self.agent = BaseAgent(system_prompt=self.system_prompt)
        logger.info("InterviewerAgent 初始化完成")

    def initialize_conversation(self, basic_info):
        """初始化对话，注入受访者基本信息"""
        system_message = self.system_prompt.replace("[用户的基本生平信息]", basic_info)
        self.agent.system_prompt = system_message
        self.agent.reset()
        logger.info(f"对话已初始化，基本信息: {basic_info}")

    def get_next_question(self, interviewee_response=None):
        """根据受访者的回答决定下一步行动。

        Returns:
            dict: {"action": "continue"|"next_phase"|"end", "question": str}
        """
        message = interviewee_response or "请开始访谈"
        try:
            raw = self.agent.step(message)

            cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
            parsed = json.loads(cleaned)
            action = parsed.get("action", "continue")
            question = parsed.get("question", "")
            logger.info(f"决策: {action} | 问题: {question[:80]}...")
            return {"action": action, "question": question}

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"JSON解析失败，回退到原始文本: {e}")
            return {"action": "continue", "question": raw}
        except Exception as e:
            logger.error(f"API调用失败: {e}")
            return {"action": "continue", "question": "抱歉，我遇到了一些技术问题，请稍后再试。"}

    def run_interview(self):
        """运行交互式访谈循环"""
        print("=== 传记访谈助手 ===")

        print("请输入受访者的基本信息（如：出生于1950年代，曾是一名工程师，现居北京）:")
        basic_info = input("基本信息: ").strip()

        self.initialize_conversation(basic_info)

        result = self.get_next_question()
        print(f"\n访谈者: {result['question']}")

        while True:
            user_input = input("\n受访者: ").strip()

            if user_input.lower() in ['退出', 'exit', 'quit', '结束']:
                print("访谈结束，感谢参与！")
                break

            if not user_input:
                print("请输入有效回答")
                continue

            result = self.get_next_question(user_input)
            if result["action"] == "end":
                print("\n访谈者: 非常感谢您的分享，访谈到此结束。")
                break
            print(f"\n[{result['action']}] 访谈者: {result['question']}")


if __name__ == "__main__":
    if not Config.MOONSHOT_API_KEY:
        print("错误: 请先在 .env 文件中设置 MOONSHOT_API_KEY")
        exit(1)

    agent = InterviewerAgent()
    agent.run_interview()
