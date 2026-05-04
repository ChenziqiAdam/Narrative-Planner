import unittest
from types import SimpleNamespace
from unittest.mock import patch


class _FailingCompletion:
    def create(self, **kwargs):
        raise Exception(
            "Error code: 429 - {'error': {'message': 'The engine is currently "
            "overloaded, please try again later', 'type': 'engine_overloaded_error'}}"
        )


class _FakeChat:
    def __init__(self):
        self.completions = _FailingCompletion()


class LLMRetryTest(unittest.TestCase):
    def test_interviewee_overloaded_error_returns_fallback_answer(self):
        from src.agents import interviewee_agent
        from src.agents.interviewee_agent import DEFAULT_REPLY_FALLBACK, IntervieweeAgent
        from src.config import Config

        agent = IntervieweeAgent.__new__(IntervieweeAgent)
        agent.sys_prompt = "system"
        agent.tools = []
        agent.model_candidates = ["overloaded-model"]
        agent.model = "overloaded-model"
        agent.client = SimpleNamespace(chat=_FakeChat())

        with patch.object(Config, "MAX_RETRIES", 2), \
            patch.object(interviewee_agent, "sleep_before_retry", return_value=0):
            reply, tool_calls = agent.step_with_metadata("question")

        self.assertEqual(reply, DEFAULT_REPLY_FALLBACK)
        self.assertEqual(tool_calls, [])


if __name__ == "__main__":
    unittest.main()
