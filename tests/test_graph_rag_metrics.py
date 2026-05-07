import unittest

from src.services.graph_rag_metrics import (
    build_extraction_metrics,
    build_graph_rag_metrics,
    build_retrieval_metrics,
    build_write_metrics,
)
from src.services.retrieval_models import RankedEntity, RetrievalResult
from src.state.narrative_models import ExtractedEntity, ExtractedRelationship, GraphExtraction


class FakeWriteResult:
    entity_ids = ["event_1", "person_1"]
    new_entity_count = 1
    updated_entity_count = 1
    relationship_count = 2
    deduplicated_count = 1


class FakeDecisionContext:
    overall_coverage = 0.42
    coverage_by_theme = {"THEME_A": 0.1, "THEME_B": 0.8}
    undercovered_themes = ["THEME_A"]
    exhausted_themes = []
    current_focus_theme_id = "THEME_A"
    focus_entity_id = "event_1"
    focus_rich_text = "一次重要经历"
    connected_people = ["母亲"]
    connected_locations = ["老家"]
    explorable_angles = ["缺少情感"]
    low_info_streak = 2
    graph_rag_context = "## 叙事记忆脉络\n- [事件] 一次重要经历"
    emotional_state = None


class GraphRAGMetricsTest(unittest.TestCase):
    def test_extraction_metrics_count_entity_types(self):
        extraction = GraphExtraction(
            entities=[
                ExtractedEntity("Event", "搬家", "搬到县城"),
                ExtractedEntity("Person", "母亲", "母亲帮忙"),
                ExtractedEntity("Emotion", "不舍", "离开老家很不舍"),
            ],
            relationships=[
                ExtractedRelationship("母亲", "搬家", "PARTICIPATES_IN"),
            ],
            narrative_summary="讲述搬家经历",
            open_loops=["为什么搬家"],
            confidence=0.83,
        )

        metrics = build_extraction_metrics(extraction, latency_ms=12.34)

        self.assertEqual(metrics["entity_count"], 3)
        self.assertEqual(metrics["event_count"], 1)
        self.assertEqual(metrics["person_count"], 1)
        self.assertEqual(metrics["emotion_count"], 1)
        self.assertEqual(metrics["relationship_count"], 1)
        self.assertEqual(metrics["open_loops_count"], 1)
        self.assertEqual(metrics["confidence"], 0.83)
        self.assertFalse(metrics["empty_extraction"])

    def test_write_metrics_are_json_ready(self):
        metrics = build_write_metrics(FakeWriteResult(), latency_ms=8.88)

        self.assertEqual(metrics["entity_ids_count"], 2)
        self.assertEqual(metrics["new_entity_count"], 1)
        self.assertEqual(metrics["updated_entity_count"], 1)
        self.assertEqual(metrics["deduplicated_count"], 1)
        self.assertEqual(metrics["relationship_count"], 2)
        self.assertFalse(metrics["write_empty"])

    def test_retrieval_metrics_include_channel_trace(self):
        retrieval = RetrievalResult(
            entities=[
                RankedEntity(
                    entity_id="event_1",
                    entity_type="Event",
                    name="搬家",
                    description="搬到县城",
                    combined_score=0.12,
                    sources=["vector", "graph"],
                )
            ],
            prompt_text="## 叙事记忆脉络\n- [事件] 搬到县城",
            token_count=16,
            latency_ms=5.5,
            trace={
                "channel_counts": {"vector": 1, "graph": 1, "fulltext": 0, "ranked": 1},
                "channel_errors": {},
                "top_entities": [{"entity_id": "event_1", "sources": ["vector", "graph"]}],
            },
        )

        metrics = build_retrieval_metrics(retrieval)

        self.assertEqual(metrics["ranked_entity_count"], 1)
        self.assertEqual(metrics["token_count"], 16)
        self.assertFalse(metrics["context_empty"])
        self.assertEqual(metrics["channel_counts"]["ranked"], 1)
        self.assertEqual(metrics["top_entities"][0]["entity_id"], "event_1")

    def test_combined_graph_rag_metrics_have_expected_sections(self):
        extraction = GraphExtraction(
            entities=[ExtractedEntity("Event", "搬家", "搬到县城")],
            confidence=0.7,
        )
        retrieval = RetrievalResult(prompt_text="", trace={"channel_counts": {}})

        metrics = build_graph_rag_metrics(
            extraction=extraction,
            write_result=FakeWriteResult(),
            planner_retrieval=retrieval,
            decision_ctx=FakeDecisionContext(),
            extraction_ms=10,
            write_ms=20,
        )

        self.assertIn("extraction", metrics)
        self.assertIn("write", metrics)
        self.assertIn("planner_retrieval", metrics)
        self.assertIn("decision_context", metrics)
        self.assertEqual(metrics["decision_context"]["undercovered_theme_count"], 1)


if __name__ == "__main__":
    unittest.main()
