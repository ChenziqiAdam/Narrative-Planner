from camel.agents import ChatAgent
from camel.models import ModelFactory
from camel.types import ModelPlatformType
import os
from prompts.roles.elderly_promot import ElderPromptGenerator

# 查找记忆的工具
from tools.elder_tools import ElderMemorySystem, get_tools

class IntervieweeAgent:
    def __init__(self, profile_path, model_type, model_base_url, api_key, save_path):
        self.profile_path = profile_path
        self.example_text = None
        self.model_type = model_type
        self.model_base_url = model_base_url
        self.api_key = api_key
        self.save_path = save_path
        
        self._load_sys_prompt()
        self._load_model()
        self._load_tools()
        
        self._load_chat_agent()
        self.history = ""

    def _load_tools(self):
        self.memory_system = ElderMemorySystem(self.profile_path)
        self.tool_schemas = get_tools(self.memory_system)
    
    def _load_model(self):
        self.model = ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
            model_type=self.model_type,
            url=self.model_base_url,
            api_key=self.api_key,
        )
    
    def _load_sys_prompt(self):
        generator = ElderPromptGenerator()
        profile_data = generator.load_elder_profile(self.profile_path)
        self.sys_prompt = generator.generate_prompt(profile_data)

    def _load_step_prompt(self, history, question):
        prompt = f"采访历史：{history}\n采访问题：{question}"
        return prompt

    def _load_chat_agent(self):
        self.agent = ChatAgent(
            system_message=self.sys_prompt,
            model=self.model,
            tools=self.tool_schemas,
        )
    # test mode
    def answer_questions(self, questions, save_path=None,test = False):
        if save_path is None:
            save_path = self.save_path
        responses = []
        if test:
            while True:
                question = input("请输入问题（输入exit退出）：")
                if question.lower() == "exit":
                    break
                prompt = self._load_step_prompt(self.history, question)
                response = self.agent.step(prompt)
                answer = response.msg.content
                print(f"问题：{question}\n回答：{answer}\n")
                self.history += f"Q: {question}\nA: {answer}\n"
        else:
            for idx, question in enumerate(questions):
                if idx == 0:
                    prompt = self._load_step_prompt("", question)
                else:
                    prompt = self._load_step_prompt(self.history, question)
                response = self.agent.step(prompt)
                answer = response.msg.content
                self.history += f"Q: {question}\nA: {answer}\n"
                responses.append(answer)
                print(f"问题：{question}\n回答：{answer}\n")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(self.history)
        print(f"已保存到 {save_path}")
        return responses


# test 
if __name__ == "__main__":
    agent = IntervieweeAgent(
        os.path.join(os.path.dirname(__file__), "../prompts/roles/elder_profile_example.json"),
        model_type="deepseek-chat",
        model_base_url="https://api.deepseek.com/v1",
        api_key=os.getenv("API_KEY"),
        save_path=os.path.join(os.path.dirname(__file__), "../data/raw/interviewee_answers.txt"),
    )
    questions = [
        "您叫什么名字",
        "您有什么故事要分享？"
    ]
    agent.answer_questions(questions)