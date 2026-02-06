"""
叙事导航者 (Narrative Navigator)

核心访谈规划系统，包含：
- 核心模块：主题、图谱管理
- Agent：Baseline 和 Planner Agent
"""

from . import config
from .core import GraphManager, ThemeLoader, ThemeNode, EventNode

__version__ = "0.1.0"
__all__ = ["config", "GraphManager", "ThemeLoader", "ThemeNode", "EventNode"]
