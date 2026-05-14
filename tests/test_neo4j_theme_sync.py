import unittest

from src.core.theme_loader import ThemeLoader
from src.storage.neo4j.manager import Neo4jGraphManager
from src.storage.neo4j.models import TopicNode


class FakeTopicDriver:
    def __init__(self, topic_count=0):
        self.topic_count = topic_count
        self.inserted_nodes = []
        self.inserted_edges = []

    def execute_query(self, query, params=None):
        if "MATCH (t:Topic) RETURN count(t) AS cnt" in query:
            return [{"cnt": self.topic_count}]
        return []

    def insert_node(self, node_dict):
        self.inserted_nodes.append(node_dict)
        return True

    def insert_edge(self, source_id, target_id, relation_type, properties=None):
        self.inserted_edges.append((source_id, target_id, relation_type, properties or {}))
        return True


class Neo4jThemeSyncTest(unittest.TestCase):
    def test_upsert_topic_sanitizes_slots_filled_dict(self):
        driver = FakeTopicDriver()
        manager = Neo4jGraphManager(driver=driver)

        manager.upsert_topic(
            TopicNode(
                id="THEME_TEST",
                theme_id="THEME_TEST",
                name="测试主题",
                description="测试",
                slots_filled={"entities": False, "relationships": False},
            )
        )

        inserted = driver.inserted_nodes[0]
        self.assertIsInstance(inserted["slots_filled"], str)
        self.assertIn('"entities": false', inserted["slots_filled"])

    def test_sync_themes_resyncs_when_topic_count_is_partial(self):
        expected = len(ThemeLoader().load())
        driver = FakeTopicDriver(topic_count=expected - 1)
        manager = Neo4jGraphManager(driver=driver)

        written = manager.sync_themes_to_neo4j()

        self.assertEqual(written, expected)
        self.assertEqual(len(driver.inserted_nodes), expected)


if __name__ == "__main__":
    unittest.main()
