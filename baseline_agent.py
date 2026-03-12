#!/usr/bin/env python3
import os
import time
import logging
from config import Config
from openai import OpenAI

# 设置日志
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/baseline_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BaselineAgent:
    """无Planner的基线对话Agent"""

    MAX_HISTORY_MESSAGES = 18

    def __init__(self):
        self.client = OpenAI(
            api_key=Config.MOONSHOT_API_KEY,
            base_url=Config.MOONSHOT_BASE_URL
        )
        self.conversation_history = []

        # 加载系统提示词
        with open(
            os.path.join(Config.PROMPTS_DIR, 'baseline_system_prompt.txt'),
            'r',
            encoding='utf-8'
        ) as f:
            self.system_prompt = f.read()

        logger.info("Baseline Agent 初始化完成")

    def initialize_conversation(self, basic_info):
        """初始化对话"""
        if not basic_info:
            basic_info = "暂无更多背景信息"

        system_message = self.system_prompt.replace("[用户的基本生平信息]", basic_info)
        self.conversation_history = [{"role": "system", "content": system_message}]
        logger.info(f"对话已初始化，基本信息: {basic_info}")

    def _trim_history(self):
        """保留 system message + 最近若干条对话，避免上下文无限增长。"""
        if len(self.conversation_history) <= self.MAX_HISTORY_MESSAGES:
            return
        self.conversation_history = [
            self.conversation_history[0],
            *self.conversation_history[-(self.MAX_HISTORY_MESSAGES - 1):]
        ]

    @staticmethod
    def _normalize_question(text):
        """确保输出为简洁的单个问题。"""
        if not text:
            return "您愿意从童年里最难忘的一段经历开始讲起吗？"

        cleaned = " ".join(text.strip().split())
        separators = ["\n", "？", "?", "。", "！", "!"]
        best_cut = None
        for sep in separators:
            idx = cleaned.find(sep)
            if idx != -1:
                cut = idx + 1
                if best_cut is None or cut < best_cut:
                    best_cut = cut

        if best_cut is not None:
            cleaned = cleaned[:best_cut].strip()

        if not cleaned.endswith(("？", "?")):
            cleaned = f"{cleaned}？"

        return cleaned

    def get_next_question(self, user_response=None):
        """获取下一个问题"""

        # 添加用户回复到历史（如果是第一轮，user_response为None）
        if user_response:
            self.conversation_history.append({"role": "user", "content": user_response})

        self._trim_history()

        for attempt in range(1, Config.MAX_RETRIES + 1):
            try:
                response = self.client.chat.completions.create(
                    model=Config.MODEL_NAME,
                    messages=self.conversation_history,
                    max_tokens=220,
                    temperature=0.65,
                    timeout=Config.REQUEST_TIMEOUT
                )

                raw_question = response.choices[0].message.content or ""
                question = self._normalize_question(raw_question)
                self.conversation_history.append({"role": "assistant", "content": question})

                logger.info(f"生成问题(第{attempt}次尝试): {question[:100]}...")
                return question
            except Exception as e:
                logger.warning(f"API调用失败(第{attempt}次): {e}")
                if attempt < Config.MAX_RETRIES:
                    time.sleep(min(2 ** (attempt - 1), 4))

        logger.error("API多次调用失败，返回兜底问题")
        fallback = "我听见了，您愿意继续讲讲这段经历里最让您难忘的细节吗？"
        self.conversation_history.append({"role": "assistant", "content": fallback})
        return fallback

    def run_interview(self):
        """运行访谈循环"""
        print("=== 传记访谈助手 Baseline ===")

        print("请输入老人的基本信息（如：出生于1950年代，曾是一名工程师，现居北京）:")
        basic_info = input("基本信息: ").strip()

        self.initialize_conversation(basic_info)

        # 第一轮问题
        question = self.get_next_question()
        print(f"\n助手: {question}")

        # 对话循环
        while True:
            try:
                user_input = input("\n老人: ").strip()

                if user_input.lower() in ['退出', 'exit', 'quit', '结束', 'bye']:
                    print("访谈结束，感谢参与！")
                    break

                if not user_input:
                    print("请输入有效回答")
                    continue

                question = self.get_next_question(user_input)
                print(f"\n助手: {question}")
            except (KeyboardInterrupt, EOFError):
                print("\n访谈结束，感谢参与！")
                break

if __name__ == "__main__":
    # 检查API密钥
    if not Config.MOONSHOT_API_KEY:
        print("错误: 请先在 .env 文件中设置 MOONSHOT_API_KEY")
        exit(1)

    agent = BaselineAgent()
    agent.run_interview()
