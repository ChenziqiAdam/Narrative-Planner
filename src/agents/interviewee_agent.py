import os
from camel.models import ModelFactory
from camel.types import ModelPlatformType
from camel.messages import BaseMessage
from prompts.roles.elderly_promot import ElderPromptGenerator

# 查找记忆的工具
from tools.elder_tools import ElderMemorySystem, get_tools
from src.agents.base_agents import BaseAgent


class IntervieweeAgent(BaseAgent):
    def __init__(self, profile_path, model_type, model_base_url, api_key, save_path):
        self.profile_path = profile_path
        self.example_text = None
        self.model_type = model_type
        self.model_base_url = model_base_url
        self.api_key = api_key
        self.save_path = save_path
        self.history = ""
        
        # 加载老年人角色信息
        self.generator = ElderPromptGenerator()
        self.profile_data = self.generator.load_elder_profile(self.profile_path)
        
        # 加载工具
        self._load_tools()
        
        # 调用父类初始化
        super().__init__(tools=self.tool_schemas)

    def _load_tools(self):
        """加载记忆系统工具"""
        self.memory_system = ElderMemorySystem(self.profile_path)
        self.tool_schemas = get_tools(self.memory_system)

    def _setup_model(self):
        """覆盖父类方法，使用自定义的模型参数"""
        return ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
            model_type=self.model_type,
            url=self.model_base_url,
            api_key=self.api_key,
        )
    
    def _create_system_message(self) -> BaseMessage:
        """创建系统消息：生成老年人角色prompt"""
        sys_prompt = self.generator.generate_prompt(self.profile_data)
        return BaseMessage.make_system_message(sys_prompt)

    def _create_step_message(self) -> BaseMessage:
        """创建步骤消息（采访问题）"""
        # 这个方法用于单个问题的prompt构建
        raise NotImplementedError("_create_step_message is not used directly in IntervieweeAgent")

    def _load_step_prompt(self, history, question):
        """为采访构建prompt：包含采访历史和当前问题"""
        
        
        
        prompt = f"采访问题：{question} "
        return prompt
    
    def respond(self, message):
        reply = self.agent.step(message).msg.content
        return self.parse_json_response(reply)
    
    # test mode
    def answer_questions(self, questions, save_path=None, test=False):
        """回答采访问题"""
        if save_path is None:
            save_path = self.save_path
        responses = []
        if test:
            while True:
                question = input("请输入问题（输入exit退出）：")
                if question.lower() == "exit":
                    break
                response = self.agent.step(str(question))
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
    from dotenv import load_dotenv
    load_dotenv()
    agent = IntervieweeAgent(
        "prompts/roles/elder_profile_example.json",
        model_type=os.getenv("MODEL_TYPE"),
        model_base_url=os.getenv("MODEL_BASE_URL"),
        api_key=os.getenv("API_KEY"),
        save_path="data/raw/interviewee_answers.txt",
    )  
    agent.answer_questions([], test=True)
