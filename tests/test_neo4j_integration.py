"""Neo4j integration tests.

These tests require a running Neo4j instance.  They are skipped
automatically if ``NEO4J_ENABLED`` is not set or the server is
unreachable.
"""

from __future__ import annotations

import os
import uuid
import unittest

from src.config import Config


def _neo4j_available() -> bool:
    if not Config.NEO4J_ENABLED:
        return False
    try:
        from src.storage.neo4j.driver import Neo4jGraphDriver
        drv = Neo4jGraphDriver()
        drv.connect()
        drv.close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_neo4j_available(), "Neo4j not available")
class TestNeo4jDriver(unittest.TestCase):
    """Tests for Neo4jGraphDriver CRUD operations."""

    @classmethod
    def setUpClass(cls):
        from src.storage.neo4j.driver import Neo4jGraphDriver
        cls.driver = Neo4jGraphDriver()
        cls.driver.connect()
        cls.driver.initialize_schema()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "driver") and cls.driver.driver:
            # Clean up test data
            cls.driver.execute_query("MATCH (n) WHERE n.id STARTS WITH 'test_' DETACH DELETE n")
            cls.driver.close()

    def test_01_insert_and_read_node(self):
        node_id = f"test_topic_{uuid.uuid4().hex[:8]}"
        ok = self.driver.insert_node({
            "id": node_id,
            "type": "Topic",
            "name": "Test Theme",
            "status": "pending",
        })
        self.assertTrue(ok)
        node = self.driver.get_node(node_id)
        self.assertIsNotNone(node)
        self.assertEqual(node["name"], "Test Theme")

    def test_02_insert_edge(self):
        src = f"test_topic_{uuid.uuid4().hex[:8]}"
        tgt = f"test_event_{uuid.uuid4().hex[:8]}"
        self.driver.insert_node({"id": src, "type": "Topic", "name": "Parent"})
        self.driver.insert_node({"id": tgt, "type": "Event", "name": "Child"})
        ok = self.driver.insert_edge(src, tgt, "INCLUDES")
        self.assertTrue(ok)

    def test_03_hop_query(self):
        topic_id = f"test_topic_{uuid.uuid4().hex[:8]}"
        event_id = f"test_event_{uuid.uuid4().hex[:8]}"
        self.driver.insert_node({"id": topic_id, "type": "Topic", "name": "HopTopic"})
        self.driver.insert_node({"id": event_id, "type": "Event", "name": "HopEvent"})
        self.driver.insert_edge(topic_id, event_id, "INCLUDES")

        result = self.driver.query_by_hop(topic_id, hop_count=1)
        self.assertIsNotNone(result["center"])
        self.assertGreater(result["total_nodes"], 0)


@unittest.skipUnless(_neo4j_available(), "Neo4j not available")
class TestNeo4jManager(unittest.TestCase):
    """Tests for Neo4jGraphManager high-level operations."""

    @classmethod
    def setUpClass(cls):
        from src.storage.neo4j.driver import Neo4jGraphDriver
        from src.storage.neo4j.manager import Neo4jGraphManager
        cls.mgr = Neo4jGraphManager(Neo4jGraphDriver())
        cls.mgr.initialize()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "mgr"):
            cls.mgr.driver.execute_query(
                "MATCH (n) WHERE n.id STARTS WITH 'test_' DETACH DELETE n"
            )
            cls.mgr.close()

    def test_01_upsert_topic(self):
        from src.storage.neo4j.models import TopicNode
        topic = TopicNode(
            id=f"test_THEME_01",
            theme_id=f"test_THEME_01",
            name="人生篇章",
            description="Test topic",
            domain="life_chapters",
            status="pending",
            priority=3,
            slots_filled={"time": False, "location": False},
        )
        ok = self.mgr.upsert_topic(topic)
        self.assertTrue(ok)

    def test_02_upsert_event(self):
        from src.storage.neo4j.models import EventNodeNeo4j
        event = EventNodeNeo4j(
            id=f"test_evt_{uuid.uuid4().hex[:8]}",
            title="童年记忆",
            description="小时候的故事",
            theme_id="test_THEME_01",
        )
        ok = self.mgr.upsert_event(event, "test_THEME_01")
        self.assertTrue(ok)

    def test_03_coverage(self):
        metrics = self.mgr.get_coverage_metrics()
        self.assertIn("overall", metrics)
        self.assertIsInstance(metrics["overall"], float)

    def test_04_detect_patterns(self):
        patterns = self.mgr.detect_patterns()
        self.assertIsInstance(patterns, list)


if __name__ == "__main__":
    unittest.main()
