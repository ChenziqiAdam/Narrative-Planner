"""
核心模块

包含访谈图谱的核心数据模型和管理组件：
- 节点状态和领域枚举
- ThemeNode 和 EventNode 数据类
- ThemeLoader 主题加载器
- GraphManager 图谱管理器
"""

from .node_status import NodeStatus, Domain, NodeStyle
from .theme_node import ThemeNode
from .event_node import EventNode
from .theme_loader import ThemeLoader
from .graph_manager import GraphManager

__all__ = [
    # 枚举
    "NodeStatus",
    "Domain",
    "NodeStyle",
    # 数据模型
    "ThemeNode",
    "EventNode",
    # 加载器和管理器
    "ThemeLoader",
    "GraphManager",
]
