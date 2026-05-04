"""Helpers for retrying transient LLM provider failures."""

from __future__ import annotations

import time
from typing import Any


_TRANSIENT_ERROR_MARKERS = (
    "429",
    "rate_limit",
    "rate limit",
    "too many requests",
    "engine_overloaded",
    "overloaded",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "502",
    "503",
    "504",
    "service unavailable",
)


def is_transient_llm_error(error: Exception) -> bool:
    """Return True when an LLM API error is likely recoverable by retrying."""
    status_code = getattr(error, "status_code", None)
    if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True

    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    if response_status in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True

    message = str(error).lower()
    return any(marker in message for marker in _TRANSIENT_ERROR_MARKERS)


def retry_delay_seconds(attempt: int, base_seconds: float = 0.8, cap_seconds: float = 6.0) -> float:
    """Small exponential backoff for human-facing chat flows."""
    return min(cap_seconds, base_seconds * (2 ** max(0, attempt - 1)))


def sleep_before_retry(error: Exception, attempt: int) -> float:
    """Sleep before a retry and return the delay used."""
    delay = _retry_after(error) or retry_delay_seconds(attempt)
    time.sleep(delay)
    return delay


def _retry_after(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers: Any = getattr(response, "headers", None)
    if not headers:
        return None
    value = None
    if hasattr(headers, "get"):
        value = headers.get("retry-after") or headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, min(float(value), 10.0))
    except (TypeError, ValueError):
        return None
