import unittest

from src.orchestration.session_orchestrator import SessionOrchestrator


def _orchestrator() -> SessionOrchestrator:
    return SessionOrchestrator.__new__(SessionOrchestrator)


class PlannerPlanTraceTest(unittest.TestCase):
    def test_build_planning_trace_projects_decision_summary(self):
        orchestrator = _orchestrator()
        trace = orchestrator._build_planning_trace(
            {
                "action": "continue",
                "planner_plan": {
                    "stage": "life_overview",
                    "selected_action": "continue_life_overview",
                    "focus": {"type": "life_period", "label": "早年"},
                    "event_completeness": {
                        "score": 0.25,
                        "missing_dimensions": ["people", "feeling"],
                    },
                    "emotion_signal": {
                        "energy": 0.6,
                        "valence": "neutral",
                    },
                    "candidate_actions": [
                        {"action": "continue_life_overview", "score": 0.9}
                    ],
                    "selected_slot_or_angle": "life_timeline",
                    "question_intent": "继续梳理人生脉络。",
                },
            }
        )

        self.assertEqual(trace["next_action"], "continue")
        self.assertEqual(trace["selected_action"], "continue_life_overview")
        self.assertEqual(trace["stage"], "life_overview")
        self.assertEqual(trace["event_completeness_score"], 0.25)
        self.assertEqual(trace["missing_dimensions"], ["people", "feeling"])


if __name__ == "__main__":
    unittest.main()
