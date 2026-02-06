"""
主题加载器

从 JSON 文件加载 McAdams 23 个主题定义，并实例化为 ThemeNode 对象。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .theme_node import ThemeNode
from .node_status import NodeStatus, Domain


logger = logging.getLogger(__name__)


class ThemeLoader:
    """
    主题加载器

    负责从 JSON 文件加载 McAdams 23 个主题定义，
    并将其实例化为 ThemeNode 对象。

    Usage:
        loader = ThemeLoader()
        themes = loader.load()
        theme = loader.get_theme_by_id("THEME_01_LIFE_CHAPTERS")
    """

    def __init__(self, themes_file: Optional[str] = None):
        """
        初始化主题加载器

        Args:
            themes_file: 主题定义文件路径，默认为 data/themes/mcadams_themes.json
        """
        if themes_file is None:
            # 默认路径：相对于项目根目录
            current_dir = Path(__file__).parent
            themes_file = current_dir.parent / "data" / "themes" / "mcadams_themes.json"

        self.themes_file = Path(themes_file)
        self._theme_definitions: Dict = {}
        self._theme_nodes: Dict[str, ThemeNode] = {}

    def load(self) -> Dict[str, ThemeNode]:
        """
        加载所有主题定义并实例化为 ThemeNode

        Returns:
            Dict[str, ThemeNode]: 主题ID到ThemeNode的映射
        """
        if not self.themes_file.exists():
            logger.error(f"主题文件不存在: {self.themes_file}")
            raise FileNotFoundError(f"主题文件不存在: {self.themes_file}")

        try:
            with open(self.themes_file, 'r', encoding='utf-8') as f:
                self._theme_definitions = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
            raise
        except Exception as e:
            logger.error(f"读取主题文件失败: {e}")
            raise

        self._theme_nodes = {}
        theme_count = 0

        # 遍历所有领域
        for domain_id, domain_data in self._theme_definitions.get("domains", {}).items():
            try:
                domain = Domain(domain_id)
            except ValueError:
                logger.warning(f"未知的领域: {domain_id}，跳过")
                continue

            # 遍历该领域下的所有主题
            for theme_def in domain_data.get("themes", []):
                theme_node = self._create_theme_node(theme_def, domain)
                self._theme_nodes[theme_node.theme_id] = theme_node
                theme_count += 1

        logger.info(f"成功加载 {theme_count} 个主题节点")
        return self._theme_nodes

    def _create_theme_node(self, theme_def: Dict, domain: Domain) -> ThemeNode:
        """
        从定义字典创建 ThemeNode 对象

        Args:
            theme_def: 主题定义字典
            domain: 所属领域

        Returns:
            ThemeNode 实例
        """
        return ThemeNode(
            theme_id=theme_def["theme_id"],
            domain=domain,
            title=theme_def["title"],
            description=theme_def["description"],
            seed_questions=theme_def.get("seed_questions", []),
            status=NodeStatus.PENDING,
            priority=theme_def.get("priority", 5),
            depends_on=theme_def.get("depends_on", []),
            trigger_logic=theme_def.get("trigger_logic"),
            slots_filled={slot: False for slot in theme_def.get("slots", [])},
            metadata={
                "expected_depth": theme_def.get("expected_depth", 3),
            }
        )

    def get_theme_by_id(self, theme_id: str) -> Optional[ThemeNode]:
        """
        根据ID获取主题

        Args:
            theme_id: 主题ID

        Returns:
            ThemeNode 实例，如果不存在返回 None
        """
        return self._theme_nodes.get(theme_id)

    def get_themes_by_domain(self, domain: Domain) -> List[ThemeNode]:
        """
        获取指定领域的所有主题

        Args:
            domain: 领域枚举

        Returns:
            该领域下的所有主题节点列表
        """
        return [
            node for node in self._theme_nodes.values()
            if node.domain == domain
        ]

    def get_pending_themes(self, graph_state: Optional[Dict[str, ThemeNode]] = None) -> List[ThemeNode]:
        """
        获取所有待触达的主题

        Args:
            graph_state: 图谱中所有主题的状态，用于检查依赖

        Returns:
            待触达的主题节点列表
        """
        return [
            node for node in self._theme_nodes.values()
            if node.status == NodeStatus.PENDING and node.is_ready_to_explore(graph_state or self._theme_nodes)
        ]

    def get_mentioned_themes(self) -> List[ThemeNode]:
        """
        获取所有已提及但未完成的主题

        Returns:
            已提及但未完成的主题节点列表
        """
        return [
            node for node in self._theme_nodes.values()
            if node.status == NodeStatus.MENTIONED
        ]

    def get_exhausted_themes(self) -> List[ThemeNode]:
        """
        获取所有已完成的主题

        Returns:
            已完成的主题节点列表
        """
        return [
            node for node in self._theme_nodes.values()
            if node.status == NodeStatus.EXHAUSTED
        ]

    def get_next_priority_theme(self, graph_state: Optional[Dict[str, ThemeNode]] = None) -> Optional[ThemeNode]:
        """
        获取下一个优先级最高的待探索主题

        考虑因素：
        1. 主题的 priority 值
        2. 依赖是否满足
        3. 当前状态为 PENDING 或 MENTIONED

        Args:
            graph_state: 图谱中所有主题的状态

        Returns:
            下一个应该探索的主题节点，如果没有则返回 None
        """
        candidates = [
            node for node in self._theme_nodes.values()
            if node.status in [NodeStatus.PENDING, NodeStatus.MENTIONED]
            and node.is_ready_to_explore(graph_state or self._theme_nodes)
        ]

        if not candidates:
            return None

        # 按优先级排序（priority值越小越优先）
        # 对于相同优先级，MENTIONED 状态优先于 PENDING
        def sort_key(node):
            return (node.priority, 0 if node.status == NodeStatus.MENTIONED else 1)

        return min(candidates, key=sort_key)

    def get_all_themes(self) -> Dict[str, ThemeNode]:
        """
        获取所有主题节点

        Returns:
            所有主题节点的字典
        """
        return self._theme_nodes.copy()

    def get_theme_count(self) -> int:
        """
        获取主题总数

        Returns:
            主题总数
        """
        return len(self._theme_nodes)

    def get_domains_summary(self) -> Dict[str, Dict]:
        """
        获取各领域的摘要信息

        Returns:
            各领域的摘要信息字典
        """
        summary = {}

        for domain in Domain:
            themes = self.get_themes_by_domain(domain)
            summary[domain.value] = {
                "label": domain.value,
                "count": len(themes),
                "theme_ids": [t.theme_id for t in themes],
            }

        return summary

    def reload(self) -> Dict[str, ThemeNode]:
        """
        重新加载主题定义

        Returns:
            重新加载后的主题节点字典
        """
        self._theme_nodes = {}
        return self.load()
