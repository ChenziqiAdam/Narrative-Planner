#!/usr/bin/env python3
"""
Flask 启动脚本 - 确保加载最新代码
"""
import sys
import os
import importlib

# 设置环境变量
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

# 确保项目根目录在路径中
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, '.env'))

# 先导入 config，确保是最新的
import src.config
importlib.reload(src.config)
from src.config import Config
print(f"Config check: OPENAI_API_KEY = {'SET' if Config.OPENAI_API_KEY else 'NOT SET'}")
print(f"Config.PROMPTS_DIR = {Config.PROMPTS_DIR}")

# 导入并运行 Flask
import src.app
importlib.reload(src.app)
from src.app import app
app.run(host='0.0.0.0', port=9999, debug=False, use_reloader=False)
