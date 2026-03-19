import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    """配置类"""
    
    # API 配置
    MOONSHOT_API_KEY = os.getenv('MOONSHOT_API_KEY')
    MOONSHOT_BASE_URL = os.getenv('MOONSHOT_BASE_URL', 'https://api.moonshot.cn/v1')
    MODEL_NAME = os.getenv('MODEL_NAME', 'moonshot-v1-8k') # 默认模型改为 Kimi
    
    # 项目配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 30))
    
    # 文件路径
    PROMPTS_DIR = 'src/prompts'
    DATA_DIR = 'data'
    LOGS_DIR = 'logs'

    # Agent 提示词配置
    # interviewee_agent 使用的 Jinja2 模板文件路径（None 则使用代码内默认模板）
    INTERVIEWEE_PROMPT_TEMPLATE = os.getenv(
        'INTERVIEWEE_PROMPT_TEMPLATE',
        None  # e.g. 'prompts/roles/elderly_jinja_template.txt'
    )
    # life_generator 使用的系统提示词文件路径（None 则使用代码内默认字符串）
    LIFE_GENERATOR_SYSTEM_PROMPT = os.getenv(
        'LIFE_GENERATOR_SYSTEM_PROMPT',
        None  # e.g. 'prompts/roles/life_generator_system_prompt.txt'
    )
    # interviewer_agent 使用的系统提示词文件路径
    INTERVIEWER_SYSTEM_PROMPT = os.getenv(
        'INTERVIEWER_SYSTEM_PROMPT',
        'prompts/interviewer_system_prompt.md'
    )

# 创建必要的目录
os.makedirs(Config.PROMPTS_DIR, exist_ok=True)
os.makedirs(Config.DATA_DIR, exist_ok=True)
os.makedirs(Config.LOGS_DIR, exist_ok=True)