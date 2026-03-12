from camel.agents import ChatAgent
from camel.messages import OpenAISystemMessage
from camel.types import ModelType
from camel.models import ModelFactory
from camel.types import ModelPlatformType

import os
import logging
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config
from prompts.roles.life_generator_prompt import build_init_prompt, build_update_message

sys.path.append(os.path.join(os.path.dirname(__file__), "../prompts/roles"))

logging.basicConfig(
    level=Config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/life_generator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LifeGenerator:
    def __init__(self, name, example_path, save_path, model_type=None, model_base_url=None, api_key=None):
        self.example_path = example_path
        self.example_text = None
        self.user_name = name
        self.model_type = model_type or Config.MODEL_NAME
        self.model_base_url = model_base_url or Config.MOONSHOT_BASE_URL
        self.api_key = api_key or Config.MOONSHOT_API_KEY
        self.save_path = save_path

        self.sys_prompt = self._load_sys_prompt()
        self.agent = self._load_chat_agent()
        logger.info("LifeGenerator 初始化完成")

    def _load_sys_prompt(self):
        system_prompt = None
        if Config.LIFE_GENERATOR_SYSTEM_PROMPT and os.path.exists(Config.LIFE_GENERATOR_SYSTEM_PROMPT):
            with open(Config.LIFE_GENERATOR_SYSTEM_PROMPT, "r", encoding="utf-8") as f:
                system_prompt = f.read()
            logger.info(f"加载自定义系统提示词: {Config.LIFE_GENERATOR_SYSTEM_PROMPT}")
        with open(self.example_path, "r", encoding="utf-8") as f:
            prompt = build_init_prompt(f.read(), self.user_name, system_prompt=system_prompt)
            return prompt
    
    def _load_step_prompt(self,history):
         prompt = build_update_message(history)
         return prompt
    
    def _load_chat_agent(self):
        model = ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
            model_type=self.model_type,
            url=self.model_base_url,
            api_key=self.api_key,
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
        logger.info(f"初始人生故事生成完毕")
        print(f"初始人生故事: {history}")
        run = 0
        while run <= max_run:
            run += 1
            update_message = self._load_step_prompt(history)
            response = self.agent.step(update_message)
            history = response.msg.content
            logger.info(f"第 {run} 次更新完毕")
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
    if not Config.MOONSHOT_API_KEY:
        print("错误: 请先在 .env 文件中设置 MOONSHOT_API_KEY")
        exit(1)
    generator = LifeGenerator(
        name="张三",
        example_path=os.path.join(os.path.dirname(__file__), "../data/raw/life_example.txt"),
        save_path=os.path.join(os.path.dirname(__file__), "../data/raw/generated_life_story.txt"),
    )
    story = generator.generate()
    print(f"最终人生故事: {story}")
