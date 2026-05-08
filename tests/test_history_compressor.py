import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.services.history_compressor import HistoryCompressor


def _make_client(reply_text: str):
    message = SimpleNamespace(content=reply_text)
    choice = SimpleNamespace(message=message)
    response = SimpleNamespace(choices=[choice])
    completions = MagicMock()
    completions.create.return_value = response
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


def _make_failing_client():
    completions = MagicMock()
    completions.create.side_effect = Exception("API error")
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


class HistoryCompressorTest(unittest.TestCase):
    def test_compress_qa_pairs_returns_summary(self):
        client = _make_client("受访者谈论了童年和学校生活。")
        compressor = HistoryCompressor(client, model_candidates=["test-model"])
        turns = [
            {"question": "你小时候住在哪里？", "answer": "我住在成都。"},
            {"question": "你上学了吗？", "answer": "上了，小学在镇上。"},
        ]
        result = compressor.compress_qa_pairs(turns)
        self.assertEqual(result, "受访者谈论了童年和学校生活。")
        completions = client.chat.completions
        completions.create.assert_called_once()
        call_kwargs = completions.create.call_args[1]
        self.assertEqual(call_kwargs["model"], "test-model")

    def test_compress_qa_pairs_with_existing_summary(self):
        client = _make_client("整合摘要：童年+学校。")
        compressor = HistoryCompressor(client, model_candidates=["m"])
        turns = [{"question": "后来呢？", "answer": "后来搬了家。"}]
        result = compressor.compress_qa_pairs(turns, existing_summary="之前的摘要")
        self.assertEqual(result, "整合摘要：童年+学校。")
        call_messages = client.chat.completions.create.call_args[1]["messages"]
        user_msg = call_messages[1]["content"]
        self.assertIn("之前的摘要", user_msg)

    def test_compress_qa_pairs_failure_returns_empty(self):
        client = _make_failing_client()
        compressor = HistoryCompressor(client, model_candidates=["m"])
        turns = [{"question": "Q", "answer": "A"}]
        with patch("src.services.history_compressor.is_transient_llm_error", return_value=False):
            result = compressor.compress_qa_pairs(turns)
        self.assertEqual(result, "")

    def test_compress_messages_returns_summary(self):
        client = _make_client("对话摘要内容。")
        compressor = HistoryCompressor(client, model_candidates=["m"])
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，请问"},
        ]
        result = compressor.compress_messages(messages)
        self.assertEqual(result, "对话摘要内容。")

    def test_compress_messages_failure_returns_empty(self):
        client = _make_failing_client()
        compressor = HistoryCompressor(client, model_candidates=["m"])
        with patch("src.services.history_compressor.is_transient_llm_error", return_value=False):
            result = compressor.compress_messages([{"role": "user", "content": "hi"}])
        self.assertEqual(result, "")

    def test_empty_reply_treated_as_failure(self):
        client = _make_client("")
        compressor = HistoryCompressor(client, model_candidates=["m"])
        turns = [{"question": "Q", "answer": "A"}]
        with patch("src.services.history_compressor.is_transient_llm_error", return_value=False):
            result = compressor.compress_qa_pairs(turns)
        self.assertEqual(result, "")


class IntervieweeHistoryCompressionTest(unittest.TestCase):
    """Test IntervieweeAgent's record_turn + _load_step_prompt compression flow."""

    def _make_agent(self):
        from src.agents.interviewee_agent import IntervieweeAgent
        agent = IntervieweeAgent.__new__(IntervieweeAgent)
        agent.history = ""
        agent._history_summary = ""
        agent._history_turns = []
        agent.sys_prompt = "system"
        agent.tools = []
        agent.tool_callables = {}
        agent.model_candidates = ["m"]
        agent.model = "m"
        agent.memory_system = MagicMock()
        client = _make_client("压缩后的摘要。")
        agent.client = client
        agent._compressor = HistoryCompressor(client, model_candidates=["m"])
        return agent

    @patch("src.agents.interviewee_agent.Config.HISTORY_COMPRESS_MAX_RECENT_TURNS", 3)
    @patch("src.agents.interviewee_agent.Config.HISTORY_COMPRESS_MAX_CHAR_THRESHOLD", 100)
    def test_record_turn_triggers_compression(self):
        agent = self._make_agent()
        for i in range(5):
            agent.record_turn(f"Q{i}", f"A{i}" * 20)
        self.assertTrue(len(agent._history_turns) <= 3)
        self.assertEqual(agent._history_summary, "压缩后的摘要。")

    @patch("src.agents.interviewee_agent.Config.HISTORY_COMPRESS_MAX_RECENT_TURNS", 3)
    def test_load_step_prompt_uses_compressed_state(self):
        agent = self._make_agent()
        agent._history_summary = "已讨论童年。"
        agent._history_turns = [
            {"question": "最近Q", "answer": "最近A"},
        ]
        prompt = agent._load_step_prompt("ignored history", "新问题")
        self.assertIn("访谈历史摘要：已讨论童年。", prompt)
        self.assertIn("近期对话", prompt)
        self.assertIn("最近Q", prompt)
        self.assertNotIn("ignored history", prompt)

    @patch("src.agents.interviewee_agent.Config.HISTORY_COMPRESS_MAX_RECENT_TURNS", 3)
    def test_load_step_prompt_no_summary(self):
        agent = self._make_agent()
        agent._history_turns = [
            {"question": "Q1", "answer": "A1"},
        ]
        prompt = agent._load_step_prompt("", "问题")
        self.assertNotIn("访谈历史摘要", prompt)
        self.assertIn("Q1", prompt)
        self.assertIn("问题", prompt)

    @patch("src.agents.interviewee_agent.Config.HISTORY_COMPRESS_MAX_RECENT_TURNS", 3)
    def test_load_step_prompt_empty(self):
        agent = self._make_agent()
        prompt = agent._load_step_prompt("", "第一个问题")
        self.assertEqual(prompt, "访谈问题：第一个问题")


class BaselineHistoryCompressionTest(unittest.TestCase):
    """Test BaselineAgent's get_next_question compression flow."""

    def _make_agent(self):
        from src.agents.baseline_agent import BaselineAgent
        agent = BaselineAgent.__new__(BaselineAgent)
        agent.session_id = "test"
        agent.model_candidates = ["m"]
        agent.model = "m"
        agent.system_prompt = "system prompt"
        agent._summary_message = None

        message = SimpleNamespace(content="下一个问题")
        choice = SimpleNamespace(message=message)
        response = SimpleNamespace(choices=[choice])
        completions = MagicMock()
        completions.create.return_value = response
        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        agent._compressor = HistoryCompressor(agent.client, model_candidates=["m"])
        return agent

    @patch("src.agents.baseline_agent.Config.HISTORY_COMPRESS_MAX_RECENT_TURNS", 2)
    @patch("src.agents.baseline_agent.Config.HISTORY_COMPRESS_MAX_CHAR_THRESHOLD", 50)
    def test_compression_triggers_on_long_history(self):
        agent = self._make_agent()
        agent.conversation_history = [{"role": "system", "content": "sys"}]
        for i in range(5):
            agent.conversation_history.append({"role": "user", "content": f"response {i} " * 30})
            agent.conversation_history.append({"role": "assistant", "content": f"question {i}"})

        agent.get_next_question("latest response " * 30)
        self.assertIsNotNone(agent._summary_message)
        self.assertIn("对话摘要", agent._summary_message["content"])

    @patch("src.agents.baseline_agent.Config.HISTORY_COMPRESS_MAX_RECENT_TURNS", 2)
    def test_effective_history_includes_summary(self):
        agent = self._make_agent()
        agent.conversation_history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "r1"},
            {"role": "assistant", "content": "q1"},
        ]
        agent._summary_message = {"role": "user", "content": "[之前的对话摘要]\n摘要内容"}
        effective = agent._effective_history()
        self.assertEqual(len(effective), 4)
        self.assertEqual(effective[0]["role"], "system")
        self.assertEqual(effective[1]["content"], "[之前的对话摘要]\n摘要内容")

    @patch("src.agents.baseline_agent.Config.HISTORY_COMPRESS_MAX_RECENT_TURNS", 2)
    def test_no_compression_when_short(self):
        agent = self._make_agent()
        agent.conversation_history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "r1"},
            {"role": "assistant", "content": "q1"},
        ]
        agent.get_next_question("r2")
        self.assertIsNone(agent._summary_message)


if __name__ == "__main__":
    unittest.main()
