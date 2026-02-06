"""
节点状态和领域枚举定义

定义了访谈图谱中节点的状态和所属领域。
"""

from enum import Enum


class NodeStatus(Enum):
    """
    节点状态枚举

    对应 PRD 中的三种节点状态：

    - PENDING: 预设待触达（虚线节点）- 系统初始化时的初始状态
    - MENTIONED: 提及未展开（虚线节点）- 已提及但未深度挖掘
    - EXHAUSTED: 已挖透（实线节点）- 已完成深度挖掘

    状态转换流程:
        PENDING --> MENTIONED --> EXHAUSTED
    """
    PENDING = "pending"      # 预设待触达，未提及
    MENTIONED = "mentioned"  # 已提及，但未深度展开
    EXHAUSTED = "exhausted"  # 已深度挖掘完成


class Domain(Enum):
    """
    领域枚举

    对应 McAdams 人生故事访谈的 6 个领域。
    """
    LIFE_CHAPTERS = "life_chapters"              # 人生篇章
    KEY_SCENES = "key_scenes"                     # 关键场景
    FUTURE_SCRIPTS = "future_scripts"             # 未来剧本
    CHALLENGES = "challenges"                     # 挑战
    PERSONAL_IDEOLOGY = "personal_ideology"       # 个人意识形态
    CONTEXT_MANAGEMENT = "context_management"     # 上下文管理


class NodeStyle(Enum):
    """
    节点可视化样式枚举

    用于图谱可视化时区分节点的外观。
    """
    DASHED_PENDING = "dashed_pending"      # 虚线，预设待触达
    DASHED_MENTIONED = "dashed_mentioned"  # 虚线，提及未展开
    SOLID_EXHAUSTED = "solid_exhausted"    # 实线，已挖透
