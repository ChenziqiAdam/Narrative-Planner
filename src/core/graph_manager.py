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
from typing import Dict, List, Optional
from datetime import datetime

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

    def __init__(self, theme_loader: Optional[ThemeLoader] = None):
        self.theme_loader = theme_loader or ThemeLoader()
        self.theme_nodes: Dict[str, ThemeNode] = {}
        self.event_nodes: Dict[str, EventNode] = {}
        self._initialize_graph()

    def _initialize_graph(self):
        """初始化图谱，加载23个主题节点。"""
        self.theme_nodes = self.theme_loader.load()
        logger.info("图谱初始化完成，加载了 %d 个主题节点", len(self.theme_nodes))

    def add_event_node(self, event: EventNode, theme_id: str) -> bool:
        if theme_id not in self.theme_nodes:
            logger.warning("主题不存在: %s", theme_id)
            return False

        self.event_nodes[event.event_id] = event
        theme = self.theme_nodes.get(theme_id)
        if theme:
            theme.add_extracted_event(event.event_id)
            theme.increment_depth()
            if theme.status == NodeStatus.PENDING:
                theme.mark_mentioned()
                self._update_node_status(theme_id, NodeStatus.MENTIONED)

        logger.debug("添加事件节点: %s -> %s", event.event_id, theme_id)
        return True

    def update_event_depth(self, event_id: str, new_depth: int) -> bool:
        event = self.event_nodes.get(event_id)
        if event:
            event.depth_level = min(new_depth, 5)
            return True
        return False

    def mark_theme_exhausted(self, theme_id: str) -> bool:
        theme = self.theme_nodes.get(theme_id)
        if theme:
            theme.mark_exhausted()
            self._update_node_status(theme_id, NodeStatus.EXHAUSTED)
            logger.info("主题已完成: %s", theme_id)
            return True
        return False

    def _update_node_status(self, node_id: str, status: NodeStatus):
        """Hook for subclasses (e.g. Neo4jGraphAdapter) to override."""
        pass

    def calculate_coverage(self) -> Dict[str, float]:
        total_themes = len(self.theme_nodes)
        if total_themes == 0:
            return {"overall": 0.0, "by_domain": {}}

        theme_completions = []
        domain_completions: Dict[str, List[float]] = {}

        for theme_id, theme in self.theme_nodes.items():
            completion = theme.get_completion_ratio()
            theme_completions.append(completion)
            domain = theme.domain.value
            domain_completions.setdefault(domain, []).append(completion)

        overall = sum(theme_completions) / total_themes
        by_domain = {d: sum(v) / len(v) for d, v in domain_completions.items()}

        return {"overall": overall, "by_domain": by_domain}

    def calculate_slot_coverage(self) -> Dict[str, float]:
        events = list(self.event_nodes.values())
        if not events:
            return {"time": 0.0, "location": 0.0, "people": 0.0, "event": 0.0, "reflection": 0.0}

        slot_keys = ["time", "location", "people", "event", "reflection"]
        coverage = {}
        for slot_name in slot_keys:
            filled = sum(1 for e in events if e.slots.get(slot_name))
            coverage[slot_name] = filled / len(events)
        return coverage

    def get_pending_theme_nodes(self) -> List[ThemeNode]:
        return [n for n in self.theme_nodes.values() if n.status == NodeStatus.PENDING]

    def get_mentioned_theme_nodes(self) -> List[ThemeNode]:
        return [n for n in self.theme_nodes.values() if n.status == NodeStatus.MENTIONED]

    def get_exhausted_theme_nodes(self) -> List[ThemeNode]:
        return [n for n in self.theme_nodes.values() if n.status == NodeStatus.EXHAUSTED]

    def get_next_candidate_theme(self, current_focus: Optional[str] = None) -> Optional[ThemeNode]:
        mentioned = self.get_mentioned_theme_nodes()
        if mentioned:
            return min(mentioned, key=lambda n: n.get_completion_ratio())

        pending = [
            node for node in self.theme_nodes.values()
            if node.status == NodeStatus.PENDING and node.is_ready_to_explore(self.theme_nodes)
        ]
        if not pending:
            return None
        return min(pending, key=lambda n: n.priority)

    def get_theme_status(self, theme_id: str) -> Optional[Dict]:
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
        coverage = self.calculate_coverage()
        slot_coverage = self.calculate_slot_coverage()
        return {
            "coverage_metrics": {
                "overall_coverage": coverage["overall"],
                "domain_coverage": coverage["by_domain"],
                "slot_coverage": slot_coverage,
            },
            "theme_count": len(self.theme_nodes),
            "event_count": len(self.event_nodes),
            "pending_themes": len(self.get_pending_theme_nodes()),
            "mentioned_themes": len(self.get_mentioned_theme_nodes()),
            "exhausted_themes": len(self.get_exhausted_theme_nodes()),
            "timestamp": datetime.now().isoformat(),
        }

    def save_checkpoint(self, session_id: str, output_dir: Optional[Path] = None) -> bool:
        if output_dir is None:
            current_dir = Path(__file__).parent.parent
            output_dir = current_dir / "data" / "interviews" / session_id

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            themes_data = {tid: node.to_dict() for tid, node in self.theme_nodes.items()}
            with open(output_dir / "themes_state.json", "w", encoding="utf-8") as f:
                json.dump(themes_data, f, ensure_ascii=False, indent=2)

            events_data = {eid: node.to_dict() for eid, node in self.event_nodes.items()}
            with open(output_dir / "events.json", "w", encoding="utf-8") as f:
                json.dump(events_data, f, ensure_ascii=False, indent=2)

            logger.info("断点已保存到: %s", output_dir)
            return True
        except Exception:
            logger.exception("保存断点失败")
            return False

    def load_checkpoint(self, session_id: str, input_dir: Optional[Path] = None) -> bool:
        if input_dir is None:
            current_dir = Path(__file__).parent.parent
            input_dir = current_dir / "data" / "interviews" / session_id

        try:
            with open(input_dir / "themes_state.json", "r", encoding="utf-8") as f:
                for tid, data in json.load(f).items():
                    if tid in self.theme_nodes:
                        theme = self.theme_nodes[tid]
                        theme.status = NodeStatus(data["status"])
                        theme.exploration_depth = data.get("exploration_depth", 0)
                        theme.slots_filled = data.get("slots_filled", {})

            with open(input_dir / "events.json", "r", encoding="utf-8") as f:
                for eid, data in json.load(f).items():
                    self.event_nodes[eid] = EventNode.from_dict(data)

            logger.info("断点已从 %s 加载", input_dir)
            return True
        except FileNotFoundError:
            logger.warning("断点文件不存在: %s", input_dir)
            return False
        except Exception:
            logger.exception("加载断点失败")
            return False

    def reset(self):
        self.event_nodes.clear()
        self._initialize_graph()
        logger.info("图谱已重置")
