import unittest

from src.services.hybrid_retriever import HybridRetriever


class FakeDriver:
    def __init__(self):
        self.nodes = {
            "event_1": {
                "id": "event_1",
                "type": "Event",
                "name": "搬到县城",
                "description": "1978年全家从村里搬到县城，母亲帮着收拾行李。",
            },
            "person_1": {
                "id": "person_1",
                "type": "Person",
                "name": "母亲",
                "description": "搬家时照顾全家的人。",
            },
        }

    def get_node(self, node_id):
        return self.nodes.get(node_id)

    def query_by_hop(self, node_id, hop_count=2):
        return {
            "neighbors_by_hop": {
                "1": [
                    {
                        "id": "person_1",
                        "type": "Person",
                        "name": "母亲",
                        "description": "搬家时照顾全家的人。",
                    }
                ]
            },
            "relationships": [
                {
                    "source_id": "person_1",
                    "target_id": "event_1",
                    "relation_type": "PARTICIPATES_IN",
                }
            ],
        }

    def fulltext_search(self, query, top_k=5, session_id=""):
        return []


class FakeNeo4j:
    def __init__(self):
        self.driver = FakeDriver()


class FakeVectorStore:
    def search_by_text(self, query, top_k=5):
        return [("event_1", "Event", 0.92)]


class HybridRetrieverMetricsTest(unittest.TestCase):
    def test_retrieve_hydrates_vector_hits_and_emits_trace(self):
        retriever = HybridRetriever(FakeNeo4j(), FakeVectorStore())

        result = retriever.retrieve("搬家时母亲做了什么", "session_1", max_tokens=200)

        self.assertEqual(result.trace["channel_counts"]["vector"], 1)
        self.assertEqual(result.trace["channel_counts"]["graph"], 1)
        self.assertEqual(result.trace["channel_counts"]["ranked"], 2)
        self.assertFalse(result.trace["prompt_empty"])
        self.assertIn("1978年全家从村里搬到县城", result.prompt_text)
        self.assertIn("搬家时照顾全家的人", result.prompt_text)
        self.assertEqual(result.trace["top_entities"][0]["entity_id"], "event_1")


if __name__ == "__main__":
    unittest.main()
