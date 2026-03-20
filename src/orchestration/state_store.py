from __future__ import annotations

from typing import Dict, Optional

from src.state import SessionState


class InMemorySessionStateStore:
    def __init__(self):
        self._states: Dict[str, SessionState] = {}

    def save(self, state: SessionState) -> SessionState:
        state.touch()
        self._states[state.session_id] = state
        return state

    def get(self, session_id: str) -> Optional[SessionState]:
        return self._states.get(session_id)

    def delete(self, session_id: str) -> None:
        self._states.pop(session_id, None)
