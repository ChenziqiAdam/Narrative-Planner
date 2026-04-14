#!/usr/bin/env python3
"""
Run M planner vectors for N interviewer turns, score each run, and analyze to find best vector.

Usage:
  python scripts/run_planner_vector_optimization.py \
    --vectors-file docs/planner-weight-experiments/vector_groups.sample.json \
    --turns 20 \
    --repeats 3 \
    --use-llm-scorer
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root on sys.path when run as script.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.app import app, _compare_sessions, _save_conversation
from src.services.conversation_result_scorer import (
    ConversationResultScorer,
    aggregate_vector_scores,
    bootstrap_ci,
    pareto_front,
)


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


def _copy_to_compat(paths: List[Path]) -> None:
    compat_dir = Path("results/conversation")
    compat_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        target = compat_dir / path.name
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def run_single_vector_session(
    client: Any,
    elder_info: Dict[str, Any],
    vector_name: str,
    vector: List[float],
    turns: int,
    run_index: int,
    scorer: ConversationResultScorer,
) -> Dict[str, Any]:
    start_resp = client.post(
        "/api/planner/start",
        json={
            "elder_info": elder_info,
            "mode": "ai",
            "decision_weight_vector": vector,
        },
    )
    if start_resp.status_code != 200:
        raise RuntimeError(
            f"planner start failed ({vector_name} run#{run_index}): "
            f"{start_resp.status_code} {start_resp.get_data(as_text=True)}"
        )

    payload = start_resp.get_json()
    session_id = payload["session_id"]

    actions: List[str] = []
    interviewer_turns = 0

    while interviewer_turns < turns:
        resp = client.get(f"/api/planner/auto?session_id={session_id}&single_turn=1")
        if resp.status_code != 200:
            raise RuntimeError(
                f"planner auto failed ({vector_name} run#{run_index}): "
                f"{resp.status_code} {resp.get_data(as_text=True)}"
            )
        for ev in _parse_interviewer_events(resp.get_data(as_text=True)):
            interviewer_turns += 1
            actions.append(str(ev.get("action", "continue")))
            if interviewer_turns >= turns:
                break

    _save_conversation(session_id, _compare_sessions[session_id])

    conv_file = Path("results/conversations") / f"planner_{session_id}.txt"
    state_file = Path("results/conversations") / f"planner_state_{session_id}.json"
    _copy_to_compat([conv_file, state_file])

    score_result = scorer.score_from_files(
        conversation_txt_path=conv_file,
        planner_state_json_path=state_file,
        vector_name=vector_name,
        vector=vector,
    )

    return {
        "vector_name": vector_name,
        "vector": vector,
        "run_index": run_index,
        "session_id": session_id,
        "interviewer_turns": interviewer_turns,
        "actions": actions,
        "action_counts": {
            "continue": actions.count("continue"),
            "next_phase": actions.count("next_phase"),
            "end": actions.count("end"),
        },
        "decision_weight_payload": payload.get("decision_weight_payload", {}),
        "conversation_file": str(conv_file),
        "state_file": str(state_file),
        "score": score_result.to_dict(),
    }


def build_analysis_methods_note() -> List[str]:
    return [
        "Descriptive statistics: mean/std/min/max of overall score per vector.",
        "Bootstrap confidence interval: non-parametric CI for mean overall score per vector.",
        "Pareto front analysis: identify vectors not dominated on multi-objectives.",
        "Stability analysis: compare score variance across repeated runs (repeats).",
        "Action-distribution analysis: compare continue/next_phase/end mix against target interviewing behavior.",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Planner vector optimization with scoring and analysis")
    parser.add_argument("--vectors-file", required=True, help="JSON containing elder_info and vectors")
    parser.add_argument("--turns", type=int, default=20, help="Interviewer turns per run")
    parser.add_argument("--repeats", type=int, default=1, help="Runs per vector")
    parser.add_argument("--use-llm-scorer", action="store_true", help="Enable LLM holistic scorer")
    parser.add_argument("--llm-weight", type=float, default=0.3, help="Weight for LLM score in final score")
    args = parser.parse_args()

    vectors_file = Path(args.vectors_file)
    if not vectors_file.exists():
        raise FileNotFoundError(f"vectors file not found: {vectors_file}")

    cfg = json.loads(vectors_file.read_text(encoding="utf-8"))
    elder_info = cfg.get("elder_info")
    vectors = cfg.get("vectors")

    if not isinstance(elder_info, dict) or not elder_info:
        raise ValueError("vectors-file must contain non-empty elder_info object")
    if not isinstance(vectors, list) or not vectors:
        raise ValueError("vectors-file must contain non-empty vectors list")

    scorer = ConversationResultScorer(use_llm=args.use_llm_scorer, llm_weight=args.llm_weight)

    run_rows: List[Dict[str, Any]] = []

    with app.test_client() as client:
        for item in vectors:
            if not isinstance(item, dict):
                raise ValueError("Each vector item must be an object with name/vector")
            vector_name = str(item.get("name") or "unnamed_vector")
            vector = item.get("vector")
            if not isinstance(vector, list) or not all(isinstance(v, (int, float)) for v in vector):
                raise ValueError(f"Invalid vector for {vector_name}; expected numeric list")
            numeric_vector = [float(v) for v in vector]

            for run_index in range(1, max(1, args.repeats) + 1):
                print(f"[run] vector={vector_name} run={run_index}/{args.repeats} turns={args.turns}")
                row = run_single_vector_session(
                    client=client,
                    elder_info=elder_info,
                    vector_name=vector_name,
                    vector=numeric_vector,
                    turns=args.turns,
                    run_index=run_index,
                    scorer=scorer,
                )
                run_rows.append(row)

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in run_rows:
        grouped[row["vector_name"]].append(row)

    vector_summary: Dict[str, Any] = {}
    pareto_records: List[Dict[str, Any]] = []

    for vector_name, rows in grouped.items():
        aggregate = aggregate_vector_scores(rows)
        overall_values = [float(r["score"]["overall_score"]) for r in rows]
        ci = bootstrap_ci(overall_values)

        info_eff_values = [float(r["score"]["deterministic_breakdown"].get("information_effectiveness", 0.0)) for r in rows]
        struct_values = [float(r["score"]["deterministic_breakdown"].get("structure_coverage", 0.0)) for r in rows]
        non_redundancy_values = [float(r["score"]["deterministic_breakdown"].get("non_redundancy", 0.0)) for r in rows]

        pareto_metrics = {
            "overall_score_mean": aggregate.get("overall_mean", 0.0),
            "information_effectiveness_mean": round(sum(info_eff_values) / max(1, len(info_eff_values)), 4),
            "structure_coverage_mean": round(sum(struct_values) / max(1, len(struct_values)), 4),
            "non_redundancy_mean": round(sum(non_redundancy_values) / max(1, len(non_redundancy_values)), 4),
        }
        pareto_records.append({"vector_name": vector_name, "metrics": pareto_metrics})

        vector_summary[vector_name] = {
            "aggregate": aggregate,
            "bootstrap_ci": ci,
            "pareto_metrics": pareto_metrics,
            "runs": rows,
        }

    ranked = sorted(
        vector_summary.items(),
        key=lambda item: float(item[1]["aggregate"].get("overall_mean", 0.0)),
        reverse=True,
    )

    best_vector_name = ranked[0][0] if ranked else ""
    pareto_vectors = pareto_front(
        records=pareto_records,
        objectives=[
            "overall_score_mean",
            "information_effectiveness_mean",
            "structure_coverage_mean",
            "non_redundancy_mean",
        ],
    )

    result = {
        "generated_at": datetime.now().isoformat(),
        "vectors_file": str(vectors_file),
        "turns_per_run": args.turns,
        "repeats": args.repeats,
        "llm_scorer_enabled": bool(args.use_llm_scorer),
        "llm_weight": args.llm_weight,
        "analysis_methods": build_analysis_methods_note(),
        "best_vector": best_vector_name,
        "ranking_by_overall_mean": [
            {
                "vector_name": name,
                "overall_mean": payload["aggregate"].get("overall_mean", 0.0),
                "overall_std": payload["aggregate"].get("overall_std", 0.0),
                "bootstrap_ci": payload["bootstrap_ci"],
            }
            for name, payload in ranked
        ],
        "pareto_front_vectors": pareto_vectors,
        "vector_summary": vector_summary,
    }

    out_dir = Path("results/conversation")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"planner_vector_optimization_report_{ts}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # also keep a copy in conversations for consistency
    out_dir2 = Path("results/conversations")
    out_dir2.mkdir(parents=True, exist_ok=True)
    copy_path = out_dir2 / out_path.name
    copy_path.write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(json.dumps({
        "best_vector": best_vector_name,
        "report": str(out_path),
        "report_copy": str(copy_path),
        "vector_count": len(vector_summary),
        "total_runs": len(run_rows),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
