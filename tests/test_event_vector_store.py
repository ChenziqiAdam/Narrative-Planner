"""Tests for EventVectorStore - session-level FAISS cosine similarity search."""
import pytest


class TestEventVectorStoreBasics:
    def test_size_empty(self):
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        assert store.size == 0

    def test_add_increases_size(self):
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        store.add("evt_001", "参加了高中毕业典礼")
        assert store.size == 1
        store.add("evt_002", "大学入学考试")
        assert store.size == 2

    def test_search_returns_empty_when_store_empty(self):
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        results = store.search("毕业典礼", top_k=2)
        assert results == []

    def test_search_returns_event_id_and_score(self):
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        store.add("evt_001", "参加了高中毕业典礼")
        results = store.search("毕业", top_k=1)
        assert len(results) == 1
        event_id, score = results[0]
        assert event_id == "evt_001"
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0 + 1e-6  # cosine similarity, allow float rounding

    def test_search_returns_most_similar(self):
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        store.add("evt_001", "参加了高中毕业典礼")
        store.add("evt_002", "在工厂做工人")
        store.add("evt_003", "大学毕业")
        results = store.search("毕业典礼", top_k=1)
        assert len(results) == 1
        assert results[0][0] in ("evt_001", "evt_003")  # both graduation-related

    def test_search_top_k_limits_results(self):
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        for i in range(5):
            store.add(f"evt_{i:03d}", f"事件描述 {i}")
        results = store.search("事件", top_k=2)
        assert len(results) == 2

    def test_search_top_k_capped_by_store_size(self):
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        store.add("evt_001", "参加了高中毕业典礼")
        results = store.search("毕业", top_k=5)
        assert len(results) == 1  # only 1 event in store

    def test_add_duplicate_id_overwrites(self):
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        store.add("evt_001", "参加了高中毕业典礼")
        store.add("evt_001", "更新后的描述：大学毕业")
        assert store.size == 1  # size unchanged
        results = store.search("大学毕业", top_k=1)
        assert results[0][0] == "evt_001"
