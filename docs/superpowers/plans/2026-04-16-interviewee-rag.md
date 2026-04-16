# Interviewee RAG — Semantic Memory Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `search_memories_by_semantic` as a vector-based tool to `ElderMemorySystem`, enabling the interviewee LLM to retrieve profile memories by semantic similarity alongside existing keyword/tag tools.

**Architecture:** `ElderMemorySystem` gets a `ProfileVectorStore` (an `EventVectorStore` instance) built at init time by iterating all profile memory events. A new `search_memories_by_semantic(query, top_k)` method is exposed and registered as an OpenAI function-calling tool — same shape as existing tools, no changes to `IntervieweeAgent`.

**Tech Stack:** `EventVectorStore` (FAISS + `sentence-transformers`), existing `get_tool_schemas` / `get_tool_callables` pattern.

---

### Task 1: Write failing tests for `search_memories_by_semantic`

**Files:**
- Test: `tests/test_elder_tools_semantic.py`

- [ ] **Step 1: Create the test file**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_elder_tools_semantic.py -v
```

Expected: all tests FAIL — `AttributeError: 'ElderMemorySystem' object has no attribute 'search_memories_by_semantic'` or similar.

---

### Task 2: Implement `search_memories_by_semantic` in `ElderMemorySystem`

**Files:**
- Modify: `src/tools/elder_tools.py`

- [ ] **Step 1: Add `_vector_store` init and `_build_vector_index` to `ElderMemorySystem`**

In `ElderMemorySystem.__init__`, add after `self._build_memory_index()`:

```python
from src.services.event_vector_store import EventVectorStore
self._vector_store = EventVectorStore()
self._build_vector_index()
```

Add the new private method to the class:

```python
def _build_vector_index(self) -> None:
    for memory_id, memory_info in self.memory_index.items():
        memory = memory_info["memory"]
        text = " ".join(filter(None, [
            memory.get("event_name", ""),
            memory.get("description", ""),
            memory.get("details", ""),
        ]))
        if text.strip():
            self._vector_store.add(memory_id, text)
```

- [ ] **Step 2: Add `search_memories_by_semantic` method**

Add to the `ElderMemorySystem` class (after `get_related_memories`):

```python
def search_memories_by_semantic(
    self,
    query: str,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """语义搜索记忆，适合模糊或概念性查询。返回格式与 search_memories_by_keywords 一致。"""
    hits = self._vector_store.search(query, top_k)
    results = []
    for memory_id, score in hits:
        memory_info = self.memory_index.get(memory_id)
        if memory_info:
            results.append({
                "memory_id": memory_id,
                "memory": memory_info["memory"],
                "period": memory_info["period"],
                "similarity_score": score,
            })
    return results
```

- [ ] **Step 3: Add tool schema entry in `get_tool_schemas`**

Append to the list returned by `get_tool_schemas()`:

```python
{
    "type": "function",
    "function": {
        "name": "search_memories_by_semantic",
        "description": "用自然语言语义搜索老人记忆，适合模糊或概念性查询（如"艰难时期"、"最自豪的事"）",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言查询"},
                "top_k": {"type": "integer", "description": "返回结果数量限制", "default": 3},
            },
            "required": ["query"],
        },
    },
},
```

- [ ] **Step 4: Register in `get_tool_callables`**

In `get_tool_callables`, add:

```python
"search_memories_by_semantic": ms.search_memories_by_semantic,
```

- [ ] **Step 5: Run the new tests**

```bash
pytest tests/test_elder_tools_semantic.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run existing tests to confirm no regressions**

```bash
pytest tests/ -v
```

Expected: all previously passing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add src/tools/elder_tools.py tests/test_elder_tools_semantic.py
git commit -m "feat(interviewee): add semantic memory search tool via EventVectorStore"
```

---

## Self-Review

**Spec coverage:**
- ✅ `ProfileVectorStore` (`EventVectorStore` instance) built at init → Task 2, Step 1
- ✅ `_build_vector_index()` indexes all profile memory events → Task 2, Step 1
- ✅ `search_memories_by_semantic(query, top_k)` method → Task 2, Step 2
- ✅ Return shape matches keyword search → Task 2, Step 2 (memory_id, memory, period + similarity_score)
- ✅ Tool schema added → Task 2, Step 3
- ✅ Registered in `get_tool_callables` → Task 2, Step 4
- ✅ No changes to `IntervieweeAgent` → correct, not in any task

**Placeholder scan:** None found.

**Type consistency:** `search_memories_by_semantic` defined in Task 2 Step 2, referenced in schema Task 2 Step 3 and callables Task 2 Step 4 — all consistent. Return type `List[Dict[str, Any]]` matches `search_memories_by_keywords` shape.
