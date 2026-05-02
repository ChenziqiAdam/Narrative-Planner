import unittest
from datetime import datetime

from src.services.graphrag_monitor import GraphRAGMonitor
from src.state import (
    CanonicalEvent,
    ElderProfile,
    GraphSummary,
    MemoryCapsule,
    SessionState,
    ThemeState,
    ThemeSummary,
    TurnRecord,
)


class FakeVectorStore:
    size = 2

    def search(self, query: str, top_k: int = 5):
        return [("evt_focus", 0.82), ("evt_other", 0.41)][:top_k]


def _graph_summary(coverage: float) -> GraphSummary:
    pending_theme = ThemeSummary(
        theme_id="theme_childhood",
        title="童年记忆",
        description="",
        status="pending",
        completion_ratio=0.0,
        priority=2,
        extracted_event_count=0,
    )
    mentioned_theme = ThemeSummary(
        theme_id="theme_work",
        title="工作经历",
        description="",
        status="mentioned",
        completion_ratio=0.5,
        priority=3,
        extracted_event_count=1,
    )
    return GraphSummary(
        overall_coverage=coverage,
        theme_coverage={"theme_childhood": 0.0, "theme_work": 0.5},
        slot_coverage={"time": 0.5, "location": 0.5},
        people_coverage=0.5,
        current_focus_theme_id="theme_work",
        active_event_ids=["evt_focus"],
        all_themes=[pending_theme, mentioned_theme],
        pending_themes=[pending_theme],
        mentioned_themes=[mentioned_theme],
        exhausted_themes=[],
    )


def _state() -> SessionState:
    now = datetime.now()
    state = SessionState(
        session_id="graphrag_test",
        mode="planner",
        created_at=now,
        updated_at=now,
        elder_profile=ElderProfile(name="测试老人"),
        memory_capsule=MemoryCapsule(
            active_event_ids=["evt_focus"],
            active_people_ids=["person_mother"],
        ),
    )
    state.canonical_events["evt_focus"] = CanonicalEvent(
        event_id="evt_focus",
        title="第一次上学",
        summary="母亲和邻居帮助上学",
        time="1950年",
        people_names=["母亲", "王婆婆"],
        source_turn_ids=["turn_1"],
        completeness_score=0.7,
        theme_id="theme_childhood",
    )
    state.theme_state["theme_childhood"] = ThemeState(
        theme_id="theme_childhood",
        title="童年记忆",
        status="pending",
        priority=2,
        completion_ratio=0.0,
    )
    return state


class GraphRAGMonitorTest(unittest.TestCase):
    def test_turn_metrics_capture_retrieval_graph_grounding_and_decision(self):
        monitor = GraphRAGMonitor()
        state = _state()
        turn = TurnRecord(
            turn_id="turn_1",
            turn_index=1,
            timestamp=datetime.now(),
            interviewer_question="后来上学顺利吗？",
            interviewee_answer="那时候母亲和王婆婆帮了我很多，我一直记得。",
        )
        hints = {
            "decision_scores": {
                "action": {"continue": 1.4, "next_phase": 0.9, "end": 0.1},
                "focus": {"stay_current_event": 1.2, "switch_new_event": 0.6},
            },
            "preferred_action": "continue",
            "preferred_focus": "stay_current_event",
            "slot_rankings": [{"slot": "location", "score": 1.1}],
            "theme_rankings": [{"theme_id": "theme_childhood", "score": 1.3}],
            "recommended_theme_id": "theme_childhood",
        }

        metrics = monitor.build_turn_metrics(
            state=state,
            turn_record=turn,
            pre_graph_summary=_graph_summary(0.2),
            post_graph_summary=_graph_summary(0.35),
            generation_hints=hints,
            focus_event_payload={
                "event_id": "evt_focus",
                "missing_slots": ["location", "reflection"],
            },
            event_vector_store=FakeVectorStore(),
            retrieval_query=turn.interviewee_answer,
        ).to_dict()

        self.assertTrue(metrics["enabled_signals"]["semantic_event_retrieval"])
        self.assertEqual(metrics["retrieval"]["retrieved_count"], 2)
        self.assertEqual(metrics["retrieval"]["focus_event_retrieved"], 1.0)
        self.assertEqual(metrics["graph_context"]["focus_missing_slot_count"], 2)
        self.assertEqual(metrics["grounding"]["source_linkage_rate"], 1.0)
        self.assertEqual(metrics["decision_influence"]["top_slot"], "location")
        self.assertAlmostEqual(metrics["decision_influence"]["action_score_margin"], 0.5)

    def test_session_metrics_aggregate_turn_traces(self):
        monitor = GraphRAGMonitor()
        state = _state()
        state.transcript = [
            TurnRecord(
                turn_id="turn_1",
                turn_index=1,
                timestamp=datetime.now(),
                interviewer_question="Q1",
                interviewee_answer="A1",
                debug_trace={
                    "graphrag": {
                        "retrieval": {
                            "retrieved_count": 2,
                            "top_score": 0.8,
                            "focus_event_retrieved": 1.0,
                        },
                        "graph_context": {
                            "coverage_delta": 0.1,
                            "active_event_count": 1,
                        },
                        "decision_influence": {
                            "preferred_action": "continue",
                            "preferred_focus": "stay_current_event",
                            "action_score_margin": 0.3,
                        },
                        "quality_flags": {},
                    }
                },
            ),
            TurnRecord(
                turn_id="turn_2",
                turn_index=2,
                timestamp=datetime.now(),
                interviewer_question="Q2",
                interviewee_answer="A2",
                debug_trace={
                    "graphrag": {
                        "retrieval": {
                            "retrieved_count": 0,
                            "top_score": 0.0,
                            "focus_event_retrieved": 0.0,
                        },
                        "graph_context": {
                            "coverage_delta": 0.0,
                            "active_event_count": 0,
                        },
                        "decision_influence": {
                            "preferred_action": "next_phase",
                            "preferred_focus": "switch_new_event",
                            "action_score_margin": 0.1,
                        },
                        "quality_flags": {"empty_graph_context": True},
                    }
                },
            ),
        ]

        metrics = monitor.build_session_metrics(state)

        self.assertTrue(metrics["uses_graphrag_style_path"])
        self.assertEqual(metrics["turn_count"], 2)
        self.assertEqual(metrics["semantic_retrieval_turn_rate"], 0.5)
        self.assertEqual(metrics["decision_action_counts"]["continue"], 1)
        self.assertEqual(metrics["decision_action_counts"]["next_phase"], 1)
        self.assertEqual(metrics["stale_or_empty_context_turns"], 1)


if __name__ == "__main__":
    unittest.main()
