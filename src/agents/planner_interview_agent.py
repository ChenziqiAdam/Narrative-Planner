#!/usr/bin/env python3
"""
Planner interview agent backed by the new session orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.orchestration import SessionOrchestrator


logger = logging.getLogger(__name__)


class PlannerInterviewAgent:
    """
    Thin compatibility wrapper around the orchestrated multi-agent runtime.

    Public methods intentionally mirror the previous implementation so the
    existing Flask compare endpoints can keep working unchanged.
    """

    def __init__(self, session_id: str | None = None, decision_weights: Optional[Any] = None):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.orchestrator = SessionOrchestrator(
            self.session_id,
            mode="planner",
            decision_weights=decision_weights,
        )
        self._initialized = False

    def initialize_conversation(self, elder_info: Dict[str, Any]):
        self.orchestrator.initialize_session(elder_info)
        self._initialized = True
        logger.info("PlannerInterviewAgent initialized (session=%s)", self.session_id)

    async def get_next_question(self, user_response: str | None = None) -> Dict[str, Any]:
        if not self._initialized:
            raise RuntimeError("PlannerInterviewAgent must be initialized before use.")

        if user_response is None:
            return self.orchestrator.get_pending_question_result()
        return await self.orchestrator.process_user_response(user_response)

    def get_graph_state(self) -> Dict[str, Any]:
        return self.orchestrator.get_graph_state()

    def get_evaluation_state(self) -> Dict[str, Any]:
        return self.orchestrator.get_evaluation_state()

    def get_conversation_history(self) -> List[Dict[str, str]]:
        return self.orchestrator.build_conversation_history()

    def save_conversation(self) -> str:
        return self.orchestrator.save_session()

    async def close(self) -> None:
        await self.orchestrator.close()


class PlannerInterviewAgentSync:
    """Synchronous adapter for Flask handlers."""

    def __init__(self, session_id: str | None = None, decision_weights: Optional[Any] = None):
        self.async_agent = PlannerInterviewAgent(session_id, decision_weights=decision_weights)
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def initialize_conversation(self, elder_info: Dict[str, Any]):
        self.async_agent.initialize_conversation(elder_info)

    def get_next_question(self, user_response: str | None = None) -> Dict[str, Any]:
        return self.loop.run_until_complete(self.async_agent.get_next_question(user_response))

    def get_graph_state(self) -> Dict[str, Any]:
        return self.async_agent.get_graph_state()

    def get_evaluation_state(self) -> Dict[str, Any]:
        return self.async_agent.get_evaluation_state()

    def get_conversation_history(self) -> List[Dict[str, str]]:
        return self.async_agent.get_conversation_history()

    def save_conversation(self) -> str:
        return self.async_agent.save_conversation()

    def close(self):
        self.loop.run_until_complete(self.async_agent.close())
        self.loop.close()
