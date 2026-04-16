"""Tests for ElderMemorySystem.search_memories_by_semantic."""
import json
import os
import tempfile
import pytest


PROFILE = {
    "elder_profile": {
        "life_memories_by_period": {
            "period_1": {
                "memory_events": [
                    {
                        "event_id": "mem_001",
                        "event_name": "高中毕业典礼",
                        "description": "参加了学校的毕业典礼，心情激动",
                        "details": "穿着校服和同学合影留念",
                        "tags": ["毕业", "学校"],
                        "emotional_weight": 8,
                    },
                    {
                        "event_id": "mem_002",
                        "event_name": "工厂上班第一天",
                        "description": "进入纺织厂成为一名工人",
                        "details": "师傅带我熟悉车间环境",
                        "tags": ["工作", "工厂"],
                        "emotional_weight": 6,
                    },
                ]
            },
            "period_2": {
                "memory_events": [
                    {
                        "event_id": "mem_003",
                        "event_name": "结婚典礼",
                        "description": "和丈夫举办了简单的婚礼",
                        "details": "邻居们都来祝贺",
                        "tags": ["婚姻", "家庭"],
                        "emotional_weight": 9,
                    }
                ]
            },
        }
    }
}


@pytest.fixture
def profile_path(tmp_path):
    path = tmp_path / "elder.json"
    path.write_text(json.dumps(PROFILE, ensure_ascii=False), encoding="utf-8")
    return str(path)


class TestSearchMemoriesBySemantic:
    def test_returns_list(self, profile_path):
        from src.tools.elder_tools import ElderMemorySystem
        ms = ElderMemorySystem(profile_path)
        results = ms.search_memories_by_semantic("毕业", top_k=2)
        assert isinstance(results, list)

    def test_returns_memory_dicts_with_expected_keys(self, profile_path):
        from src.tools.elder_tools import ElderMemorySystem
        ms = ElderMemorySystem(profile_path)
        results = ms.search_memories_by_semantic("毕业", top_k=1)
        assert len(results) == 1
        result = results[0]
        assert "memory_id" in result
        assert "memory" in result
        assert "period" in result
        assert "similarity_score" in result

    def test_most_relevant_returned_first(self, profile_path):
        from src.tools.elder_tools import ElderMemorySystem
        ms = ElderMemorySystem(profile_path)
        results = ms.search_memories_by_semantic("毕业典礼学校", top_k=3)
        assert len(results) >= 1
        assert results[0]["memory_id"] == "mem_001"

    def test_top_k_limits_results(self, profile_path):
        from src.tools.elder_tools import ElderMemorySystem
        ms = ElderMemorySystem(profile_path)
        results = ms.search_memories_by_semantic("人生经历", top_k=2)
        assert len(results) <= 2

    def test_similarity_score_is_float_between_0_and_1(self, profile_path):
        from src.tools.elder_tools import ElderMemorySystem
        ms = ElderMemorySystem(profile_path)
        results = ms.search_memories_by_semantic("工作", top_k=1)
        assert len(results) == 1
        score = results[0]["similarity_score"]
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0 + 1e-6

    def test_empty_profile_returns_empty_list(self, tmp_path):
        from src.tools.elder_tools import ElderMemorySystem
        empty_profile = {"elder_profile": {"life_memories_by_period": {}}}
        path = tmp_path / "empty.json"
        path.write_text(json.dumps(empty_profile), encoding="utf-8")
        ms = ElderMemorySystem(str(path))
        results = ms.search_memories_by_semantic("任何查询", top_k=3)
        assert results == []


class TestToolSchemaIncludesSemanticSearch:
    def test_schema_contains_semantic_tool(self):
        from src.tools.elder_tools import get_tool_schemas
        schemas = get_tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "search_memories_by_semantic" in names

    def test_semantic_tool_schema_has_required_query(self):
        from src.tools.elder_tools import get_tool_schemas
        schemas = get_tool_schemas()
        semantic = next(s for s in schemas if s["function"]["name"] == "search_memories_by_semantic")
        assert "query" in semantic["function"]["parameters"]["required"]

    def test_semantic_tool_schema_has_top_k_param(self):
        from src.tools.elder_tools import get_tool_schemas
        schemas = get_tool_schemas()
        semantic = next(s for s in schemas if s["function"]["name"] == "search_memories_by_semantic")
        props = semantic["function"]["parameters"]["properties"]
        assert "top_k" in props


class TestToolCallablesIncludesSemanticSearch:
    def test_callables_contains_semantic_search(self, profile_path):
        from src.tools.elder_tools import ElderMemorySystem, get_tool_callables
        ms = ElderMemorySystem(profile_path)
        callables = get_tool_callables(ms)
        assert "search_memories_by_semantic" in callables
        assert callable(callables["search_memories_by_semantic"])
