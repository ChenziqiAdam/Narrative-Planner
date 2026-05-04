import unittest
import json
from datetime import datetime

from src.agents.interviewer_agent import InterviewerAgent
from src.services.graph_rag_decision_context import GraphRAGDecisionContext
from src.state import ElderProfile, TurnRecord


def _agent() -> InterviewerAgent:
    return InterviewerAgent.__new__(InterviewerAgent)


def _turn(index: int) -> TurnRecord:
    return TurnRecord(
        turn_id=f"turn_{index}",
        turn_index=index,
        timestamp=datetime.now(),
        interviewer_question="您愿意先讲讲早年的一段记忆吗？",
        interviewee_answer="我小时候在老家生活，家里人很多，日子比较紧。",
    )


class InterviewerLifeOverviewTest(unittest.TestCase):
    def test_opening_does_not_jump_to_work_when_background_mentions_factory(self):
        agent = _agent()
        profile = ElderProfile(
            name="王奶奶",
            birth_year=1942,
            hometown="四川成都",
            background_summary="年轻时在纺织厂工作，后来养育三个子女。",
        )

        question = agent._build_opening_question(profile)

        self.assertIn("最早", question)
        self.assertNotIn("工作", question)
        self.assertNotIn("工厂", question)
        self.assertNotIn("纺织", question)

    def test_early_prompt_prioritizes_life_overview_scaffolding(self):
        agent = _agent()
        profile = ElderProfile(
            birth_year=1942,
            hometown="四川成都",
            background_summary="年轻时在纺织厂工作。",
        )

        prompt = agent._build_user_prompt(
            profile,
            [_turn(1), _turn(2)],
            GraphRAGDecisionContext(),
        )

        self.assertIn("人生脉络梳理阶段", prompt)
        self.assertIn("人生阶段、大事节点、关键人物、自我评价和价值观", prompt)
        self.assertIn("不要因为背景里出现某个职业", prompt)

    def test_overview_guidance_expires_after_initial_mapping_turns(self):
        agent = _agent()
        profile = ElderProfile(birth_year=1942, hometown="四川成都")

        prompt = agent._build_user_prompt(
            profile,
            [_turn(index) for index in range(1, 9)],
            GraphRAGDecisionContext(),
        )

        self.assertNotIn("人生脉络梳理阶段", prompt)

    def test_prompt_requires_structured_planner_plan(self):
        agent = _agent()
        profile = ElderProfile(birth_year=1942, hometown="四川成都")

        prompt = agent._build_user_prompt(
            profile,
            [_turn(1)],
            GraphRAGDecisionContext(),
        )

        self.assertIn("planner_plan", prompt)
        self.assertIn("selected_action", prompt)
        self.assertIn("event_completeness", prompt)
        self.assertIn("candidate_actions", prompt)

    def test_parse_response_preserves_planner_plan(self):
        agent = _agent()
        raw = json.dumps(
            {
                "planner_plan": {
                    "stage": "life_overview",
                    "selected_action": "continue_life_overview",
                    "focus": {"type": "life_period", "label": "童年"},
                    "event_completeness": {
                        "score": 0.2,
                        "missing_dimensions": ["people", "feeling"],
                        "reason_summary": "仍在建立早年脉络。",
                    },
                    "emotion_signal": {
                        "energy": 0.6,
                        "valence": "neutral",
                        "support_needed": False,
                    },
                    "candidate_actions": [
                        {
                            "action": "continue_life_overview",
                            "score": 0.8,
                            "reason_summary": "先铺开人生脉络。",
                        }
                    ],
                    "selected_slot_or_angle": "life_timeline",
                    "tone": "respectful_warm",
                    "question_intent": "继续梳理早年生活。",
                },
                "action": "continue",
                "question": "您小时候家里和周围的生活，大概是什么样子的？",
            },
            ensure_ascii=False,
        )

        parsed = agent._parse_response(raw)

        self.assertEqual(parsed["action"], "continue")
        self.assertIn("planner_plan", parsed)
        self.assertEqual(parsed["planner_plan"]["stage"], "life_overview")
        self.assertEqual(
            parsed["planner_plan"]["event_completeness"]["missing_dimensions"],
            ["people", "feeling"],
        )

    def test_opening_response_includes_planner_plan_without_llm_call(self):
        agent = _agent()
        profile = ElderProfile(
            name="王奶奶",
            birth_year=1942,
            hometown="四川成都",
        )

        response = agent._opening_response(profile)

        self.assertEqual(response["action"], "continue")
        self.assertIn("planner_plan", response)
        self.assertEqual(response["planner_plan"]["stage"], "life_overview")
        self.assertEqual(
            response["planner_plan"]["selected_action"],
            "continue_life_overview",
        )


if __name__ == "__main__":
    unittest.main()
