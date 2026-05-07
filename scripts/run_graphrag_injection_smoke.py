#!/usr/bin/env python3
"""Run a real Neo4j GraphRAG injection/retrieval smoke experiment.

This script validates the core GraphRAG loop without requiring external LLM
keys: scripted "extractions" are written through the production GraphWriter,
then retrieved through HybridRetriever from the updated graph/vector store.
It answers the operational question: after a respondent answer is injected
into GraphRAG, can the next planner retrieval see that fresh evidence?
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.graph_rag_metrics import (  # noqa: E402
    build_extraction_metrics,
    build_retrieval_metrics,
    build_write_metrics,
)
from src.services.graph_writer import GraphWriter  # noqa: E402
from src.services.hybrid_retriever import HybridRetriever  # noqa: E402
from src.state.narrative_models import (  # noqa: E402
    ExtractedEntity,
    ExtractedRelationship,
    GraphExtraction,
)
from src.storage.neo4j.manager import Neo4jGraphManager  # noqa: E402


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results" / "graphrag-observation"


SCRIPTED_EVENTS: List[Dict[str, Any]] = [
    {
        "event": "搬到县城",
        "description": "1978年全家从村里搬到县城，母亲把旧木箱捆在自行车后座上，我第一次见到县城的百货楼。",
        "person": "母亲",
        "location": "县城百货楼",
        "emotion": "新鲜又不舍",
        "theme_id": "THEME_01_LIFE_CHAPTERS",
    },
    {
        "event": "进入机械厂",
        "description": "1982年我进了机械厂当学徒，师傅老周教我看图纸，也让我第一次觉得手艺能改变一家人的日子。",
        "person": "老周师傅",
        "location": "机械厂车间",
        "emotion": "紧张但自豪",
        "theme_id": "THEME_07_ADULT_MEMORY",
    },
    {
        "event": "照顾生病父亲",
        "description": "父亲住院那段时间，我白天上班晚上去医院守着，兄弟姐妹轮流送饭，那是家里最难的一段。",
        "person": "父亲",
        "location": "县医院",
        "emotion": "疲惫和担心",
        "theme_id": "THEME_14_HEALTH",
    },
    {
        "event": "女儿出生",
        "description": "女儿出生那天正下大雨，我骑车去请接生员，听见孩子哭出来的时候，心里一下子踏实了。",
        "person": "女儿",
        "location": "老屋",
        "emotion": "踏实和欢喜",
        "theme_id": "THEME_02_PEAK_EXPERIENCE",
    },
    {
        "event": "退休后学书法",
        "description": "退休以后我在社区活动室学书法，每周三和几个老同事一起练字，日子慢下来反而更有味道。",
        "person": "老同事",
        "location": "社区活动室",
        "emotion": "安定和满足",
        "theme_id": "THEME_20_SINGLE_VALUE",
    },
]


class KeywordEmbeddingService:
    """Small deterministic embedding service for repeatable smoke tests."""

    keywords = [
        "搬", "县城", "母亲", "机械", "师傅", "工厂", "父亲", "医院",
        "女儿", "出生", "退休", "书法", "社区", "自豪", "担心", "欢喜",
    ]

    def encode_single(self, text: str) -> List[float]:
        text = text or ""
        vec = [float(text.count(keyword)) for keyword in self.keywords]
        vec.append(float(len(text)) / 200.0)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def encode(self, texts: List[str]) -> List[List[float]]:
        return [self.encode_single(text) for text in texts]


class SimpleVectorStore:
    """FAISS-free vector store with the EntityVectorStore interface subset."""

    def __init__(self, embedding_service: KeywordEmbeddingService):
        self.embedding_service = embedding_service
        self.items: Dict[str, Tuple[str, str, List[float]]] = {}

    def add(
        self,
        entity_id: str,
        entity_type: str,
        text: str,
        embedding: List[float] | None = None,
    ) -> None:
        self.items[entity_id] = (
            entity_type,
            text,
            embedding or self.embedding_service.encode_single(text),
        )

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        entity_type: str | None = None,
    ) -> List[Tuple[str, float]]:
        rows: List[Tuple[str, float]] = []
        for entity_id, (stored_type, _text, embedding) in self.items.items():
            if entity_type and stored_type != entity_type:
                continue
            score = sum(a * b for a, b in zip(query_embedding, embedding))
            rows.append((entity_id, float(score)))
        rows.sort(key=lambda item: item[1], reverse=True)
        return rows[:top_k]

    def search_by_text(
        self,
        query_text: str,
        top_k: int = 5,
        entity_type: str | None = None,
    ) -> List[Tuple[str, str, float]]:
        embedding = self.embedding_service.encode_single(query_text)
        return [
            (entity_id, self.items[entity_id][0], score)
            for entity_id, score in self.search(embedding, top_k, entity_type)
        ]

    def get_embedding(self, entity_id: str) -> List[float] | None:
        item = self.items.get(entity_id)
        return item[2] if item else None


@dataclass
class TurnObservation:
    turn_index: int
    answer: str
    event_name: str
    event_id: str
    pre_retrieval: Dict[str, Any]
    extraction: Dict[str, Any]
    write: Dict[str, Any]
    post_retrieval: Dict[str, Any]
    fresh_event_in_top_entities: bool
    fresh_event_in_context: bool
    context_gain: int


def _build_extraction(item: Dict[str, Any]) -> GraphExtraction:
    event = ExtractedEntity(
        entity_type="Event",
        name=item["event"],
        description=item["description"],
        properties={"theme_id": item["theme_id"]},
    )
    person = ExtractedEntity(
        entity_type="Person",
        name=item["person"],
        description=f"{item['event']}中提到的重要人物：{item['person']}",
    )
    location = ExtractedEntity(
        entity_type="Location",
        name=item["location"],
        description=f"{item['event']}发生或被记起的地点：{item['location']}",
    )
    emotion = ExtractedEntity(
        entity_type="Emotion",
        name=item["emotion"],
        description=f"{item['event']}带出的情绪：{item['emotion']}",
    )
    return GraphExtraction(
        entities=[event, person, location, emotion],
        relationships=[
            ExtractedRelationship(item["person"], item["event"], "PARTICIPATES_IN"),
            ExtractedRelationship(item["event"], item["location"], "LOCATED_AT"),
            ExtractedRelationship(item["event"], item["emotion"], "TRIGGERS"),
        ],
        narrative_summary=item["description"],
        open_loops=[f"继续追问{item['event']}的感受和后来影响"],
        emotional_state={"energy": 0.7, "valence": "mixed"},
        confidence=0.92,
    )


def _cleanup_session(manager: Neo4jGraphManager, session_id: str) -> None:
    manager.driver.execute_query(
        "MATCH (n {session_id: $session_id}) DETACH DELETE n",
        {"session_id": session_id},
    )


def _run(args: argparse.Namespace) -> Dict[str, Any]:
    session_id = args.session_id or f"graphrag_smoke_{uuid.uuid4().hex[:8]}"
    elder_id = args.elder_id or f"{session_id}_elder"
    manager = Neo4jGraphManager()
    manager.initialize()
    manager.sync_themes_to_neo4j()
    _cleanup_session(manager, session_id)

    embedding = KeywordEmbeddingService()
    vector_store = SimpleVectorStore(embedding)
    writer = GraphWriter(manager, vector_store, embedding_service=embedding)
    retriever = HybridRetriever(manager, vector_store)

    observations: List[TurnObservation] = []
    try:
        turns = max(1, int(args.turns))
        for index in range(1, turns + 1):
            item = SCRIPTED_EVENTS[(index - 1) % len(SCRIPTED_EVENTS)]
            answer = item["description"]

            pre = retriever.retrieve(answer, session_id, max_tokens=args.max_tokens)
            extraction = _build_extraction(item)

            t0 = time.perf_counter()
            write_result = writer.write_extraction(
                extraction,
                session_id=session_id,
                elder_id=elder_id,
            )
            write_ms = (time.perf_counter() - t0) * 1000

            post = retriever.retrieve(answer, session_id, max_tokens=args.max_tokens)
            event_id = next(
                (entity_id for entity_id in write_result.entity_ids if entity_id.startswith("event_")),
                "",
            )
            top_ids = {
                str(entity.get("entity_id"))
                for entity in post.trace.get("top_entities", [])
                if isinstance(entity, dict)
            }
            fresh_event_in_top_entities = bool(event_id and event_id in top_ids)
            fresh_event_in_context = item["event"] in post.prompt_text or item["description"][:20] in post.prompt_text

            observations.append(
                TurnObservation(
                    turn_index=index,
                    answer=answer,
                    event_name=item["event"],
                    event_id=event_id,
                    pre_retrieval=build_retrieval_metrics(pre),
                    extraction=build_extraction_metrics(extraction, latency_ms=0.0),
                    write=build_write_metrics(write_result, latency_ms=write_ms),
                    post_retrieval=build_retrieval_metrics(post),
                    fresh_event_in_top_entities=fresh_event_in_top_entities,
                    fresh_event_in_context=fresh_event_in_context,
                    context_gain=max(0, len(post.prompt_text) - len(pre.prompt_text)),
                )
            )
    finally:
        if args.cleanup:
            _cleanup_session(manager, session_id)
        manager.close()

    turns_payload = [asdict(item) for item in observations]
    total = max(1, len(observations))
    summary = {
        "session_id": session_id,
        "turns": len(observations),
        "fresh_event_top_hit_rate": round(
            sum(1 for item in observations if item.fresh_event_in_top_entities) / total,
            4,
        ),
        "fresh_event_context_hit_rate": round(
            sum(1 for item in observations if item.fresh_event_in_context) / total,
            4,
        ),
        "pre_context_empty_rate": round(
            sum(1 for item in observations if item.pre_retrieval["context_empty"]) / total,
            4,
        ),
        "post_context_empty_rate": round(
            sum(1 for item in observations if item.post_retrieval["context_empty"]) / total,
            4,
        ),
        "avg_context_gain_chars": round(
            sum(item.context_gain for item in observations) / total,
            2,
        ),
        "avg_post_ranked_entities": round(
            sum(item.post_retrieval["ranked_entity_count"] for item in observations) / total,
            2,
        ),
        "total_new_entities": sum(item.write["new_entity_count"] for item in observations),
        "total_updated_entities": sum(item.write["updated_entity_count"] for item in observations),
        "total_relationships_written": sum(item.write["relationship_count"] for item in observations),
    }

    output = {
        "generated_at": datetime.now().isoformat(),
        "experiment": "graphrag_injection_smoke",
        "summary": summary,
        "turns": turns_payload,
        "config": {
            "turns": args.turns,
            "max_tokens": args.max_tokens,
            "cleanup": args.cleanup,
            "elder_id": elder_id,
            "uses_real_neo4j": True,
            "uses_external_llm": False,
        },
    }
    _write_output(Path(args.output_dir), session_id, output)
    return output


def _write_output(output_dir: Path, session_id: str, output: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{session_id}.json"
    md_path = output_dir / f"{session_id}.md"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# GraphRAG Injection Smoke: {session_id}",
        "",
        "```json",
        json.dumps(output["summary"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Turns",
    ]
    for turn in output["turns"]:
        lines.extend(
            [
                "",
                f"### Turn {turn['turn_index']}: {turn['event_name']}",
                f"- event_id: `{turn['event_id']}`",
                f"- fresh_event_in_top_entities: `{turn['fresh_event_in_top_entities']}`",
                f"- fresh_event_in_context: `{turn['fresh_event_in_context']}`",
                f"- pre ranked: `{turn['pre_retrieval']['ranked_entity_count']}`",
                f"- post ranked: `{turn['post_retrieval']['ranked_entity_count']}`",
                f"- context gain chars: `{turn['context_gain']}`",
            ]
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    output["output_files"] = {"json": str(json_path), "markdown": str(md_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate GraphRAG injection and post-write retrieval.")
    parser.add_argument("--turns", type=int, default=12)
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--session-id", default="")
    parser.add_argument("--elder-id", default="")
    parser.add_argument("--cleanup", action="store_true", help="Delete smoke session nodes after the run.")
    return parser.parse_args()


def main() -> None:
    output = _run(parse_args())
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(json.dumps(output["output_files"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
