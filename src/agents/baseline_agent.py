#!/usr/bin/env python3
"""
Baseline Agent - 无 Planner 的基线对话 Agent

用于评估对比，纯 LLM 对话访谈。
"""

import os
import sys
import logging
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.config import Config
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from .base_agents import BaseAgent

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


class BaselineAgent(BaseAgent):
    """无Planner的基线对话Agent"""

    def __init__(self, session_id: str = None, model_type: str = None, 
                 model_base_url: str = None, api_key: str = None, planner: bool = False):
        """
        初始化 Baseline Agent
        
        Args:
            session_id: 会话 ID，用于日志和结果保存
            model_type: 模型类型（如 'deepseek-chat'），默认使用环境变量
            model_base_url: 模型服务URL，默认使用环境变量
            api_key: API密钥，默认使用环境变量
            planner: 是否启用 Planner 模式（True 使用高级提示词策略，False 使用基础模式）
        """
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.conversation_history_raw = []  # 原始对话历史（纯文本）
        self.planner = planner  # Planner 模式开关
        
        # 模型配置
        self.model_type = model_type or os.getenv("MODEL_TYPE", "deepseek-chat")
        self.model_base_url = model_base_url or os.getenv("MODEL_BASE_URL", "https://api.deepseek.com/v1")
        self.api_key = api_key or os.getenv("API_KEY", "")
        
        # 加载系统提示词
        if self.planner:
            # 使用 Planner 模式的高级提示词
            prompt_path = os.path.join(Config.PROMPTS_DIR, 'baseline_planner_prompt.txt')
            prompt_type = "Planner"
        else:
            # 使用基础模式的提示词
            prompt_path = os.path.join(Config.PROMPTS_DIR, 'baseline_system_prompt.txt')
            prompt_type = "Basic"
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            self.system_prompt = f.read()

        # 调用父类初始化
        super().__init__(tools=None)
        
        logger.info(f"Baseline Agent 初始化完成 (Session: {self.session_id}, Model: {self.model_type}, Mode: {prompt_type})")

    def _setup_model(self):
        """覆盖父类方法，使用自定义的模型参数"""
        return ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
            model_type=self.model_type,
            url=self.model_base_url,
            api_key=self.api_key,
        )

    def _create_system_message(self) -> BaseMessage:
        """创建系统消息"""
        return BaseMessage.make_system_message(content=self.system_prompt)

    def _create_step_message(self) -> BaseMessage:
        """创建步骤消息（未在此代理中直接使用）"""
        raise NotImplementedError("_create_step_message is not used directly in BaselineAgent")

    def initialize_conversation(self, basic_info: str):
        """初始化对话"""
        system_message = self.system_prompt.replace("[用户的基本生平信息]", basic_info)
        self.system_prompt = system_message
        self._init_chat_agent(message_window_size=10)
        self.conversation_history_raw = []
        logger.info(f"对话已初始化，基本信息: {basic_info}")

    def evaluate_interviewee_state(self, answer: str) -> dict:
        """
        评估被访谈者的情感/精神状态（仅在 Planner 模式下使用）
        
        返回格式：{
            "emotional_energy": float (-1 to 1),  # 情绪能量
            "energy_level": float (0 to 1),        # 精神状态
            "analysis": str                        # 分析说明
        }
        """
        if not self.planner:
            return None
        
        # 简单的启发式评估（可扩展为使用 LLM 进行更复杂的分析）
        state = {
            "emotional_energy": 0.0,
            "energy_level": 0.5,
            "analysis": ""
        }
        
        # 情绪能量评估
        positive_indicators = ['快乐', '开心', '高兴', '欣喜', '骄傲', '感谢', '幸福', '美好', '温暖', '满足']
        negative_indicators = ['难过', '伤心', '痛苦', '后悔', '遗憾', '失望', '害怕', '焦虑', '有些感伤']
        
        positive_count = sum(1 for word in positive_indicators if word in answer)
        negative_count = sum(1 for word in negative_indicators if word in answer)
        
        if positive_count > negative_count:
            state["emotional_energy"] = min(0.8, 0.2 + positive_count * 0.2)
            state["analysis"] += "情绪积极；"
        elif negative_count > positive_count:
            state["emotional_energy"] = max(-0.8, -0.2 - negative_count * 0.2)
            state["analysis"] += "情绪较为沉重；"
        else:
            state["emotional_energy"] = 0.0
            state["analysis"] += "情绪平淡；"
        
        # 精神状态评估（基于回答长度和连贯性）
        answer_length = len(answer)
        if answer_length < 10:
            state["energy_level"] = 0.2
            state["analysis"] += "回答过短，精神状态可能下降；"
        elif answer_length < 50:
            state["energy_level"] = 0.4
            state["analysis"] += "回答较短，精神状态一般；"
        elif answer_length < 200:
            state["energy_level"] = 0.6
            state["analysis"] += "回答适长，精神状态良好；"
        else:
            state["energy_level"] = min(1.0, 0.7 + len(self.conversation_history_raw) / 100)
            state["analysis"] += "回答充分，精神状态良好；"
        
        # 根据对话轮数调整精神状态（长对话可能导致疲倦）
        if len(self.conversation_history_raw) > 16:  # 超过8轮
            state["energy_level"] *= 0.8
            state["analysis"] += "对话轮数较多，精神可能有所下降；"
        
        logger.info(f"被访谈者状态评估: {state}")
        return state

    def should_continue_interview(self) -> bool:
        """
        判断是否应该继续访谈（在 Planner 模式下使用）
        """
        # if not self.planner or len(self.conversation_history_raw) == 0:
        #     return True
        
        # # 从最后一个被访谈者的回答评估
        # last_response = None
        # for i in range(len(self.conversation_history_raw) - 1, -1, -1):
        #     if self.conversation_history_raw[i]["role"] == "user":
        #         last_response = self.conversation_history_raw[i]["content"]
        #         break
        
        # if not last_response:
        #     return True
        
        # state = self.evaluate_interviewee_state(last_response)
        
        # # 如果精神状态过低或情绪过度负面，建议休息
        # if state and (state["energy_level"] < 0.2 or state["emotional_energy"] < -0.6):
        #     logger.warning(f"被访谈者状态不佳，建议休息: {state['analysis']}")
        #     return False
        
        return True

    def get_next_question(self, user_response: str = None):
        """获取下一个问题"""
        try:
            # 如果是第一轮，user_response为None
            if user_response:
                self.conversation_history_raw.append({"role": "user", "content": user_response})
                # 使用 ChatAgent 的 step 方法获取回复
                response = self.agent.step(user_response)
                question = response.msg.content
            else:
                # 首次获取初始问题
                response = self.agent.step("请开始采访。")
                question = response.msg.content

            self.conversation_history_raw.append({"role": "assistant", "content": question})
            logger.info(f"生成问题: {question[:100]}...")
            return question

        except Exception as e:
            logger.error(f"API调用失败: {e}")
            return "抱歉，我遇到了一些技术问题，请稍后再试。"

    def save_conversation(self):
        """保存对话记录"""
        results_dir = "results/conversations"
        os.makedirs(results_dir, exist_ok=True)

        output_file = os.path.join(results_dir, f"baseline_{self.session_id}.txt")
        with open(output_file, 'w', encoding='utf-8') as f:
            for msg in self.conversation_history_raw:
                f.write(f"[{msg['role']}]: {msg['content']}\n\n")

        logger.info(f"对话记录已保存到: {output_file}")

    
    # for test
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
        turn_count = 0
        while True:
            user_input = input("\n老人: ").strip()

            if user_input.lower() in ['退出', 'exit', 'quit', '结束']:
                print("访谈结束，感谢参与！")
                self.save_conversation()
                break

            if not user_input:
                print("请输入有效回答")
                continue

            question = self.get_next_question(user_input)
            print(f"\n助手: {question}")

            turn_count += 1
            if turn_count >= 50:
                print("\n已达到最大轮次（50），访谈结束。")
                self.save_conversation()
                break


if __name__ == "__main__":
    # 检查API密钥
    if not Config.OPENAI_API_KEY:
        print("错误: 请先在 .env 文件中设置 OPENAI_API_KEY")
        sys.exit(1)

    agent = BaselineAgent()
    agent.run_interview()
