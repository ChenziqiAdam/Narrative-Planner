import json
import unittest
from unittest.mock import MagicMock, patch

from src.agents.llm_turn_judge_agent import LLMTurnJudgeAgent


class LLMTurnJudgeAgentTest(unittest.TestCase):
    def test_dimension_prompt_renders_json_schema_without_format_error(self):
        prompt = LLMTurnJudgeAgent._dimension_system_prompt("evidence_responsiveness")

        self.assertIn('"score": 0.0', prompt)
        self.assertIn("previous_turns_for_continuity", prompt)
        self.assertIn("session_progress_for_strategy", prompt)
        self.assertNotIn("baseline", prompt.lower())
        self.assertNotIn("planner", prompt.lower())

    def test_judge_turn_scores_each_dimension_separately_and_weights_total(self):
        responses = {
            "trajectory_guidance": {"reason": "推进清楚", "score": 0.8, "suggestions": []},
            "evidence_responsiveness": {"reason": "承接具体线索", "score": 0.6, "suggestions": []},
            "depth_breadth_control": {"reason": "深挖得当", "score": 1.0, "suggestions": []},
            "information_gain_design": {"reason": "补充材料", "score": 0.4, "suggestions": []},
            "rapport_and_load": {"reason": "负荷适中", "score": 0.5, "suggestions": []},
        }

        def fake_create(**kwargs):
            user_payload = json.loads(kwargs["messages"][1]["content"])
            payload = responses[user_payload["dimension_to_score"]]
            message = MagicMock(content=json.dumps(payload, ensure_ascii=False))
            choice = MagicMock(message=message)
            return MagicMock(choices=[choice])

        with patch("src.agents.llm_turn_judge_agent.OpenAI") as openai_cls:
            openai_cls.return_value.chat.completions.create.side_effect = fake_create
            agent = LLMTurnJudgeAgent(model="judge-test-model")
            result = agent.judge_turn(
                dialogue_context=[
                    {"role": "interviewer", "text": "您刚进厂时是什么样？"},
                    {"role": "interviewee", "text": "我很紧张，也很想证明自己。"},
                ],
                interviewer_question="那天是谁带您进车间的？",
                interviewee_answer="是师傅带我进去的。",
                interview_goal="继续追问具体事件细节",
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(openai_cls.return_value.chat.completions.create.call_count, 5)
        self.assertAlmostEqual(result["question_score"], 0.675)
        self.assertEqual(result["dimensions"]["evidence_responsiveness"], 0.6)
        self.assertNotIn("baseline", result["reason"].lower())
        self.assertNotIn("planner", result["reason"].lower())

        for call in openai_cls.return_value.chat.completions.create.call_args_list:
            serialized = json.dumps(call.kwargs["messages"], ensure_ascii=False).lower()
            self.assertNotIn("baseline", serialized)
            self.assertNotIn("planner", serialized)
            self.assertIn("interview_goal_or_intent", serialized)
            self.assertIn("session_progress_for_strategy", serialized)
            self.assertNotIn("planner_goal_or_intent", serialized)


if __name__ == "__main__":
    unittest.main()
