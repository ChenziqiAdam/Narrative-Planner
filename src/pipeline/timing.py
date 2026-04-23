# src/pipeline/timing.py
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Optional


class Timer:
    _SENTINEL = object()

    def __init__(self):
        self._start: float = 0.0
        self._end = self._SENTINEL

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        self._end = self._SENTINEL
        return self

    def __exit__(self, *_) -> None:
        self._end = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        if self._end is self._SENTINEL:
            raise RuntimeError("Timer.elapsed_ms accessed before context manager exited.")
        return (self._end - self._start) * 1000.0  # type: ignore[operator]


@dataclass
class TurnTiming:
    """Per-module timing for one interview turn (all values in ms)."""
    interviewee_llm_ms: Optional[float] = None    # LLM call time (sum across retries)
    interviewee_tool_ms: Optional[float] = None   # total tool execution time
    interviewee_total_ms: Optional[float] = None  # wall time for full step_with_metadata
    interviewer_llm_ms: Optional[float] = None    # get_next_question wall time
    # Planner-only (None in baseline mode)
    extraction_ms: Optional[float] = None
    merge_ms: Optional[float] = None
    graph_ms: Optional[float] = None
    memory_ms: Optional[float] = None
    coverage_ms: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in vars(self).items() if v is not None}
