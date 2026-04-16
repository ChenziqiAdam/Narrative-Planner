"""Neo4jGraphAdapter — drop-in replacement for GraphManager.

Maintains in-memory ``theme_nodes`` / ``event_nodes`` dicts for
millisecond-level reads (essential for PlannerDecisionPolicy) while
persisting every write to Neo4j.  On startup the adapter loads state
from Neo4j; if the database is empty it falls back to the theme loader.

Public interface mirrors ``src.core.graph_manager.GraphManager``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import Config
from src.core.event_node import EventNode
from src.core.node_status import NodeStatus
from src.core.theme_loader import ThemeLoader
from src.core.theme_node import ThemeNode
from src.services.coverage_cache import CoverageCache
from src.storage.neo4j.driver import Neo4jGraphDriver
from src.storage.neo4j.manager import Neo4jGraphManager
from src.storage.neo4j.models import TopicNode, EventNodeNeo4j

logger = logging.getLogger(__name__)


class Neo4jGraphAdapter:
    """GraphManager-compatible adapter backed by Neo4j + in-memory cache."""

    def __init__(
        self,
        theme_loader: Optional[ThemeLoader] = None,
        neo4j_driver: Optional[Neo4jGraphDriver] = None,
    ):
        self.theme_loader = theme_loader or ThemeLoader()

        # In-memory dicts — same as GraphManager, used for fast reads.
        self.theme_nodes: Dict[str, ThemeNode] = {}
        self.event_nodes: Dict[str, EventNode] = {}

        # Neo4j backend — lazy-initialised on first write.
        self._neo4j_mgr: Optional[Neo4jGraphManager] = None
        self._neo4j_driver = neo4j_driver
        self._neo4j_ready = False

        # CoverageCache — populated from Neo4j Cypher aggregation.
        self.coverage_cache = CoverageCache()

        # Initialise themes in memory (same as GraphManager).
        self._initialize_themes()

    # ────────────────────────────────────────────────────────
    # Neo4j lifecycle
    # ────────────────────────────────────────────────────────

    def _ensure_neo4j(self) -> Neo4jGraphManager:
        if self._neo4j_mgr is None:
            driver = self._neo4j_driver or Neo4jGraphDriver()
            self._neo4j_mgr = Neo4jGraphManager(driver)
        if not self._neo4j_ready:
            try:
                self._neo4j_mgr.initialize()
                self._neo4j_ready = True
            except Exception:
                logger.warning("Neo4j not available — operating in memory-only mode", exc_info=True)
                self._neo4j_ready = False
        return self._neo4j_mgr

    def close(self) -> None:
        if self._neo4j_mgr:
            self._neo4j_mgr.close()

    # ────────────────────────────────────────────────────────
    # Initialisation (same as GraphManager)
    # ────────────────────────────────────────────────────────

    def _initialize_themes(self) -> None:
        self.theme_nodes = self.theme_loader.load()
        logger.info("Loaded %d theme nodes", len(self.theme_nodes))

    # ────────────────────────────────────────────────────────
    # GraphManager-compatible public interface
    # ────────────────────────────────────────────────────────

    def add_event_node(self, event: EventNode, theme_id: str) -> bool:
        if theme_id not in self.theme_nodes:
            logger.warning("Theme not found: %s", theme_id)
            return False

        # In-memory update (identical to GraphManager).
        self.event_nodes[event.event_id] = event
        theme = self.theme_nodes[theme_id]
        theme.add_extracted_event(event.event_id)
        # NOTE: depth increment is done in GraphProjector._update_theme_slots()
        # to avoid double-increment (it also calls theme.increment_depth()).
        if theme.status == NodeStatus.PENDING:
            theme.mark_mentioned()
            self._update_theme_status(theme_id, NodeStatus.MENTIONED)

        # Neo4j write (best-effort).
        self._persist_event(event, theme_id)
        logger.debug("Added event %s -> %s", event.event_id, theme_id)
        return True

    def update_event_depth(self, event_id: str, new_depth: int) -> bool:
        event = self.event_nodes.get(event_id)
        if not event:
            return False
        event.depth_level = min(new_depth, 5)
        # Update Neo4j
        mgr = self._ensure_neo4j()
        if self._neo4j_ready:
            mgr.driver.execute_query(
                "MATCH (e:Event {id: $id}) SET e.depth_level = $depth RETURN e",
                {"id": event_id, "depth": event.depth_level},
            )
        return True

    def mark_theme_exhausted(self, theme_id: str) -> bool:
        theme = self.theme_nodes.get(theme_id)
        if not theme:
            return False
        theme.mark_exhausted()
        self._update_theme_status(theme_id, NodeStatus.EXHAUSTED)
        if self._neo4j_ready:
            self._ensure_neo4j().update_topic_status(theme_id, "exhausted")
        logger.info("Theme exhausted: %s", theme_id)
        return True

    def _update_theme_status(self, theme_id: str, status: NodeStatus) -> None:
        """Backward compat — same as GraphManager._update_node_status."""
        # In-memory already updated by ThemeNode methods above.

        # Also persist to Neo4j.
        if self._neo4j_ready:
            self._ensure_neo4j().update_topic_status(theme_id, status.value)

    def calculate_coverage(self) -> Dict[str, float]:
        if self._neo4j_ready:
            cached = self.coverage_cache.get_all()
            return {"overall": cached["overall"], "by_domain": cached["by_domain"]}
        return self._calculate_coverage_from_memory()

    def calculate_slot_coverage(self) -> Dict[str, float]:
        if self._neo4j_ready:
            cached = self.coverage_cache.get_all()
            return cached["slot_coverage"]
        return self._calculate_slot_coverage_from_memory()

    def _calculate_coverage_from_memory(self) -> Dict[str, float]:
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

    def _calculate_slot_coverage_from_memory(self) -> Dict[str, float]:
        events = list(self.event_nodes.values())
        if not events:
            return {s: 0.0 for s in ("time", "location", "people", "event", "reflection")}

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
            n for n in self.theme_nodes.values()
            if n.status == NodeStatus.PENDING and n.is_ready_to_explore(self.theme_nodes)
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

            logger.info("Checkpoint saved to %s", output_dir)
            return True
        except Exception:
            logger.exception("Failed to save checkpoint")
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

            logger.info("Checkpoint loaded from %s", input_dir)
            return True
        except FileNotFoundError:
            logger.warning("Checkpoint not found: %s", input_dir)
            return False
        except Exception:
            logger.exception("Failed to load checkpoint")
            return False

    def reset(self) -> None:
        self.event_nodes.clear()
        self._initialize_themes()
        logger.info("Graph adapter reset")

    # ────────────────────────────────────────────────────────
    # Neo4j-specific persistence helpers
    # ────────────────────────────────────────────────────────

    def _persist_event(self, event: EventNode, theme_id: str) -> None:
        """Best-effort persist an event + its Topic link to Neo4j."""
        try:
            mgr = self._ensure_neo4j()
            if not self._neo4j_ready:
                return
            neo4j_event = EventNodeNeo4j(
                id=event.event_id,
                name=event.title,
                description=event.description,
                theme_id=theme_id,
                title=event.title,
                time_anchor=event.time_anchor,
                location=event.location,
                people_involved=list(event.people_involved),
                slots=dict(event.slots),
                emotional_score=event.emotional_score,
                information_density=event.information_density,
                depth_level=event.depth_level,
            )
            mgr.upsert_event(neo4j_event, theme_id)
            # Also update the Topic's extracted_events list.
            mgr.add_event_to_topic(theme_id, event.event_id)
        except Exception:
            logger.debug("Neo4j persist failed for event %s", event.event_id, exc_info=True)

    def _persist_theme_update(self, theme_id: str, theme: ThemeNode) -> None:
        """Sync theme slots_filled and depth to Neo4j Topic node."""
        try:
            mgr = self._ensure_neo4j()
            if not self._neo4j_ready:
                return
            mgr.update_topic_slots(theme_id, theme.slots_filled)
            # Sync exploration_depth.
            mgr.driver.execute_query(
                "MATCH (t:Topic {id: $id}) SET t.exploration_depth = $depth RETURN t",
                {"id": theme_id, "depth": theme.exploration_depth},
            )
        except Exception:
            logger.debug("Neo4j theme update failed for %s", theme_id, exc_info=True)

    def _refresh_coverage_cache(self) -> None:
        """Refresh CoverageCache from Neo4j Cypher aggregation."""
        if not self._neo4j_ready:
            return
        try:
            mgr = self._ensure_neo4j()
            metrics = mgr.get_coverage_metrics()
            self.coverage_cache.refresh_from_metrics(metrics)
        except Exception:
            logger.debug("Coverage cache refresh from Neo4j failed", exc_info=True)

    def sync_themes_to_neo4j(self) -> int:
        """Bulk-push all in-memory themes to Neo4j.  Returns count synced."""
        mgr = self._ensure_neo4j()
        if not self._neo4j_ready:
            return 0
        topics = [TopicNode.from_theme_node(t) for t in self.theme_nodes.values()]
        return mgr.batch_upsert_topics(topics)

    def load_themes_from_neo4j(self) -> bool:
        """Load theme state from Neo4j, overriding in-memory defaults."""
        mgr = self._ensure_neo4j()
        if not self._neo4j_ready:
            return False
        neo4j_topics = mgr.get_all_topics()
        if not neo4j_topics:
            return False
        for theme_id, props in neo4j_topics.items():
            theme = self.theme_nodes.get(theme_id)
            if not theme:
                continue
            status_str = props.get("status", "pending")
            try:
                theme.status = NodeStatus(status_str)
            except ValueError:
                pass
            theme.exploration_depth = int(props.get("exploration_depth", 0) or 0)
            slots_raw = props.get("slots_filled", {})
            if isinstance(slots_raw, str):
                try:
                    slots_raw = json.loads(slots_raw)
                except (json.JSONDecodeError, TypeError):
                    slots_raw = {}
            if isinstance(slots_raw, dict):
                theme.slots_filled = {k: bool(v) for k, v in slots_raw.items()}
        logger.info("Loaded %d theme states from Neo4j", len(neo4j_topics))
        return True

    # ────────────────────────────────────────────────────────
    # Neo4j-specific query helpers (for Phase 3)
    # ────────────────────────────────────────────────────────

    def get_neo4j_manager(self) -> Optional[Neo4jGraphManager]:
        if self._neo4j_ready:
            return self._neo4j_mgr
        return None

    def query_related_themes(self, theme_id: str, hop: int = 2) -> List[Dict[str, Any]]:
        """N-hop theme relationship query."""
        mgr = self.get_neo4j_manager()
        if mgr:
            return mgr.get_related_themes(theme_id, hop)
        return []

    def detect_patterns(self) -> List[Dict[str, Any]]:
        mgr = self.get_neo4j_manager()
        if mgr:
            return mgr.detect_patterns()
        return []
