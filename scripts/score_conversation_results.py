#!/usr/bin/env python3
"""Score existing planner results under results/conversation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.conversation_result_scorer import ConversationResultScorer


def main() -> None:
    parser = argparse.ArgumentParser(description="Score existing planner conversation result files")
    parser.add_argument("--dir", default="results/conversation", help="Directory containing planner_*.txt and planner_state_*.json")
    parser.add_argument("--use-llm-scorer", action="store_true", help="Enable LLM holistic scorer")
    parser.add_argument("--llm-weight", type=float, default=0.3)
    args = parser.parse_args()

    base = Path(args.dir)
    if not base.exists():
        raise FileNotFoundError(f"Directory not found: {base}")

    scorer = ConversationResultScorer(use_llm=args.use_llm_scorer, llm_weight=args.llm_weight)

    rows: List[Dict] = []
    for state_file in sorted(base.glob("planner_state_*.json")):
        session_id = state_file.stem.replace("planner_state_", "", 1)
        conv_file = base / f"planner_{session_id}.txt"
        if not conv_file.exists():
            continue
        score = scorer.score_from_files(conv_file, state_file, vector_name=f"session_{session_id}")
        rows.append(
            {
                "session_id": session_id,
                "conversation_file": str(conv_file),
                "state_file": str(state_file),
                "score": score.to_dict(),
            }
        )

    rows.sort(key=lambda x: float(x["score"]["overall_score"]), reverse=True)

    report = {
        "generated_at": datetime.now().isoformat(),
        "directory": str(base),
        "count": len(rows),
        "scores": rows,
    }

    out_path = base / f"conversation_scores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out_path), "count": len(rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
