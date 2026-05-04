import unittest
from datetime import datetime

from src.services.graph_rag_decision_context import GraphRAGDecisionContext
from src.state import ElderProfile, TurnRecord
from src.tools.planner_tools import (
    PlannerToolSystem,
    get_planner_tool_callables,
    get_planner_tool_schemas,
)


def _turn() -> TurnRecord:
    return TurnRecord(
        turn_id="turn_1",
        turn_index=1,
        timestamp=datetime.now(),
        interviewer_question="您愿意讲讲早年的生活吗？",
        interviewee_answer="我小时候在成都家里，父亲和母亲都在，后来因为家里困难，我心里也挺辛苦。",
    )


class PlannerToolsTest(unittest.TestCase):
    def test_tool_schemas_and_callables_share_names(self):
        ctx = GraphRAGDecisionContext()
        system = PlannerToolSystem(ElderProfile(), [], ctx)
        schema_names = {
            item["function"]["name"]
            for item in get_planner_tool_schemas()
        }
        callable_names = set(get_planner_tool_callables(system))

        self.assertIn("assess_event_completeness", schema_names)
        self.assertEqual(schema_names, callable_names)

    def test_assess_event_completeness_returns_evidence_not_action(self):
        ctx = GraphRAGDecisionContext(
            focus_rich_text="小时候在成都家里生活，父亲和母亲都在。",
            connected_people=["父亲", "母亲"],
            connected_locations=["成都"],
            emotional_thread="辛苦",
        )
        system = PlannerToolSystem(ElderProfile(), [_turn()], ctx)

        result = system.assess_event_completeness()

        self.assertGreater(result["score"], 0.3)
        self.assertIn("people", result["filled_dimensions"])
        self.assertIn("location", result["filled_dimensions"])
        self.assertIn("recommended_probe_dimensions", result)
        self.assertNotIn("selected_action", result)

    def test_theme_coverage_tool_returns_undercovered_themes(self):
        ctx = GraphRAGDecisionContext(
            overall_coverage=0.2,
            coverage_by_theme={"childhood": 0.1, "work": 0.6},
            current_focus_theme_id="childhood",
            undercovered_themes=["childhood"],
        )
        system = PlannerToolSystem(ElderProfile(), [], ctx)

        result = system.get_theme_coverage()

        self.assertEqual(result["overall_coverage"], 0.2)
        self.assertEqual(result["current_focus_theme_id"], "childhood")
        self.assertEqual(result["undercovered_themes"], ["childhood"])

    def test_graph_tool_schemas_are_only_exposed_when_graph_manager_exists(self):
        ctx = GraphRAGDecisionContext()
        without_graph = PlannerToolSystem(ElderProfile(), [], ctx)
        with_graph = PlannerToolSystem(ElderProfile(), [], ctx, neo4j_manager=_FakeNeo4jManager())

        base_names = {
            item["function"]["name"]
            for item in get_planner_tool_schemas(include_graph_tools=without_graph.has_graph_tools)
        }
        graph_names = {
            item["function"]["name"]
            for item in get_planner_tool_schemas(include_graph_tools=with_graph.has_graph_tools)
        }

        self.assertNotIn("get_entity_context", base_names)
        self.assertIn("get_entity_context", graph_names)
        self.assertIn("get_theme_detail", graph_names)

    def test_graph_tools_return_compact_graph_evidence(self):
        ctx = GraphRAGDecisionContext(
            current_focus_theme_id="childhood",
            focus_entity_id="event_1",
        )
        system = PlannerToolSystem(
            ElderProfile(),
            [],
            ctx,
            neo4j_manager=_FakeNeo4jManager(),
        )
        callables = get_planner_tool_callables(system)

        entity_context = callables["get_entity_context"]()
        theme_detail = callables["get_theme_detail"]()
        graph_summary = callables["get_graph_summary"]()

        self.assertEqual(entity_context["center"]["id"], "event_1")
        self.assertIn("1", entity_context["neighbors_by_hop"])
        self.assertTrue(theme_detail["found"])
        self.assertEqual(theme_detail["theme_id"], "childhood")
        self.assertEqual(graph_summary["node_count"], 2)


class _FakeDriver:
    def get_graph_statistics(self):
        return {"node_count": 2, "relationship_count": 1}

    def query_by_text_similarity(self, text, entity_type=None, max_results=10):
        return [
            {
                "id": "person_1",
                "type": entity_type or "Person",
                "name": "母亲",
                "description": "反复出现的家庭人物",
                "score": 0.9,
            }
        ][:max_results]

    def execute_query(self, query, params=None):
        return [{"id": "event_1", "type": "Event", "name": "童年记忆"}]


class _FakeNeo4jManager:
    def __init__(self):
        self.driver = _FakeDriver()

    def get_entity_by_hop(self, node_id, hop_count=2):
        return {
            "center": {
                "id": node_id,
                "type": "Event",
                "name": "童年记忆",
                "description": "小时候在成都家里的生活",
            },
            "neighbors_by_hop": {
                "1": [
                    {
                        "id": "person_1",
                        "type": "Person",
                        "name": "母亲",
                        "description": "关键人物",
                    }
                ]
            },
            "relationships": [{"source": node_id, "target": "person_1", "type": "PARTICIPATES_IN"}],
        }

    def detect_patterns(self):
        return [{"pattern_type": "recurring_person", "items": ["母亲", "父亲"]}]

    def get_topic(self, theme_id):
        return {
            "id": theme_id,
            "title": "童年与家庭",
            "status": "mentioned",
            "priority": 1,
            "domain": "life_period",
            "description": "早年生活、家庭关系和日常环境",
            "exploration_depth": 1,
        }


if __name__ == "__main__":
    unittest.main()
