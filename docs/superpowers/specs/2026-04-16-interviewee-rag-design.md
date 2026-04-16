---
title: Interviewee RAG — Semantic Memory Retrieval
date: 2026-04-16
status: approved
---

## Background

The `IntervieweeAgent` already has keyword-based and tag-based memory recall via OpenAI tool calling (`ElderMemorySystem`). Keyword search fails on conceptual or paraphrased queries (e.g., "艰难时期", "最自豪的事") that don't share exact tokens with stored memory text. Adding semantic/vector search as a complementary tool lets the LLM retrieve relevant memories by meaning, not just token overlap.

## Design

### Component: `ProfileVectorStore` (reuse `EventVectorStore`)

`EventVectorStore` is already a general-purpose FAISS cosine-similarity index over (id, text) pairs. No changes needed to the class. `ElderMemorySystem` will instantiate it internally as `self._vector_store = EventVectorStore()`.

### Indexing at init

`ElderMemorySystem.__init__` calls a new private method `_build_vector_index()` after `_build_memory_index()`.

`_build_vector_index()` iterates `self.memory_index` and for each entry calls:

```python
text = f"{memory.get('event_name', '')} {memory.get('description', '')} {memory.get('details', '')}"
self._vector_store.add(memory_id, text)
```

The embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) loads lazily via the existing `_get_model` singleton — no cold-start penalty unless at least one memory exists.

### New method

```python
def search_memories_by_semantic(
    self,
    query: str,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """
    语义搜索记忆，适合模糊或概念性查询。
    返回格式与 search_memories_by_keywords 一致。
    """
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

### Tool schema addition

Added to `get_tool_schemas()`:

```json
{
  "type": "function",
  "function": {
    "name": "search_memories_by_semantic",
    "description": "用自然语言语义搜索老人记忆，适合模糊或概念性查询（如"艰难时期"、"最自豪的事"）",
    "parameters": {
      "type": "object",
      "properties": {
        "query": { "type": "string", "description": "自然语言查询" },
        "top_k": { "type": "integer", "description": "返回结果数量", "default": 3 }
      },
      "required": ["query"]
    }
  }
}
```

Registered in `get_tool_callables`:

```python
"search_memories_by_semantic": ms.search_memories_by_semantic,
```

## Files changed

| File | Change |
|------|--------|
| `src/tools/elder_tools.py` | Add `_vector_store` to `ElderMemorySystem`, add `_build_vector_index()`, add `search_memories_by_semantic()`, update `get_tool_schemas()` and `get_tool_callables()` |

No changes to `IntervieweeAgent`, `EventVectorStore`, or any orchestration code.

## Non-goals

- No changes to session-level `EventVectorStore` (interviewer side)
- No prompt injection of RAG results — LLM decides when to call the tool
- No persistence of the profile vector index (rebuilt from profile JSON each session)
