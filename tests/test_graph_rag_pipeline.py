import unittest

from src.services.graph_writer import GraphWriter
from src.state.narrative_models import ExtractedEntity, GraphExtraction
from src.storage.neo4j.manager import Neo4jGraphManager


class FakeDriver:
    def __init__(self):
        self.nodes = {}
        self.edges = []

    def insert_node(self, node_dict):
        self.nodes[node_dict["id"]] = dict(node_dict)
        return True

    def insert_edge(self, source_id, target_id, relation_type, properties=None):
        self.edges.append((source_id, target_id, relation_type, properties or {}))
        return True

    def node_exists(self, node_id):
        return node_id in self.nodes


class FakeNeo4jManager:
    def __init__(self):
        self.driver = FakeDriver()
        self.status_updates = []
        self.depth_updates = []
        self.topics = {
            "THEME_01_LIFE_CHAPTERS": {
                "id": "THEME_01_LIFE_CHAPTERS",
                "name": "人生篇章概览",
                "description": "人生阶段与时间线",
                "domain": "life_chapters",
            },
            "THEME_14_HEALTH": {
                "id": "THEME_14_HEALTH",
                "name": "健康",
                "description": "重大健康问题、住院、医生、手术",
                "domain": "challenges",
            },
        }
        for topic_id, topic in self.topics.items():
            self.driver.insert_node({**topic, "type": "Topic"})

    def get_all_topics(self):
        return self.topics

    def get_topic(self, theme_id):
        return self.topics.get(theme_id)

    def add_event_to_topic(self, theme_id, event_id):
        return self.driver.insert_edge(theme_id, event_id, "INCLUDES")

    def update_topic_status(self, theme_id, status):
        self.status_updates.append((theme_id, status))
        return True

    def increment_topic_depth(self, theme_id):
        self.depth_updates.append(theme_id)
        return True


class FakeVectorStore:
    def __init__(self):
        self.items = {}

    def add(self, entity_id, entity_type, text, embedding=None):
        self.items[entity_id] = (entity_type, text, embedding)

    def search(self, query_embedding, top_k=5, entity_type=None):
        return []

    def get_embedding(self, entity_id):
        item = self.items.get(entity_id)
        return item[2] if item else None


class FakeEmbeddingService:
    def encode_single(self, text):
        return self._vector(text)

    def encode(self, texts):
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text):
        if any(word in text for word in ("健康", "医院", "手术", "医生", "住院")):
            return [1.0, 0.0]
        return [0.0, 1.0]


class TestGraphRAGPipeline(unittest.TestCase):
    def test_sync_themes_to_neo4j_loads_topic_nodes(self):
        manager = Neo4jGraphManager(FakeDriver())

        count = manager.sync_themes_to_neo4j()

        self.assertGreaterEqual(count, 20)
        self.assertIn("THEME_01_LIFE_CHAPTERS", manager.driver.nodes)
        self.assertEqual(manager.driver.nodes["THEME_01_LIFE_CHAPTERS"]["type"], "Topic")

    def test_graph_writer_links_event_to_semantic_theme(self):
        manager = FakeNeo4jManager()
        writer = GraphWriter(
            manager,
            FakeVectorStore(),
            embedding_service=FakeEmbeddingService(),
        )
        extraction = GraphExtraction(
            entities=[
                ExtractedEntity(
                    entity_type="Event",
                    name="住院手术",
                    description="那年我在医院做了一次手术，医生说恢复得不错。",
                )
            ],
            confidence=0.8,
        )

        result = writer.write_extraction(extraction, "session_1", "elder_1")

        self.assertEqual(result.new_entity_count, 1)
        event_id = result.entity_ids[0]
        self.assertEqual(manager.driver.nodes[event_id]["theme_id"], "THEME_14_HEALTH")
        self.assertIn(("THEME_14_HEALTH", event_id, "INCLUDES", {}), manager.driver.edges)
        self.assertIn(("THEME_14_HEALTH", "mentioned"), manager.status_updates)
        self.assertIn("THEME_14_HEALTH", manager.depth_updates)

    def test_graph_writer_respects_explicit_theme_id(self):
        manager = FakeNeo4jManager()
        writer = GraphWriter(
            manager,
            FakeVectorStore(),
            embedding_service=FakeEmbeddingService(),
        )
        extraction = GraphExtraction(
            entities=[
                ExtractedEntity(
                    entity_type="Event",
                    name="人生阶段回顾",
                    description="我先讲讲自己从童年到退休分成几个阶段。",
                    properties={"theme_id": "THEME_01_LIFE_CHAPTERS"},
                )
            ],
            confidence=0.8,
        )

        result = writer.write_extraction(extraction, "session_1", "elder_1")

        event_id = result.entity_ids[0]
        self.assertEqual(manager.driver.nodes[event_id]["theme_id"], "THEME_01_LIFE_CHAPTERS")
        self.assertIn(("THEME_01_LIFE_CHAPTERS", event_id, "INCLUDES", {}), manager.driver.edges)


if __name__ == "__main__":
    unittest.main()
