from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


class Timer:
    _SENTINEL = object()

    def __init__(self):
        self._start: float = 0.0
        self._end = self._SENTINEL

    def __enter__(self) -> Timer:
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
    interviewee_llm_ms: Optional[float] = None
    interviewee_tool_ms: Optional[float] = None
    interviewee_total_ms: Optional[float] = None
    interviewer_llm_ms: Optional[float] = None
    # GraphRAG pipeline
    retrieval_ms: Optional[float] = None
    extraction_ms: Optional[float] = None
    write_ms: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in vars(self).items() if v is not None}


@dataclass
class TurnTokenUsage:
    """Per-module token counts for one interview turn."""
    interviewer_prompt_tokens: Optional[int] = None
    interviewer_completion_tokens: Optional[int] = None
    extraction_prompt_tokens: Optional[int] = None
    extraction_completion_tokens: Optional[int] = None
    interviewee_prompt_tokens: Optional[int] = None
    interviewee_completion_tokens: Optional[int] = None

    @property
    def total_prompt_tokens(self) -> Optional[int]:
        vals = [self.interviewer_prompt_tokens, self.extraction_prompt_tokens,
                self.interviewee_prompt_tokens]
        valid = [v for v in vals if v is not None]
        return sum(valid) if valid else None

    @property
    def total_completion_tokens(self) -> Optional[int]:
        vals = [self.interviewer_completion_tokens, self.extraction_completion_tokens,
                self.interviewee_completion_tokens]
        valid = [v for v in vals if v is not None]
        return sum(valid) if valid else None

    def to_dict(self) -> dict:
        d = {k: v for k, v in vars(self).items() if v is not None}
        if self.total_prompt_tokens is not None:
            d["total_prompt_tokens"] = self.total_prompt_tokens
        if self.total_completion_tokens is not None:
            d["total_completion_tokens"] = self.total_completion_tokens
        return d
