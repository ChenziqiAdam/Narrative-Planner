#!/usr/bin/env python3
import os
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
    
    def __init__(self):
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        self.conversation_history = []
        
        # 加载系统提示词
        with open(os.path.join(Config.PROMPTS_DIR, 'baseline_system_prompt.txt'), 
'r', encoding='utf-8') as f:
            self.system_prompt = f.read()
        
        logger.info("Baseline Agent 初始化完成")
    
    def initialize_conversation(self, basic_info):
        """初始化对话"""
        system_message = self.system_prompt.replace("[用户的基本生平信息]", 
basic_info)
        self.conversation_history = [{"role": "system", "content": system_message}]
        logger.info(f"对话已初始化，基本信息: {basic_info}")
    
    def get_next_question(self, user_response=None):
        """获取下一个问题"""
        
        # 添加用户回复到历史（如果是第一轮，user_response为None）
        if user_response:
            self.conversation_history.append({"role": "user", "content": 
user_response})
        
        try:
            response = self.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=self.conversation_history,
                max_tokens=500,
                temperature=0.7
            )
            
            question = response.choices[0].message.content
            self.conversation_history.append({"role": "assistant", "content": 
question})
            
            logger.info(f"生成问题: {question[:100]}...")
            return question
            
        except Exception as e:
            logger.error(f"API调用失败: {e}")
            return "抱歉，我遇到了一些技术问题，请稍后再试。"
    
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
            user_input = input("\n老人: ").strip()
            
            if user_input.lower() in ['退出', 'exit', 'quit', '结束']:
                print("访谈结束，感谢参与！")
                break
                
            if not user_input:
                print("请输入有效回答")
                continue
                
            question = self.get_next_question(user_input)
            print(f"\n助手: {question}")

if __name__ == "__main__":
    # 检查API密钥
    if not Config.OPENAI_API_KEY:
        print("错误: 请先在 .env 文件中设置 OPENAI_API_KEY")
        exit(1)
    
    agent = BaselineAgent()
    agent.run_interview()

