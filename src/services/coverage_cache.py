"""CoverageCache — in-memory coverage metrics refreshed after each Neo4j write.

Provides sub-millisecond reads for PlannerDecisionPolicy signal
computation while ensuring data freshness by coupling refresh calls
to the write path in ``Neo4jGraphAdapter``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from src.core.graph_manager import GraphManager

logger = logging.getLogger(__name__)


class CoverageCache:
    """Thread-safe coverage cache backed by a GraphManager-compatible source."""

    def __init__(self, source: Any = None):
        # ``source`` is expected to be a GraphManager or Neo4jGraphAdapter.
        self._source = source
        self._lock = threading.Lock()
        self._metrics: Dict[str, Any] = {
            "overall": 0.0,
            "by_domain": {},
            "slot_coverage": {},
        }

    # ── Refresh ──

    def refresh(self, source: Optional[Any] = None) -> None:
        """Re-compute coverage from the graph source."""
        src = source or self._source
        if src is None:
            return
        try:
            coverage = src.calculate_coverage()
            slot_coverage = src.calculate_slot_coverage()
            with self._lock:
                self._metrics = {
                    "overall": coverage.get("overall", 0.0),
                    "by_domain": coverage.get("by_domain", {}),
                    "slot_coverage": slot_coverage,
                }
        except Exception:
            logger.debug("CoverageCache refresh failed", exc_info=True)

    # ── Fast reads ──

    @property
    def overall(self) -> float:
        with self._lock:
            return self._metrics["overall"]

    @property
    def by_domain(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._metrics["by_domain"])

    @property
    def slot_coverage(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._metrics["slot_coverage"])

    def get_all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._metrics)
