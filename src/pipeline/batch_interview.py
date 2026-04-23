# src/pipeline/batch_interview.py
"""
Standalone batch interview pipeline — no Flask required.

Usage:
    conda run -n planner python -m src.pipeline.batch_interview --config configs/batch_interview.yaml
    conda run -n planner python -m src.pipeline.batch_interview \
        --profile src/prompts/roles/elder_profile_1.json \
        --mode baseline --turns 20 --runs 5 --output results/batch/
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = os.path.join(os.path.dirname(__file__), "..", "..")
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import yaml

from src.agents.baseline_agent import BaselineAgent
from src.agents.interviewee_agent import IntervieweeAgent, extract_interviewee_reply
from src.pipeline.timing import Timer, TurnTiming


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class BatchConfig:
    profile_path: str
    interviewer_mode: str = "baseline"   # "baseline" | "planner"
    max_turns: int = 20
    num_runs: int = 1
    output_dir: str = "results/batch"
    basic_info: Dict[str, Any] = field(default_factory=dict)
    custom_system_prompt: Optional[str] = None

    @classmethod
    def from_yaml(cls, path: str) -> "BatchConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "BatchConfig":
        basic_info: Dict[str, Any] = {}
        if args.basic_info:
            try:
                basic_info = json.loads(args.basic_info)
            except json.JSONDecodeError:
                basic_info = {"background": args.basic_info}
        return cls(
            profile_path=args.profile,
            interviewer_mode=args.mode,
            max_turns=args.turns,
            num_runs=args.runs,
            output_dir=args.output,
            basic_info=basic_info,
            custom_system_prompt=args.system_prompt,
        )


# ── Stats ─────────────────────────────────────────────────────────────────────

def compute_aggregate_stats(timing_rows: List[Dict[str, float]], key: str) -> Dict[str, float]:
    values = sorted(v for row in timing_rows if (v := row.get(key)) is not None)
    if not values:
        return {}
    n = len(values)

    def pct(p: float) -> float:
        idx = (p / 100) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return values[lo] * (1 - (idx - lo)) + values[hi] * (idx - lo)

    return {
        "mean": statistics.mean(values),
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "min": values[0],
        "max": values[-1],
        "count": n,
    }


def _timing_keys(mode: str) -> List[str]:
    base = ["interviewee_llm_ms", "interviewee_tool_ms", "interviewee_total_ms", "interviewer_llm_ms"]
    planner = ["extraction_ms", "merge_ms", "graph_ms", "memory_ms", "coverage_ms"]
    return base + (planner if mode == "planner" else [])


# ── Runner ────────────────────────────────────────────────────────────────────

class InterviewRunner:
    def __init__(self, cfg: BatchConfig):
        self.cfg = cfg

    def _build_agents(self):
        interviewee = IntervieweeAgent(profile_path=self.cfg.profile_path)
        interviewee.initialize_conversation(self.cfg.basic_info)
        if self.cfg.custom_system_prompt:
            interviewee.sys_prompt = self.cfg.custom_system_prompt

        if self.cfg.interviewer_mode == "baseline":
            interviewer = BaselineAgent()
            basic_str = (
                self.cfg.basic_info if isinstance(self.cfg.basic_info, str)
                else json.dumps(self.cfg.basic_info, ensure_ascii=False)
            )
            interviewer.initialize_conversation(basic_str)
        else:
            from src.agents.planner_interview_agent import PlannerInterviewAgentSync
            interviewer = PlannerInterviewAgentSync()
            interviewer.initialize_conversation(self.cfg.basic_info)
        return interviewee, interviewer

    def run_one(self, run_index: int) -> Dict[str, Any]:
        interviewee, interviewer = self._build_agents()
        turns: List[Dict[str, Any]] = []
        transcript: List[str] = []

        # Opening question (not timed — part of initialization)
        if self.cfg.interviewer_mode == "baseline":
            last_question = interviewer.get_next_question()
        else:
            res = interviewer.get_next_question()
            last_question = res.get("question", "") if isinstance(res, dict) else res
        transcript.append(f"访谈者: {last_question}")

        for turn_idx in range(self.cfg.max_turns):
            timing = TurnTiming()
            prompt = interviewee._load_step_prompt(interviewee.history, last_question)

            # ── Timed interviewee step ────────────────────────────────────
            llm_ms_parts: List[float] = []
            tool_ms_parts: List[float] = []
            original_create = interviewee._create_completion
            original_tools = interviewee.tool_callables

            def _timed_create(messages, _orig=original_create, _acc=llm_ms_parts):
                with Timer() as t:
                    result = _orig(messages)
                _acc.append(t.elapsed_ms)
                return result

            timed_tools: Dict[str, Any] = {}
            for fn_name, fn in original_tools.items():
                def _make_timed(f=fn, acc=tool_ms_parts):
                    def _w(*args, **kwargs):
                        with Timer() as t:
                            res = f(*args, **kwargs)
                        acc.append(t.elapsed_ms)
                        return res
                    return _w
                timed_tools[fn_name] = _make_timed()

            interviewee._create_completion = _timed_create
            interviewee.tool_callables = timed_tools
            try:
                with Timer() as total_t:
                    raw_answer, tool_calls_log = interviewee.step_with_metadata(prompt)
            finally:
                interviewee._create_completion = original_create
                interviewee.tool_callables = original_tools

            timing.interviewee_total_ms = total_t.elapsed_ms
            timing.interviewee_llm_ms = sum(llm_ms_parts) if llm_ms_parts else 0.0
            timing.interviewee_tool_ms = sum(tool_ms_parts) if tool_ms_parts else 0.0

            answer = extract_interviewee_reply(raw_answer)
            interviewee.record_turn(last_question, answer)
            transcript.append(f"受访者: {answer}")

            # ── Timed interviewer step ────────────────────────────────────
            if self.cfg.interviewer_mode == "baseline":
                with Timer() as iv_t:
                    next_question = interviewer.get_next_question(answer)
                timing.interviewer_llm_ms = iv_t.elapsed_ms
                turn_record: Dict[str, Any] = {
                    "turn_index": turn_idx + 1,
                    "question": last_question,
                    "answer": answer,
                    "timing": timing.to_dict(),
                    "tool_calls": tool_calls_log,
                }
                action = "continue"
            else:
                with Timer() as iv_t:
                    planner_result = interviewer.get_next_question(answer)
                timing.interviewer_llm_ms = iv_t.elapsed_ms
                debug_trace = planner_result.get("debug_trace", {}) if isinstance(planner_result, dict) else {}
                timing.extraction_ms = debug_trace.get("extraction_ms")
                timing.merge_ms = debug_trace.get("merge_ms")
                timing.graph_ms = debug_trace.get("graph_ms")
                timing.memory_ms = debug_trace.get("memory_ms")
                timing.coverage_ms = debug_trace.get("coverage_ms")
                next_question = planner_result.get("question", "") if isinstance(planner_result, dict) else str(planner_result)
                action = planner_result.get("action", "continue") if isinstance(planner_result, dict) else "continue"
                turn_record = {
                    "turn_index": turn_idx + 1,
                    "question": last_question,
                    "answer": answer,
                    "timing": timing.to_dict(),
                    "tool_calls": tool_calls_log,
                    "planner_action": action,
                }

            turns.append(turn_record)
            transcript.append(f"访谈者: {next_question}")

            if action == "end":
                break
            last_question = next_question

        return {
            "run_index": run_index,
            "mode": self.cfg.interviewer_mode,
            "turns": turns,
            "transcript": "\n".join(transcript),
            "turn_count": len(turns),
        }


# ── Batch orchestrator ────────────────────────────────────────────────────────

def run_batch(cfg: BatchConfig) -> None:
    out = Path(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    runner = InterviewRunner(cfg)
    all_timing_rows: List[Dict[str, float]] = []
    run_summaries: List[Dict[str, Any]] = []

    for i in range(cfg.num_runs):
        print(f"[batch] run {i + 1}/{cfg.num_runs} ...", flush=True)
        result = runner.run_one(run_index=i)
        jsonl_path = out / f"run_{i:04d}_{batch_id}.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for turn in result["turns"]:
                f.write(json.dumps(turn, ensure_ascii=False) + "\n")
        for turn in result["turns"]:
            all_timing_rows.append(turn.get("timing", {}))
        run_summaries.append({"run_index": i, "turn_count": result["turn_count"], "file": str(jsonl_path)})
        print(f"  {len(result['turns'])} turns -> {jsonl_path.name}", flush=True)

    keys = _timing_keys(cfg.interviewer_mode)
    aggregate = {k: compute_aggregate_stats(all_timing_rows, k) for k in keys}
    summary = {
        "batch_id": batch_id,
        "config": {"profile_path": cfg.profile_path, "mode": cfg.interviewer_mode,
                   "max_turns": cfg.max_turns, "num_runs": cfg.num_runs},
        "runs": run_summaries,
        "aggregate": aggregate,
        "total_turns": len(all_timing_rows),
    }
    summary_path = out / f"summary_{batch_id}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[batch] summary -> {summary_path}", flush=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Batch interview pipeline")
    p.add_argument("--config", help="YAML config file path")
    p.add_argument("--profile", default="src/prompts/roles/elder_profile_1.json")
    p.add_argument("--mode", choices=["baseline", "planner"], default="baseline")
    p.add_argument("--turns", type=int, default=20)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--output", default="results/batch")
    p.add_argument("--basic-info", dest="basic_info",
                   help='JSON string, e.g. \'{"name": "王大爷"}\'')
    p.add_argument("--system-prompt", dest="system_prompt",
                   help="Override interviewee system prompt")
    args = p.parse_args()
    cfg = BatchConfig.from_yaml(args.config) if args.config else BatchConfig.from_args(args)
    run_batch(cfg)


if __name__ == "__main__":
    main()
