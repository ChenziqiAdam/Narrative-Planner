"""
叙事导航者 (Narrative Navigator)

核心访谈规划系统，包含：
- 核心模块：主题加载
- Agent：Interviewer、Evaluator、GraphExtraction
"""

from . import config
from .core import ThemeLoader, ThemeNode, EventNode

__version__ = "0.2.0"
__all__ = ["config", "ThemeLoader", "ThemeNode", "EventNode"]
