import unittest
from unittest.mock import patch

from src.agents.interviewee_agent import extract_interviewee_reply
from src.orchestration.baseline_evaluation_runtime import BaselineEvaluationRuntime


class BaselineEvaluationRuntimeTest(unittest.TestCase):
    def test_records_completed_turn_without_planner_pipeline(self):
        runtime = BaselineEvaluationRuntime("baseline_test_session")
        state = runtime.initialize_session(
            {
                "name": "Test Elder",
                "birth_year": 1942,
                "hometown": "Chengdu",
                "background": "Retired textile worker.",
            }
        )

        self.assertEqual(state.mode, "baseline")
        self.assertTrue(state.metadata["control_group"])
        self.assertFalse(state.metadata["planner_enabled"])

        evaluation = runtime.submit_turn(
            "Could you tell me about your first job?",
            "I remember entering the factory in the early morning and feeling nervous but proud.",
            "continue",
        )
        snapshot = runtime.get_evaluation_state()

        self.assertEqual(evaluation["status"], "completed")
        self.assertIn("turn_id", evaluation)
        self.assertIn("question_quality_score", evaluation)
        self.assertEqual(snapshot["pipeline"], "baseline_no_planner")
        self.assertEqual(snapshot["turn_count"], 1)
        self.assertEqual(snapshot["completed_turn_count"], 1)
        self.assertEqual(snapshot["pending_turn_ids"], [])
        self.assertEqual(snapshot["coverage_metrics"]["overall_coverage"], 0.0)
        self.assertIn("average_turn_quality", snapshot["session_metrics"])


class IntervieweeReplyParsingTest(unittest.TestCase):
    def test_extracts_reply_from_json_response(self):
        raw = '{"thoughts": {"current_emotion": "calm"}, "reply": "I remember that day clearly."}'

        self.assertEqual(extract_interviewee_reply(raw), "I remember that day clearly.")

    def test_extracts_reply_from_markdown_json_fence(self):
        raw = '```json\n{"answer": "The factory was noisy, but everyone helped me."}\n```'

        self.assertEqual(
            extract_interviewee_reply(raw),
            "The factory was noisy, but everyone helped me.",
        )


class BaselineCompareRouteTest(unittest.TestCase):
    def test_baseline_start_uses_restored_runtime_instead_of_stub(self):
        import src.app as app_module

        class FakeBaselineAgent:
            def __init__(self, session_id):
                self.session_id = session_id
                self.basic_info = None

            def initialize_conversation(self, basic_info):
                self.basic_info = basic_info

            def get_next_question(self, user_response=None):
                return "What memory would you like to start with?"

        class FakeRuntime:
            def __init__(self, session_id):
                self.session_id = session_id
                self.elder_info = None

            def initialize_session(self, elder_info):
                self.elder_info = elder_info

            def get_evaluation_state(self):
                return {
                    "session_id": self.session_id,
                    "pipeline": "baseline_no_planner",
                    "control_group": True,
                    "turn_count": 0,
                    "completed_turn_count": 0,
                    "pending_turn_ids": [],
                    "turn_evaluations": {},
                    "turns": [],
                    "session_metrics": {},
                    "coverage_metrics": {"overall_coverage": 0.0},
                }

        app_module._compare_sessions.clear()
        with patch.object(app_module.Config, "get_api_key", return_value="test-key"), \
            patch.object(app_module, "InterviewerAgent", FakeBaselineAgent), \
            patch.object(app_module, "BaselineEvaluationRuntime", FakeRuntime):
            client = app_module.app.test_client()
            response = client.post(
                "/api/baseline/start",
                json={
                    "elder_info": {
                        "name": "Test Elder",
                        "birth_year": 1942,
                        "hometown": "Chengdu",
                        "background": "Retired textile worker.",
                    },
                    "mode": "user",
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["first_question"], "What memory would you like to start with?")
        self.assertEqual(app_module._compare_sessions[data["session_id"]]["type"], "baseline")


if __name__ == "__main__":
    unittest.main()
