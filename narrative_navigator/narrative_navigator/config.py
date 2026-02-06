import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    """配置类"""
    
    # API 配置
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    MODEL_NAME = os.getenv('MODEL_NAME', 'gpt-4')
    
    # 项目配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 30))
    
    # 文件路径
    PROMPTS_DIR = 'prompts'
    DATA_DIR = 'data'
    LOGS_DIR = 'logs'
    THEMES_DIR = os.path.join(DATA_DIR, 'themes')
    INTERVIEWS_DIR = os.path.join(DATA_DIR, 'interviews')

# 创建必要的目录
os.makedirs(Config.PROMPTS_DIR, exist_ok=True)
os.makedirs(Config.DATA_DIR, exist_ok=True)
os.makedirs(Config.LOGS_DIR, exist_ok=True)
os.makedirs(Config.THEMES_DIR, exist_ok=True)
os.makedirs(Config.INTERVIEWS_DIR, exist_ok=True)

