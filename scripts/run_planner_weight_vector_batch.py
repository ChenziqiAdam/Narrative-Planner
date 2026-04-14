#!/usr/bin/env python3
"""
Run planner sessions with multiple external decision weight vectors.

Example:
  python scripts/run_planner_weight_vector_batch.py \
    --vectors-file docs/planner-weight-experiments/vector_groups.sample.json \
    --turns 20
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src.app import app, _compare_sessions, _save_conversation


def _parse_interviewer_events(raw_sse: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for block in raw_sse.split("\n\n"):
        block = block.strip()
        if not block.startswith("data: "):
            continue
        payload = block[6:]
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if data.get("role") == "interviewer":
            events.append(data)
    return events


def run_one_vector(
    client: Any,
    elder_info: Dict[str, Any],
    vector_name: str,
    vector_values: List[float],
    turns: int,
) -> Dict[str, Any]:
    start_resp = client.post(
        "/api/planner/start",
        json={
            "elder_info": elder_info,
            "mode": "ai",
            "decision_weight_vector": vector_values,
        },
    )
    if start_resp.status_code != 200:
        raise RuntimeError(f"planner start failed for {vector_name}: {start_resp.status_code} {start_resp.get_data(as_text=True)}")

    payload = start_resp.get_json()
    session_id = payload["session_id"]
    interviewer_turns = 0
    actions: List[str] = []

    while interviewer_turns < turns:
        resp = client.get(f"/api/planner/auto?session_id={session_id}&single_turn=1")
        if resp.status_code != 200:
            raise RuntimeError(f"planner auto failed for {vector_name}: {resp.status_code} {resp.get_data(as_text=True)}")

        interviewer_events = _parse_interviewer_events(resp.get_data(as_text=True))
        for ev in interviewer_events:
            interviewer_turns += 1
            actions.append(str(ev.get("action", "continue")))
            if interviewer_turns >= turns:
                break

    _save_conversation(session_id, _compare_sessions[session_id])

    text_file = Path("results/conversations") / f"planner_{session_id}.txt"
    state_file = Path("results/conversations") / f"planner_state_{session_id}.json"

    return {
        "name": vector_name,
        "session_id": session_id,
        "first_question": payload.get("first_question", ""),
        "decision_weight_payload": payload.get("decision_weight_payload", {}),
        "interviewer_turns": interviewer_turns,
        "actions": actions,
        "action_counts": dict(Counter(actions)),
        "conversation_file": str(text_file),
        "state_file": str(state_file),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch-run planner with multiple weight vectors")
    parser.add_argument("--vectors-file", required=True, help="JSON file with elder_info + vectors")
    parser.add_argument("--turns", type=int, default=20, help="Interviewer turns per vector")
    args = parser.parse_args()

    vectors_file = Path(args.vectors_file)
    if not vectors_file.exists():
        raise FileNotFoundError(f"Vectors file not found: {vectors_file}")

    config = json.loads(vectors_file.read_text(encoding="utf-8"))
    elder_info = config.get("elder_info", {})
    vectors = config.get("vectors", [])

    if not isinstance(elder_info, dict) or not elder_info:
        raise ValueError("vectors-file must include non-empty elder_info object")
    if not isinstance(vectors, list) or not vectors:
        raise ValueError("vectors-file must include non-empty vectors list")

    results: List[Dict[str, Any]] = []

    with app.test_client() as client:
        for idx, item in enumerate(vectors, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"vectors[{idx-1}] must be an object")
            name = str(item.get("name") or f"vector_{idx}")
            vector = item.get("vector")
            if not isinstance(vector, list) or not all(isinstance(v, (int, float)) for v in vector):
                raise ValueError(f"vectors[{idx-1}].vector must be numeric list")
            print(f"[run] {name} turns={args.turns}")
            run_result = run_one_vector(client, elder_info, name, [float(v) for v in vector], args.turns)
            results.append(run_result)

    out_dir = Path("results/conversations")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = out_dir / f"planner_weight_vector_batch_{ts}.json"
    summary = {
        "generated_at": datetime.now().isoformat(),
        "turns_per_vector": args.turns,
        "vectors_file": str(vectors_file),
        "results": results,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    compat_dir = Path("results/conversation")
    compat_dir.mkdir(parents=True, exist_ok=True)
    compat_summary_path = compat_dir / summary_path.name
    compat_summary_path.write_text(summary_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(json.dumps({
        "summary_path": str(summary_path),
        "compat_summary_path": str(compat_summary_path),
        "vector_count": len(results),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
