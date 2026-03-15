import os
import logging
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config
from prompts.roles.elderly_promot import ElderPromptGenerator
from tools.elder_tools import ElderMemorySystem, get_tool_schemas, get_tool_callables
from agents.base_agent import BaseAgent

logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/interviewee_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class IntervieweeAgent:
    def __init__(self, profile_path, save_path):
        self.profile_path = profile_path
        self.save_path = save_path

        self._load_sys_prompt()
        self._load_tools()
        self._init_agent()
        self.history = ""
        logger.info("IntervieweeAgent 初始化完成")

    def _load_tools(self):
        self.memory_system = ElderMemorySystem(self.profile_path)
        self.tools = get_tool_schemas()
        self.tool_callables = get_tool_callables(self.memory_system)

    def _load_sys_prompt(self):
        generator = ElderPromptGenerator(template_path=Config.INTERVIEWEE_PROMPT_TEMPLATE)
        profile_data = generator.load_elder_profile(self.profile_path)
        self.sys_prompt = generator.generate_prompt(profile_data)

    def _load_step_prompt(self, history, question):
        return f"采访历史：{history}\n采访问题：{question}"

    def _init_agent(self):
        self.agent = BaseAgent(
            system_prompt=self.sys_prompt,
            tools=self.tools,
            tool_callables=self.tool_callables,
        )

    # test mode
    def answer_questions(self, questions, save_path=None, test=False):
        if save_path is None:
            save_path = self.save_path
        responses = []
        if test:
            while True:
                question = input("请输入问题（输入exit退出）：")
                if question.lower() == "exit":
                    break
                prompt = self._load_step_prompt(self.history, question)
                answer = self.agent.step(prompt)
                logger.info(f"问题: {question[:80]}... | 回答: {answer[:80]}...")
                print(f"问题：{question}\n回答：{answer}\n")
                self.history += f"Q: {question}\nA: {answer}\n"
        else:
            for idx, question in enumerate(questions):
                history = "" if idx == 0 else self.history
                prompt = self._load_step_prompt(history, question)
                answer = self.agent.step(prompt)
                self.history += f"Q: {question}\nA: {answer}\n"
                responses.append(answer)
                logger.info(f"问题: {question[:80]}... | 回答: {answer[:80]}...")
                print(f"问题：{question}\n回答：{answer}\n")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(self.history)
        print(f"已保存到 {save_path}")
        return responses


# test
if __name__ == "__main__":
    if not Config.MOONSHOT_API_KEY:
        print("错误: 请先在 .env 文件中设置 MOONSHOT_API_KEY")
        exit(1)
    agent = IntervieweeAgent(
        profile_path=os.path.join(os.path.dirname(__file__), "../prompts/roles/elder_profile_example.json"),
        save_path=os.path.join(os.path.dirname(__file__), "../data/raw/interviewee_answers.txt"),
    )
    questions = [
        "您叫什么名字",
        "您有什么故事要分享？"
    ]
    agent.answer_questions(questions)
