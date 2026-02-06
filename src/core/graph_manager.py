"""
图谱管理器

管理动态事件图谱，包括：
- 初始化时加载23个主题节点作为"虚线节点"
- 运行时动态添加事件节点
- 维护节点间的关系
- 计算覆盖率和状态
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    nx = None

from .theme_loader import ThemeLoader
from .theme_node import ThemeNode, NodeStatus
from .event_node import EventNode


logger = logging.getLogger(__name__)


class GraphManager:
    """
    图谱管理器

    负责管理动态事件图谱，包括：
    1. 初始化时加载23个主题节点作为"虚线节点"
    2. 运行时动态添加事件节点
    3. 维护节点间的关系
    4. 计算覆盖率和状态

    Usage:
        manager = GraphManager()
        coverage = manager.calculate_coverage()
        next_theme = manager.get_next_candidate_theme()
    """

    def __init__(self, theme_loader: Optional[ThemeLoader] = None, use_networkx: bool = True):
        """
        初始化图谱管理器

        Args:
            theme_loader: 主题加载器，如果为None则创建默认实例
            use_networkx: 是否使用 NetworkX，如果为 False 使用简单的内存结构
        """
        self.theme_loader = theme_loader or ThemeLoader()
        self.use_networkx = use_networkx and HAS_NETWORKX

        if self.use_networkx:
            self.graph = nx.DiGraph()
            logger.info("使用 NetworkX 管理图谱")
        else:
            self.graph = {}  # 简单的邻接表结构
            logger.info("使用简单内存结构管理图谱")

        self.theme_nodes: Dict[str, ThemeNode] = {}
        self.event_nodes: Dict[str, EventNode] = {}

        self._initialize_graph()

    def _initialize_graph(self):
        """
        初始化图谱

        将23个主题节点作为"虚线节点"添加到图谱中
        """
        # 加载主题定义
        self.theme_nodes = self.theme_loader.load()

        if self.use_networkx:
            # 使用 NetworkX
            for theme_id, theme_node in self.theme_nodes.items():
                self.graph.add_node(
                    theme_id,
                    node_type="theme",
                    status=NodeStatus.PENDING.value,
                    data=theme_node.to_dict()
                )

                # 添加依赖关系
                for dep_id in theme_node.depends_on:
                    if dep_id in self.theme_nodes:
                        self.graph.add_edge(dep_id, theme_id, relation_type="dependency")
        else:
            # 使用简单结构
            self.graph["nodes"] = {}
            self.graph["edges"] = {}

            for theme_id, theme_node in self.theme_nodes.items():
                self.graph["nodes"][theme_id] = {
                    "node_type": "theme",
                    "status": NodeStatus.PENDING.value,
                    "data": theme_node.to_dict()
                }

                # 添加依赖关系
                for dep_id in theme_node.depends_on:
                    if dep_id not in self.graph["edges"]:
                        self.graph["edges"][dep_id] = []
                    self.graph["edges"][dep_id].append(theme_id)

        logger.info(f"图谱初始化完成，加载了 {len(self.theme_nodes)} 个主题节点")

    def add_event_node(self, event: EventNode, theme_id: str) -> bool:
        """
        添加事件节点到图谱

        Args:
            event: 事件节点
            theme_id: 关联的主题ID

        Returns:
            bool: 是否添加成功
        """
        if theme_id not in self.theme_nodes:
            logger.warning(f"主题不存在: {theme_id}")
            return False

        self.event_nodes[event.event_id] = event

        if self.use_networkx:
            # 使用 NetworkX
            self.graph.add_node(
                event.event_id,
                node_type="event",
                status="active",
                data=event.to_dict()
            )

            # 建立事件与主题的关联
            self.graph.add_edge(theme_id, event.event_id, relation_type="contains")
        else:
            # 使用简单结构
            self.graph["nodes"][event.event_id] = {
                "node_type": "event",
                "status": "active",
                "data": event.to_dict()
            }

            # 建立事件与主题的关联
            if theme_id not in self.graph["edges"]:
                self.graph["edges"][theme_id] = []
            if event.event_id not in self.graph["edges"][theme_id]:
                self.graph["edges"][theme_id].append(event.event_id)

        # 更新主题状态
        theme = self.theme_nodes.get(theme_id)
        if theme:
            theme.add_extracted_event(event.event_id)
            # 增加主题的挖掘深度
            theme.increment_depth()
            if theme.status == NodeStatus.PENDING:
                theme.mark_mentioned()
                self._update_node_status(theme_id, NodeStatus.MENTIONED)

        logger.debug(f"添加事件节点: {event.event_id} -> {theme_id}")
        return True

    def update_event_depth(self, event_id: str, new_depth: int) -> bool:
        """
        更新事件节点的挖掘深度

        Args:
            event_id: 事件ID
            new_depth: 新的深度值

        Returns:
            bool: 是否更新成功
        """
        event = self.event_nodes.get(event_id)
        if event:
            event.depth_level = min(new_depth, 5)

            if self.use_networkx:
                if event_id in self.graph.nodes:
                    self.graph.nodes[event_id]["data"]["depth_level"] = event.depth_level
            else:
                if event_id in self.graph["nodes"]:
                    self.graph["nodes"][event_id]["data"]["depth_level"] = event.depth_level

            return True
        return False

    def mark_theme_exhausted(self, theme_id: str) -> bool:
        """
        标记主题为已完成

        Args:
            theme_id: 主题ID

        Returns:
            bool: 是否标记成功
        """
        theme = self.theme_nodes.get(theme_id)
        if theme:
            theme.mark_exhausted()
            self._update_node_status(theme_id, NodeStatus.EXHAUSTED)
            logger.info(f"主题已完成: {theme_id}")
            return True
        return False

    def _update_node_status(self, node_id: str, status: NodeStatus):
        """
        更新图谱中节点的状态

        Args:
            node_id: 节点ID
            status: 新状态
        """
        if self.use_networkx:
            if node_id in self.graph.nodes:
                self.graph.nodes[node_id]["status"] = status.value
                if "data" in self.graph.nodes[node_id]:
                    self.graph.nodes[node_id]["data"]["status"] = status.value
        else:
            if node_id in self.graph["nodes"]:
                self.graph["nodes"][node_id]["status"] = status.value
                self.graph["nodes"][node_id]["data"]["status"] = status.value

    def calculate_coverage(self) -> Dict[str, float]:
        """
        计算覆盖率

        Returns:
            包含以下字段的字典：
            - overall: 总体覆盖率
            - by_domain: 各领域覆盖率
        """
        total_themes = len(self.theme_nodes)
        if total_themes == 0:
            return {"overall": 0.0, "by_domain": {}}

        # 计算每个主题的完成度
        theme_completions = []
        domain_completions = {}

        for theme_id, theme in self.theme_nodes.items():
            completion = theme.get_completion_ratio()
            theme_completions.append(completion)

            # 按领域统计
            domain = theme.domain.value
            if domain not in domain_completions:
                domain_completions[domain] = []
            domain_completions[domain].append(completion)

        # 总体覆盖率
        overall = sum(theme_completions) / total_themes

        # 各领域覆盖率
        by_domain = {}
        for domain, completions in domain_completions.items():
            by_domain[domain] = sum(completions) / len(completions)

        return {
            "overall": overall,
            "by_domain": by_domain,
        }

    def get_pending_theme_nodes(self) -> List[ThemeNode]:
        """
        获取所有待触达的主题节点

        Returns:
            待触达的主题节点列表
        """
        return [
            node for node in self.theme_nodes.values()
            if node.status == NodeStatus.PENDING
        ]

    def get_mentioned_theme_nodes(self) -> List[ThemeNode]:
        """
        获取所有已提及但未完成的主题节点

        Returns:
            已提及但未完成的主题节点列表
        """
        return [
            node for node in self.theme_nodes.values()
            if node.status == NodeStatus.MENTIONED
        ]

    def get_exhausted_theme_nodes(self) -> List[ThemeNode]:
        """
        获取所有已完成的主题节点

        Returns:
            已完成的主题节点列表
        """
        return [
            node for node in self.theme_nodes.values()
            if node.status == NodeStatus.EXHAUSTED
        ]

    def get_next_candidate_theme(self, current_focus: Optional[str] = None) -> Optional[ThemeNode]:
        """
        获取下一个候选主题

        策略：
        1. 如果有已提及但未完成的主题，优先继续
        2. 否则选择优先级最高的待触达主题
        3. 考虑与当前焦点主题的关联性

        Args:
            current_focus: 当前焦点主题ID

        Returns:
            下一个建议探索的主题节点
        """
        # 首先检查已提及但未完成的
        mentioned = self.get_mentioned_theme_nodes()
        if mentioned:
            # 选择完成度最低的
            return min(mentioned, key=lambda n: n.get_completion_ratio())

        # 然后检查待触达的
        pending = [
            node for node in self.theme_nodes.values()
            if node.status == NodeStatus.PENDING and node.is_ready_to_explore(self.theme_nodes)
        ]

        if not pending:
            return None

        # 按优先级排序
        return min(pending, key=lambda n: n.priority)

    def get_theme_status(self, theme_id: str) -> Optional[Dict]:
        """
        获取特定主题的详细状态

        Args:
            theme_id: 主题ID

        Returns:
            主题状态字典，如果主题不存在返回 None
        """
        theme = self.theme_nodes.get(theme_id)
        if not theme:
            return None

        return {
            "theme_id": theme.theme_id,
            "title": theme.title,
            "status": theme.status.value,
            "completion_ratio": theme.get_completion_ratio(),
            "exploration_depth": theme.exploration_depth,
            "slots_filled": theme.slots_filled,
            "extracted_events_count": len(theme.extracted_events),
            "has_more_questions": theme.has_more_questions(),
        }

    def get_graph_state(self) -> Dict:
        """
        获取图谱当前状态摘要

        Returns:
            图谱状态摘要字典
        """
        coverage = self.calculate_coverage()

        return {
            "coverage_metrics": {
                "overall_coverage": coverage["overall"],
                "domain_coverage": coverage["by_domain"],
            },
            "theme_count": len(self.theme_nodes),
            "event_count": len(self.event_nodes),
            "pending_themes": len(self.get_pending_theme_nodes()),
            "mentioned_themes": len(self.get_mentioned_theme_nodes()),
            "exhausted_themes": len(self.get_exhausted_theme_nodes()),
            "timestamp": datetime.now().isoformat(),
        }

    def save_checkpoint(self, session_id: str, output_dir: Optional[Path] = None) -> bool:
        """
        保存断点

        Args:
            session_id: 会话ID
            output_dir: 输出目录

        Returns:
            bool: 是否保存成功
        """
        if output_dir is None:
            current_dir = Path(__file__).parent.parent
            output_dir = current_dir / "data" / "interviews" / session_id

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 保存图谱状态
            if self.use_networkx:
                graph_data = nx.node_link_data(self.graph)
            else:
                graph_data = self.graph

            with open(output_dir / "graph_state.json", "w", encoding="utf-8") as f:
                json.dump(graph_data, f, ensure_ascii=False, indent=2)

            # 保存主题状态
            themes_data = {
                theme_id: node.to_dict()
                for theme_id, node in self.theme_nodes.items()
            }
            with open(output_dir / "themes_state.json", "w", encoding="utf-8") as f:
                json.dump(themes_data, f, ensure_ascii=False, indent=2)

            # 保存事件
            events_data = {
                event_id: node.to_dict()
                for event_id, node in self.event_nodes.items()
            }
            with open(output_dir / "events.json", "w", encoding="utf-8") as f:
                json.dump(events_data, f, ensure_ascii=False, indent=2)

            logger.info(f"断点已保存到: {output_dir}")
            return True

        except Exception as e:
            logger.error(f"保存断点失败: {e}")
            return False

    def load_checkpoint(self, session_id: str, input_dir: Optional[Path] = None) -> bool:
        """
        加载断点

        Args:
            session_id: 会话ID
            input_dir: 输入目录

        Returns:
            bool: 是否加载成功
        """
        if input_dir is None:
            current_dir = Path(__file__).parent.parent
            input_dir = current_dir / "data" / "interviews" / session_id

        try:
            # 加载图谱状态
            with open(input_dir / "graph_state.json", "r", encoding="utf-8") as f:
                graph_data = json.load(f)

                if self.use_networkx:
                    self.graph = nx.node_link_graph(graph_data)
                else:
                    self.graph = graph_data

            # 加载主题状态
            with open(input_dir / "themes_state.json", "r", encoding="utf-8") as f:
                themes_data = json.load(f)

                for theme_id, theme_dict in themes_data.items():
                    if theme_id in self.theme_nodes:
                        # 更新现有主题节点
                        theme = self.theme_nodes[theme_id]
                        theme.status = NodeStatus(theme_dict["status"])
                        theme.exploration_depth = theme_dict.get("exploration_depth", 0)
                        theme.slots_filled = theme_dict.get("slots_filled", {})

            # 加载事件
            with open(input_dir / "events.json", "r", encoding="utf-8") as f:
                events_data = json.load(f)

                for event_id, event_dict in events_data.items():
                    event = EventNode.from_dict(event_dict)
                    self.event_nodes[event_id] = event

            logger.info(f"断点已从 {input_dir} 加载")
            return True

        except FileNotFoundError:
            logger.warning(f"断点文件不存在: {input_dir}")
            return False
        except Exception as e:
            logger.error(f"加载断点失败: {e}")
            return False

    def reset(self):
        """重置图谱到初始状态"""
        self.event_nodes.clear()
        self._initialize_graph()
        logger.info("图谱已重置")
