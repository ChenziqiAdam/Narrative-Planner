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
    PROMPTS_DIR = 'prompts'
    DATA_DIR = 'data'
    LOGS_DIR = 'logs'

# 创建必要的目录
os.makedirs(Config.PROMPTS_DIR, exist_ok=True)
os.makedirs(Config.DATA_DIR, exist_ok=True)
os.makedirs(Config.LOGS_DIR, exist_ok=True)

