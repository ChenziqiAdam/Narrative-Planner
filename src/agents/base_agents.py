import os
import json
from typing import Any, Dict, List, Optional

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.types import ModelPlatformType
from camel.models import ModelFactory
from json_repair import repair_json
from jinja2 import Template
from dotenv import load_dotenv
import yaml

load_dotenv()


class BaseAgent:
    """
    抽象 Agent 基类

    子类应实现：
      - _create_system_message(self) -> BaseMessage
      - respond(self, message: str) -> str

    提供的公共功能：
      - profile 加载
      - 模型实例化（_setup_model）
      - ChatAgent 初始化（_init_chat_agent）
      - JSON 响应容错解析（parse_json_response）
      - get_name() 的默认实现
    """

    def __init__(self,  tools: Optional[List[Any]] = None):
        self.tools: List[Any] = tools or []
        self.model = self._setup_model()
        self._init_chat_agent()

    def _load_profile(self, profile_path) -> Dict[str, Any]:
        """加载 profile 文件，支持 JSON 和 YAML 格式；若路径无效或加载失败则返回空字典"""
        if not profile_path:  # 显式处理空路径
            return {}
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                _, ext = os.path.splitext(profile_path)
                ext = ext.lower() 
                if ext == '.json':
                    return json.load(f)
                elif ext in ['.yaml', '.yml']:
                    return yaml.safe_load(f)
                else:
            
                    return json.load(f)
        except Exception:  
            return {}

    def _setup_model(self):
        """创建模型实例（可由子类覆盖以更改配置）"""
        return ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
            model_type=os.getenv("MODEL_TYPE", "deepseek-chat"),
            api_key=os.getenv("API_KEY", ""),
            url=os.getenv("MODEL_URL", "https://api.deepseek.com/v1"),
        )

    def _create_system_message(self) -> BaseMessage:
        """子类必须实现：返回用于 ChatAgent 的系统消息"""
        raise NotImplementedError("_create_system_message must be implemented by subclasses")

    def _create_step_message(self) -> BaseMessage:
        """子类必须实现：返回用于 ChatAgent 的对话"""
        raise NotImplementedError("_create_step_message must be implemented by subclasses")

    def _init_chat_agent(self) -> None:
        """基于系统消息、模型和可选工具初始化 ChatAgent"""
        # 子类必须保证在调用此方法时 _create_system_message 可用
        system_message = self._create_system_message()

        if self.tools:
            self.agent = ChatAgent(system_message=system_message, model=self.model, tools=self.tools)
        else:
            self.agent = ChatAgent(system_message=system_message, model=self.model)

    def parse_json_response(self, content: str) -> Dict[str, Any]:
        """
        对 LLM 响应做容错解析（使用 json_repair），返回字典或空字典
        """
        content = repair_json(content)
        try:
            return json.loads(content)
        except Exception:
            import re
            m = re.search(r"\{.*\}", content, re.DOTALL)
            return json.loads(m.group(0)) if m else {}

    def get_name(self) -> str:
        """默认从 profile_data 中推断名称；子类可覆盖"""
        identity = self.profile_data.get("identity", {}) if isinstance(self.profile_data, dict) else {}
        raw = identity.get("raw_data", {}) if isinstance(identity.get("raw_data", {}), dict) else {}
        return identity.get("name") or raw.get("name") or "Agent"
    
    def respond(self, message: str) -> str:
        """子类必须实现：处理输入消息并返回响应"""
        raise NotImplementedError("respond must be implemented by subclasses")