import json
import tempfile
import unittest

from src.services.interview_logger import (
    DialogueLog,
    EvaluationLog,
    InterviewLogger,
    TurnLogData,
)


class InterviewLoggerTest(unittest.TestCase):
    def test_async_evaluation_update_keeps_turns_log_one_line_per_turn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = InterviewLogger(
                session_id="session-1",
                session_type="planner",
                elder_info={"name": "测试老人"},
                log_dir=temp_dir,
            )
            turn = TurnLogData(
                turn_id="turn-1",
                turn_index=1,
                timestamp="2026-05-08T17:00:00",
                dialogue=DialogueLog(
                    interviewer_question="您第一次工作是什么时候？",
                    interviewee_answer="那是很久以前。",
                ),
                evaluation=EvaluationLog(llm_judge_status="pending"),
                debug_trace={"large": {"nested": "details"}},
            )

            logger.log_turn(turn)
            logger.update_turn_evaluation(
                "turn-1",
                EvaluationLog(llm_judge_status="completed", llm_judge_score=0.72),
            )

            with open(logger.get_turns_log_path(), encoding="utf-8") as handle:
                lines = [json.loads(line) for line in handle if line.strip()]

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["turn_id"], "turn-1")
        self.assertEqual(lines[0]["evaluation"]["llm_judge_status"], "completed")
        self.assertEqual(lines[0]["evaluation"]["llm_judge_score"], 0.72)
        self.assertIn("debug_summary", lines[0])
        self.assertNotIn("debug_trace", lines[0])


if __name__ == "__main__":
    unittest.main()
