from camel.agents import ChatAgent
from camel.messages import OpenAISystemMessage
from camel.types import ModelType
from camel.models import ModelFactory
from camel.types import ModelPlatformType

import os

import sys
from prompts.roles.life_generator_prompt import build_init_prompt, build_update_message


sys.path.append(os.path.join(os.path.dirname(__file__), "../prompts/roles"))

class LifeGenerator:
    def __init__(self,name, example_path,model_type,model_base_url,api_key,save_path):
        self.example_path = example_path
        self.example_text = None
        self.user_name = name
        self.model_type = model_type
        self.model_base_url = model_base_url
        self.api_key = api_key
        self.save_path = save_path
        
        self.sys_prompt = self._load_sys_prompt()
        self.agent = self._load_chat_agent()

    def _load_sys_prompt(self):
        with open(self.example_path, "r", encoding="utf-8") as f:
            prompt = build_init_prompt(f.read(),self.user_name)
            return prompt
    
    def _load_step_prompt(self,history):
         prompt = build_update_message(history)
         return prompt
    
    def _load_chat_agent(self):
        model = ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
            model_type="deepseek-reasoner", 
            url="https://api.deepseek.com/v1",
            api_key=os.getenv("API_KEY"),
        )
        agent = ChatAgent(
            system_message=self.sys_prompt,
            model=model,
        )
        return agent
    
    def generate(self, max_run=10,save_path = None):
        if save_path is None:
            save_path = self.save_path
        response = self.agent.step("开始撰写人生故事")
        history = response.msg.content
        print(f"初始人生故事: {history}")
        run = 0
        while run <= max_run:
            run += 1
            update_message = self._load_step_prompt(history)
            response = self.agent.step(update_message)
            history = response.msg.content
            print(f"更新后的人生故事: {history}")
            response = self.agent.step("回忆一下要点？你还有没有要补充的？只回答(y/n)")
            print(response)
            if response.msg.content.lower() != 'y':
                break
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(history)
        print(f"已保存到 {save_path}")
        return history

if __name__ == "__main__":
    generator =  LifeGenerator(
        "张三",
        os.path.join(os.path.dirname(__file__), "../data/raw/life_example.txt"),
        model_type="deepseek-reasoner", 
        model_base_url="https://api.deepseek.com/v1",
        api_key=os.getenv("API_KEY"),
        save_path=os.path.join(os.path.dirname(__file__), "../data/raw/generated_life_story.txt"),
    )
    story = generator.generate()
    print(f"最终人生故事: {story}")
