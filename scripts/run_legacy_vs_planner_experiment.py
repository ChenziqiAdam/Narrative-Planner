#!/usr/bin/env python3
"""Run a legacy-vs-planner interview quality experiment.

Default experiment:
    legacy:  5 independent AI interviews, 30 turns each
    planner: 5 independent AI interviews, 30 turns each

Both agents use the same /api/planner/* Flask routes; the only difference is
the "version" field in the start payload ("legacy" vs "graphrag").

Outputs are written under results/legacy-vs-planner/<experiment_id>/.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import inspect
import json
import math
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Config


DEFAULT_ELDER_INFO = {
    "name": "李秀兰",
    "birth_year": 1944,
    "hometown": "四川成都",
    "background": (
        "退休中学语文教师，经历过知青下乡、恢复高考、改革开放后的城市变迁。"
        "她有一个儿子和一个女儿，晚年喜欢整理旧照片和写日记。"
    ),
}

COMMON_SCORE_WEIGHTS = {
    "question_quality": 0.28,
    "information_gain": 0.24,
    "non_redundancy": 0.20,
    "coverage": 0.18,
    "completion": 0.10,
}


def clip01(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


def safe_mean(values: Iterable[float]) -> float:
    vals = [float(v) for v in values]
    return float(statistics.mean(vals)) if vals else 0.0


def safe_variance(values: Iterable[float]) -> float:
    vals = [float(v) for v in values]
    return float(statistics.pvariance(vals)) if len(vals) > 1 else 0.0


def json_safe(obj: Any) -> Any:
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except TypeError:
        if isinstance(obj, dict):
            return {str(k): json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [json_safe(v) for v in obj]
        return str(obj)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_sse_events(raw_text: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in (raw_text or "").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line.split("data:", 1)[1].strip()
        if not payload:
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            event = {"role": "parse_error", "text": payload}
        events.append(event)
    return events


def extract_graph_metrics(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    graph_metrics: List[Dict[str, Any]] = []
    for turn in turns:
        for event in turn.get("events", []):
            if event.get("role") != "interviewer":
                continue
            debug_trace = event.get("debug_trace") or {}
            metrics = debug_trace.get("graph_rag_metrics")
            if isinstance(metrics, dict):
                graph_metrics.append(metrics)

    retrieval_nonempty = []
    ranked_counts = []
    new_entities = 0
    updated_entities = 0
    relationships_written = 0
    context_chars = []
    extraction_events = 0

    for metrics in graph_metrics:
        retrieval = metrics.get("planner_retrieval") or {}
        decision_context = metrics.get("decision_context") or {}
        write = metrics.get("write") or {}
        extraction = metrics.get("extraction") or {}

        if "is_empty" in retrieval:
            retrieval_nonempty.append(0.0 if retrieval.get("is_empty") else 1.0)
        ranked_counts.append(float(retrieval.get("ranked_entity_count", 0) or 0))
        context_chars.append(float(decision_context.get("context_char_count", 0) or 0))
        new_entities += int(write.get("new_entity_count", 0) or 0)
        updated_entities += int(write.get("updated_entity_count", 0) or 0)
        relationships_written += int(write.get("relationship_count", 0) or 0)
        extraction_events += int(extraction.get("event_count", 0) or 0)

    return {
        "turns_with_graph_metrics": len(graph_metrics),
        "retrieval_nonempty_rate": round(safe_mean(retrieval_nonempty), 4),
        "avg_ranked_entities": round(safe_mean(ranked_counts), 4),
        "avg_context_chars": round(safe_mean(context_chars), 2),
        "total_new_entities": new_entities,
        "total_updated_entities": updated_entities,
        "total_relationships_written": relationships_written,
        "total_extracted_events": extraction_events,
    }


def _aggregate_tokens(timing_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    iv_p, iv_c = [], []
    ex_p, ex_c = [], []
    for row in timing_rows:
        tu = row.get("token_usage") or {}
        iv_p.append(int(tu.get("interviewer_prompt_tokens") or 0))
        iv_c.append(int(tu.get("interviewer_completion_tokens") or 0))
        ex_p.append(int(tu.get("extraction_prompt_tokens") or 0))
        ex_c.append(int(tu.get("extraction_completion_tokens") or 0))
    total_p = sum(
        int((row.get("token_usage") or {}).get("total_prompt_tokens")
            or (row.get("token_usage") or {}).get("prompt_tokens") or 0)
        for row in timing_rows
    )
    total_c = sum(
        int((row.get("token_usage") or {}).get("total_completion_tokens")
            or (row.get("token_usage") or {}).get("completion_tokens") or 0)
        for row in timing_rows
    )
    return {
        "total_prompt_tokens": total_p,
        "total_completion_tokens": total_c,
        "total_tokens": total_p + total_c,
        "avg_interviewer_prompt_tokens": round(safe_mean(iv_p), 1),
        "avg_interviewer_completion_tokens": round(safe_mean(iv_c), 1),
        "total_interviewer_prompt_tokens": sum(iv_p),
        "total_interviewer_completion_tokens": sum(iv_c),
        "avg_extraction_prompt_tokens": round(safe_mean(ex_p), 1),
        "avg_extraction_completion_tokens": round(safe_mean(ex_c), 1),
        "total_extraction_prompt_tokens": sum(ex_p),
        "total_extraction_completion_tokens": sum(ex_c),
    }


def extract_common_metrics(
    agent_type: str,
    turns: List[Dict[str, Any]],
    evaluation_state: Dict[str, Any],
    target_turns: int,
) -> Dict[str, Any]:
    turn_evals: List[Dict[str, Any]] = []
    actions: List[str] = []
    interviewer_timing_rows: List[Dict[str, Any]] = []
    interviewee_ms_values: List[float] = []
    error_count = 0

    elapsed_values = [float(t["elapsed_ms"]) for t in turns if t.get("elapsed_ms") is not None]

    for turn in turns:
        for event in turn.get("events", []):
            if event.get("role") == "error":
                error_count += 1
            elif event.get("role") == "interviewee":
                t = event.get("timing") or {}
                if "interviewee_total_ms" in t:
                    interviewee_ms_values.append(float(t["interviewee_total_ms"]))
            if event.get("role") != "interviewer":
                continue
            if isinstance(event.get("turn_evaluation"), dict):
                turn_evals.append(event["turn_evaluation"])
            action = str(event.get("action") or "").strip()
            if action:
                actions.append(action)
            if isinstance(event.get("timing"), dict):
                interviewer_timing_rows.append(event["timing"])
    timing_rows = interviewer_timing_rows

    session_metrics = evaluation_state.get("session_metrics") or {}
    coverage_metrics = evaluation_state.get("coverage_metrics") or {}

    quality_values = [
        clip01(ev.get("question_quality_score"))
        for ev in turn_evals
        if "question_quality_score" in ev
    ]
    info_values = [
        clip01(ev.get("information_gain_score"))
        for ev in turn_evals
        if "information_gain_score" in ev
    ]
    non_redundancy_values = [
        clip01(ev.get("non_redundancy_score"))
        for ev in turn_evals
        if "non_redundancy_score" in ev
    ]
    low_gain_ratio = (
        len([v for v in info_values if v <= 0.08]) / max(1, len(info_values))
    )

    coverage = clip01(
        session_metrics.get(
            "overall_theme_coverage",
            coverage_metrics.get("overall_coverage", coverage_metrics.get("overall_richness", 0.0)),
        )
    )
    if coverage == 0.0:
        coverage = clip01(session_metrics.get("average_coverage_gain", 0.0))

    completed_turns = len([t for t in turns if t.get("status") == "completed"])
    completion_rate = min(1.0, completed_turns / max(1, target_turns))

    return {
        "agent": agent_type,
        "target_turns": target_turns,
        "completed_turns": completed_turns,
        "completion_rate": round(completion_rate, 4),
        "error_count": error_count,
        "avg_question_quality": round(
            safe_mean(quality_values) or clip01(session_metrics.get("average_turn_quality", 0.0)),
            4,
        ),
        "avg_information_gain": round(
            safe_mean(info_values) or clip01(session_metrics.get("average_information_gain", 0.0)),
            4,
        ),
        "avg_non_redundancy": round(safe_mean(non_redundancy_values), 4),
        "low_gain_ratio": round(low_gain_ratio, 4),
        "final_coverage": round(coverage, 4),
        "action_continue_ratio": round(actions.count("continue") / max(1, len(actions)), 4),
        "action_next_phase_ratio": round(actions.count("next_phase") / max(1, len(actions)), 4),
        "action_end_ratio": round(actions.count("end") / max(1, len(actions)), 4),
        "avg_interviewer_ms": round(
            safe_mean(
                float(row.get("interviewer_llm_ms", row.get("retrieval_ms", 0)) or 0)
                for row in timing_rows
            ),
            2,
        ),
        # --- timing: total and per-module averages ---
        "total_elapsed_ms": round(sum(elapsed_values), 2),
        "avg_turn_elapsed_ms": round(safe_mean(elapsed_values), 2),
        "timing": {
            "total_elapsed_ms": round(sum(elapsed_values), 2),
            "avg_turn_elapsed_ms": round(safe_mean(elapsed_values), 2),
            "avg_interviewee_ms": round(safe_mean(interviewee_ms_values), 2),
            "avg_interviewer_llm_ms": round(safe_mean(float(r.get("interviewer_llm_ms") or 0) for r in timing_rows), 2),
            "avg_retrieval_ms": round(safe_mean(float(r.get("retrieval_ms") or 0) for r in timing_rows), 2),
            "avg_extraction_ms": round(safe_mean(float(r.get("extraction_ms") or 0) for r in timing_rows), 2),
            "avg_write_ms": round(safe_mean(float(r.get("write_ms") or 0) for r in timing_rows), 2),
        },
        # --- tokens: total and per-module averages ---
        "tokens": _aggregate_tokens(timing_rows),
        # Legacy uses in-memory graph — no graph_rag_metrics in debug_trace
        "graph_rag": extract_graph_metrics(turns) if agent_type == "graphrag" else {},
    }


def deterministic_score(metrics: Dict[str, Any]) -> Dict[str, Any]:
    completion = clip01(metrics.get("completion_rate"))
    components = {
        "question_quality": clip01(metrics.get("avg_question_quality")),
        "information_gain": clip01(metrics.get("avg_information_gain")),
        "non_redundancy": clip01(metrics.get("avg_non_redundancy")),
        "coverage": clip01(metrics.get("final_coverage")),
        "completion": completion,
    }
    common = sum(components[k] * COMMON_SCORE_WEIGHTS[k] for k in COMMON_SCORE_WEIGHTS)

    graph_observability = None
    if metrics.get("agent") == "graphrag":
        graph = metrics.get("graph_rag") or {}
        graph_observability = clip01(
            0.35 * clip01(graph.get("retrieval_nonempty_rate"))
            + 0.25 * min(1.0, float(graph.get("avg_ranked_entities", 0.0) or 0.0) / 8.0)
            + 0.20 * min(1.0, float(graph.get("total_new_entities", 0.0) or 0.0) / max(1.0, metrics.get("completed_turns", 1)))
            + 0.20 * min(1.0, float(graph.get("total_relationships_written", 0.0) or 0.0) / max(1.0, metrics.get("completed_turns", 1)))
        )

    return {
        "deterministic_score": round(clip01(common), 4),
        "components": {key: round(value, 4) for key, value in components.items()},
        "weights": COMMON_SCORE_WEIGHTS,
        "graph_observability_score": None if graph_observability is None else round(graph_observability, 4),
    }


def build_transcript(history: List[Dict[str, Any]]) -> str:
    lines = []
    for msg in history:
        role = msg.get("role", "")
        label = "访谈者" if role == "interviewer" else "受访者" if role == "interviewee" else role
        lines.append(f"{label}: {msg.get('text', '')}")
    return "\n\n".join(lines).strip()


def score_with_llm(
    transcript: str,
    deterministic_context: Dict[str, Any],
    use_llm: bool,
) -> Optional[Dict[str, Any]]:
    if not use_llm:
        return None
    from src.agents.conversation_scorer_agent import ConversationScorerAgent

    return ConversationScorerAgent().safe_score(
        transcript,
        deterministic_context=deterministic_context,
        max_chars=12000,
    )


def final_score(
    deterministic: Dict[str, Any],
    llm_result: Optional[Dict[str, Any]],
    llm_weight: float,
) -> Dict[str, Any]:
    det = clip01(deterministic.get("deterministic_score"))
    llm_overall = None
    if llm_result and isinstance(llm_result.get("scores"), dict):
        llm_overall = clip01(llm_result["scores"].get("overall"))
    if llm_overall is None:
        overall = det
        actual_llm_weight = 0.0
    else:
        actual_llm_weight = clip01(llm_weight)
        overall = (1.0 - actual_llm_weight) * det + actual_llm_weight * llm_overall
    return {
        "overall_score": round(clip01(overall), 4),
        "deterministic_score": round(det, 4),
        "llm_score": None if llm_overall is None else round(llm_overall, 4),
        "llm_weight": actual_llm_weight,
        "deterministic": deterministic,
        "llm_result": llm_result,
    }


@dataclass
class ExperimentArgs:
    runs_per_agent: int
    legacy_turns: int
    planner_turns: int
    output_dir: Path
    experiment_id: str
    use_llm_scorer: bool
    llm_weight: float
    variance_penalty_weight: float
    model: Optional[str]
    enable_planner_tools: bool
    reset_graph_before_experiment: bool
    continue_on_error: bool
    elder_info: Dict[str, Any]


class LegacyVsPlannerRunner:
    def __init__(self, args: ExperimentArgs):
        self.args = args
        self.experiment_dir = args.output_dir / args.experiment_id
        self.runs_dir = self.experiment_dir / "runs"
        self.charts_dir = self.experiment_dir / "charts"
        self.docs_dir = self.experiment_dir / "docs"
        self.client = None

    def target_turns(self, agent_type: str) -> int:
        return self.args.planner_turns if agent_type == "graphrag" else self.args.legacy_turns

    def configure_runtime(self) -> None:
        if self.args.model:
            for attr in (
                "MODEL_NAME",
                "STRUCTURED_MODEL_NAME",
                "CHAT_MODEL_NAME",
                "INTERVIEWER_MODEL_NAME",
                "BASELINE_MODEL_NAME",
                "INTERVIEWEE_MODEL_NAME",
                "EXTRACTOR_MODEL_NAME",
                "STREAMING_MODEL_NAME",
                "CAMEL_MODEL_NAME",
                "RELATION_LLM_MODEL_NAME",
            ):
                setattr(Config, attr, self.args.model)
        Config.PLANNER_TOOLS_ENABLED = bool(self.args.enable_planner_tools)

    def reset_graph_once(self) -> None:
        if not self.args.reset_graph_before_experiment or not Config.NEO4J_ENABLED:
            return
        try:
            from src.storage.neo4j.manager import Neo4jGraphManager

            manager = Neo4jGraphManager()
            manager.initialize()
            manager.reset_interview_graph(preserve_topics=True)
            manager.sync_themes_to_neo4j()
            manager.close()
        except Exception as exc:
            print(f"[warn] Graph reset skipped: {exc}")

    def initialize_app(self) -> None:
        self.configure_runtime()
        self.reset_graph_once()
        import src.app as app_module

        app_module.app.config["TESTING"] = True
        if hasattr(app_module, "_GRAPH_RESET_ON_PORT_OPEN_DONE"):
            app_module._GRAPH_RESET_ON_PORT_OPEN_DONE = True
        self.app_module = app_module
        self.client = app_module.app.test_client()

    def start_session(self, agent_type: str) -> tuple[str, Dict[str, Any]]:
        # Both legacy and graphrag use /api/planner/start; version differentiates them
        assert self.client is not None
        response = self.client.post(
            "/api/planner/start",
            json={"elder_info": self.args.elder_info, "mode": "ai", "version": agent_type},
        )
        data = response.get_json(silent=True) or {}
        if response.status_code != 200:
            raise RuntimeError(f"planner/{agent_type} start failed: {response.status_code} {data}")
        return str(data["session_id"]), data

    def run_single_turn(self, agent_type: str, session_id: str) -> List[Dict[str, Any]]:
        # Both agents use the same /api/planner/auto endpoint
        assert self.client is not None
        response = self.client.get(f"/api/planner/auto?session_id={session_id}&single_turn=1")
        raw = response.get_data(as_text=True)
        if response.status_code != 200:
            raise RuntimeError(f"planner/{agent_type} auto failed: {response.status_code} {raw[:500]}")
        return parse_sse_events(raw)

    def fetch_json(self, path: str) -> Dict[str, Any]:
        assert self.client is not None
        response = self.client.get(path)
        return response.get_json(silent=True) or {"status_code": response.status_code}

    def run_agent_once(self, agent_type: str, run_index: int) -> Dict[str, Any]:
        run_dir = self.runs_dir / agent_type / f"run_{run_index:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)

        session_id, start_payload = self.start_session(agent_type)
        turns: List[Dict[str, Any]] = []
        status = "completed"
        started_at = datetime.now().isoformat()
        target_turns = self.target_turns(agent_type)
        t_run_start = time.perf_counter()

        for turn_index in range(1, target_turns + 1):
            t0 = time.perf_counter()
            try:
                events = self.run_single_turn(agent_type, session_id)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                error_events = [event for event in events if event.get("role") == "error"]
                turns.append(
                    {
                        "turn_index": turn_index,
                        "status": "error" if error_events else "completed",
                        "elapsed_ms": round(elapsed_ms, 2),
                        "events": events,
                    }
                )
                if error_events:
                    status = "partial"
                    if not self.args.continue_on_error:
                        break
                if any(event.get("role") == "interviewer" and event.get("action") == "end" for event in events):
                    break
            except Exception as exc:
                turns.append(
                    {
                        "turn_index": turn_index,
                        "status": "exception",
                        "error": str(exc),
                        "events": [],
                    }
                )
                status = "partial"
                if not self.args.continue_on_error:
                    break

            if turn_index % 5 == 0:
                run_elapsed_s = time.perf_counter() - t_run_start
                print(f"  [{agent_type}] run {run_index:02d}: {turn_index}/{target_turns} turns  run_elapsed={run_elapsed_s:.1f}s")

        session = self.app_module._compare_sessions.get(session_id, {})
        history = list(session.get("history", []))
        transcript = build_transcript(history)
        evaluation_state = self.fetch_json(f"/api/planner/evaluation/{session_id}")
        # Both agents are planner-class — both support report and graph endpoints
        planner_report = self.fetch_json(f"/api/planner/report/{session_id}")
        graph_state = self.fetch_json(f"/api/planner/graph/{session_id}")

        metrics = extract_common_metrics(agent_type, turns, evaluation_state, target_turns)
        deterministic = deterministic_score(metrics)
        llm_result = score_with_llm(
            transcript,
            deterministic_context={"metrics": metrics, "deterministic": deterministic},
            use_llm=self.args.use_llm_scorer,
        )
        score = final_score(deterministic, llm_result, self.args.llm_weight)

        payload = {
            "agent": agent_type,
            "run_index": run_index,
            "session_id": session_id,
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(),
            "start_payload": start_payload,
            "elder_info": self.args.elder_info,
            "turns": turns,
            "history": history,
            "evaluation_state": evaluation_state,
            "planner_report": planner_report,
            "graph_state": graph_state,
            "metrics": metrics,
            "score": score,
        }

        self.write_run_outputs(run_dir, payload, transcript)
        self.close_session(session)
        return {
            "agent": agent_type,
            "run_index": run_index,
            "session_id": session_id,
            "status": status,
            "run_dir": str(run_dir),
            "metrics": metrics,
            "score": score,
        }

    def close_session(self, session: Dict[str, Any]) -> None:
        agent = session.get("agent")
        for target in (agent, getattr(agent, "async_agent", None)):
            close = getattr(target, "close", None)
            if callable(close):
                try:
                    result = close()
                    if inspect.isawaitable(result):
                        asyncio.run(result)
                except Exception:
                    pass

    def write_run_outputs(self, run_dir: Path, payload: Dict[str, Any], transcript: str) -> None:
        (run_dir / "transcript.md").write_text(transcript + "\n", encoding="utf-8")
        with (run_dir / "turns.jsonl").open("w", encoding="utf-8") as f:
            for turn in payload["turns"]:
                f.write(json.dumps(json_safe(turn), ensure_ascii=False) + "\n")
        write_json(run_dir / "run.json", payload)
        write_json(run_dir / "metrics.json", payload["metrics"])
        write_json(run_dir / "score.json", payload["score"])
        if payload.get("planner_report"):
            write_json(run_dir / "planner_report.json", payload["planner_report"])
        if payload.get("graph_state"):
            write_json(run_dir / "graph_state.json", payload["graph_state"])

    def run(self) -> Dict[str, Any]:
        self.initialize_app()
        total_runs = self.args.runs_per_agent * 2
        print(f"[exp] experiment_id={self.args.experiment_id}  total_runs={total_runs}  legacy_turns={self.args.legacy_turns}  planner_turns={self.args.planner_turns}")
        all_runs: List[Dict[str, Any]] = []
        completed = 0
        for agent_type in ("legacy", "graphrag"):
            for run_index in range(1, self.args.runs_per_agent + 1):
                t_run_start = time.perf_counter()
                print(f"[start] {agent_type} run {run_index:02d}/{self.args.runs_per_agent}  ({completed}/{total_runs} done)")
                result = self.run_agent_once(agent_type, run_index)
                all_runs.append(result)
                completed += 1
                elapsed_s = time.perf_counter() - t_run_start
                print(
                    f"[done]  {agent_type} run {run_index:02d}  "
                    f"status={result['status']}  "
                    f"score={result['score']['overall_score']:.4f}  "
                    f"turns={result['metrics'].get('completed_turns')}  "
                    f"elapsed={elapsed_s:.1f}s  "
                    f"({completed}/{total_runs} done)"
                )

        summary = self.build_summary(all_runs)
        self.write_summary_outputs(all_runs, summary)
        return summary

    def build_summary(self, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_agent: Dict[str, List[Dict[str, Any]]] = {"legacy": [], "graphrag": []}
        for run in runs:
            by_agent.setdefault(run["agent"], []).append(run)

        agents: Dict[str, Any] = {}
        for agent, agent_runs in by_agent.items():
            values = [float(run["score"]["overall_score"]) for run in agent_runs]
            det_values = [float(run["score"]["deterministic_score"]) for run in agent_runs]
            variance = safe_variance(values)
            agents[agent] = {
                "run_count": len(agent_runs),
                "mean_score": round(safe_mean(values), 4),
                "variance": round(variance, 6),
                "std": round(math.sqrt(variance), 4),
                "mean_minus_variance_penalty": round(
                    safe_mean(values) - self.args.variance_penalty_weight * variance,
                    4,
                ),
                "deterministic_mean": round(safe_mean(det_values), 4),
                "avg_completed_turns": round(safe_mean(run["metrics"].get("completed_turns", 0) for run in agent_runs), 2),
                "avg_information_gain": round(safe_mean(run["metrics"].get("avg_information_gain", 0.0) for run in agent_runs), 4),
                "avg_non_redundancy": round(safe_mean(run["metrics"].get("avg_non_redundancy", 0.0) for run in agent_runs), 4),
                "avg_final_coverage": round(safe_mean(run["metrics"].get("final_coverage", 0.0) for run in agent_runs), 4),
                "timing": {
                    "avg_total_elapsed_ms": round(safe_mean((run["metrics"].get("timing") or {}).get("total_elapsed_ms", 0.0) for run in agent_runs), 2),
                    "avg_turn_elapsed_ms": round(safe_mean((run["metrics"].get("timing") or {}).get("avg_turn_elapsed_ms", 0.0) for run in agent_runs), 2),
                    "avg_interviewee_ms": round(safe_mean((run["metrics"].get("timing") or {}).get("avg_interviewee_ms", 0.0) for run in agent_runs), 2),
                    "avg_interviewer_llm_ms": round(safe_mean((run["metrics"].get("timing") or {}).get("avg_interviewer_llm_ms", 0.0) for run in agent_runs), 2),
                    "avg_retrieval_ms": round(safe_mean((run["metrics"].get("timing") or {}).get("avg_retrieval_ms", 0.0) for run in agent_runs), 2),
                    "avg_extraction_ms": round(safe_mean((run["metrics"].get("timing") or {}).get("avg_extraction_ms", 0.0) for run in agent_runs), 2),
                    "avg_write_ms": round(safe_mean((run["metrics"].get("timing") or {}).get("avg_write_ms", 0.0) for run in agent_runs), 2),
                },
                "tokens": {
                    "avg_total_tokens": round(safe_mean((run["metrics"].get("tokens") or {}).get("total_tokens", 0) for run in agent_runs), 1),
                    "avg_total_prompt_tokens": round(safe_mean((run["metrics"].get("tokens") or {}).get("total_prompt_tokens", 0) for run in agent_runs), 1),
                    "avg_total_completion_tokens": round(safe_mean((run["metrics"].get("tokens") or {}).get("total_completion_tokens", 0) for run in agent_runs), 1),
                    "avg_interviewer_prompt_tokens": round(safe_mean((run["metrics"].get("tokens") or {}).get("total_interviewer_prompt_tokens", 0) for run in agent_runs), 1),
                    "avg_interviewer_completion_tokens": round(safe_mean((run["metrics"].get("tokens") or {}).get("total_interviewer_completion_tokens", 0) for run in agent_runs), 1),
                    "avg_extraction_prompt_tokens": round(safe_mean((run["metrics"].get("tokens") or {}).get("total_extraction_prompt_tokens", 0) for run in agent_runs), 1),
                    "avg_extraction_completion_tokens": round(safe_mean((run["metrics"].get("tokens") or {}).get("total_extraction_completion_tokens", 0) for run in agent_runs), 1),
                },
                "runs": [
                    {
                        "run_index": run["run_index"],
                        "session_id": run["session_id"],
                        "status": run["status"],
                        "overall_score": run["score"]["overall_score"],
                        "deterministic_score": run["score"]["deterministic_score"],
                        "llm_score": run["score"].get("llm_score"),
                        "run_dir": run["run_dir"],
                    }
                    for run in agent_runs
                ],
            }

            if agent == "graphrag":
                graph_runs = [run["metrics"].get("graph_rag", {}) for run in agent_runs]
                agents[agent]["graph_rag"] = {
                    "retrieval_nonempty_rate_mean": round(
                        safe_mean(item.get("retrieval_nonempty_rate", 0.0) for item in graph_runs),
                        4,
                    ),
                    "avg_ranked_entities_mean": round(
                        safe_mean(item.get("avg_ranked_entities", 0.0) for item in graph_runs),
                        4,
                    ),
                    "total_new_entities": int(sum(item.get("total_new_entities", 0) for item in graph_runs)),
                    "total_relationships_written": int(sum(item.get("total_relationships_written", 0) for item in graph_runs)),
                }

        winner_by_mean = max(agents, key=lambda key: agents[key]["mean_score"]) if agents else ""
        winner_by_penalty = max(agents, key=lambda key: agents[key]["mean_minus_variance_penalty"]) if agents else ""

        return {
            "experiment_id": self.args.experiment_id,
            "created_at": datetime.now().isoformat(),
            "config": {
                "runs_per_agent": self.args.runs_per_agent,
                "legacy_turns": self.args.legacy_turns,
                "planner_turns": self.args.planner_turns,
                "use_llm_scorer": self.args.use_llm_scorer,
                "llm_weight": self.args.llm_weight,
                "variance_penalty_weight": self.args.variance_penalty_weight,
                "model_override": self.args.model,
                "planner_tools_enabled": self.args.enable_planner_tools,
                "reset_graph_before_experiment": self.args.reset_graph_before_experiment,
                "score_weights": COMMON_SCORE_WEIGHTS,
            },
            "agents": agents,
            "winner_by_mean": winner_by_mean,
            "winner_by_mean_minus_variance_penalty": winner_by_penalty,
        }

    def write_summary_outputs(self, runs: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
        write_json(self.experiment_dir / "summary.json", summary)
        write_json(self.experiment_dir / "experiment_config.json", summary["config"] | {"elder_info": self.args.elder_info})
        self.write_csv(runs)
        self.write_charts(summary)
        self.write_docs(summary)

    def write_csv(self, runs: List[Dict[str, Any]]) -> None:
        path = self.experiment_dir / "summary.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "agent", "run_index", "session_id", "status",
            "overall_score", "deterministic_score", "llm_score",
            "completed_turns", "avg_question_quality", "avg_information_gain",
            "avg_non_redundancy", "final_coverage",
            # timing
            "total_elapsed_ms", "avg_turn_elapsed_ms",
            "avg_interviewee_ms", "avg_interviewer_llm_ms",
            "avg_retrieval_ms", "avg_extraction_ms", "avg_write_ms",
            # tokens — totals
            "total_tokens", "total_prompt_tokens", "total_completion_tokens",
            # tokens — per module averages per turn
            "avg_interviewer_prompt_tokens", "avg_interviewer_completion_tokens",
            "avg_extraction_prompt_tokens", "avg_extraction_completion_tokens",
            # graph
            "graph_retrieval_nonempty_rate", "graph_total_new_entities",
            "graph_total_relationships_written",
            "run_dir",
        ]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for run in runs:
                metrics = run["metrics"]
                graph = metrics.get("graph_rag") or {}
                tm = metrics.get("timing") or {}
                tk = metrics.get("tokens") or {}
                writer.writerow(
                    {
                        "agent": run["agent"],
                        "run_index": run["run_index"],
                        "session_id": run["session_id"],
                        "status": run["status"],
                        "overall_score": run["score"]["overall_score"],
                        "deterministic_score": run["score"]["deterministic_score"],
                        "llm_score": run["score"].get("llm_score"),
                        "completed_turns": metrics.get("completed_turns"),
                        "avg_question_quality": metrics.get("avg_question_quality"),
                        "avg_information_gain": metrics.get("avg_information_gain"),
                        "avg_non_redundancy": metrics.get("avg_non_redundancy"),
                        "final_coverage": metrics.get("final_coverage"),
                        "total_elapsed_ms": tm.get("total_elapsed_ms"),
                        "avg_turn_elapsed_ms": tm.get("avg_turn_elapsed_ms"),
                        "avg_interviewee_ms": tm.get("avg_interviewee_ms"),
                        "avg_interviewer_llm_ms": tm.get("avg_interviewer_llm_ms"),
                        "avg_retrieval_ms": tm.get("avg_retrieval_ms"),
                        "avg_extraction_ms": tm.get("avg_extraction_ms"),
                        "avg_write_ms": tm.get("avg_write_ms"),
                        "total_tokens": tk.get("total_tokens"),
                        "total_prompt_tokens": tk.get("total_prompt_tokens"),
                        "total_completion_tokens": tk.get("total_completion_tokens"),
                        "avg_interviewer_prompt_tokens": tk.get("avg_interviewer_prompt_tokens"),
                        "avg_interviewer_completion_tokens": tk.get("avg_interviewer_completion_tokens"),
                        "avg_extraction_prompt_tokens": tk.get("avg_extraction_prompt_tokens"),
                        "avg_extraction_completion_tokens": tk.get("avg_extraction_completion_tokens"),
                        "graph_retrieval_nonempty_rate": graph.get("retrieval_nonempty_rate"),
                        "graph_total_new_entities": graph.get("total_new_entities"),
                        "graph_total_relationships_written": graph.get("total_relationships_written"),
                        "run_dir": run["run_dir"],
                    }
                )

    def write_charts(self, summary: Dict[str, Any]) -> None:
        agents = summary.get("agents", {})
        mean_values = {agent: data.get("mean_score", 0.0) for agent, data in agents.items()}
        penalty_values = {
            agent: data.get("mean_minus_variance_penalty", 0.0)
            for agent, data in agents.items()
        }
        self.write_bar_svg(
            self.charts_dir / "mean_score.svg",
            "Mean Overall Score",
            mean_values,
            "#7c3aed",
        )
        self.write_bar_svg(
            self.charts_dir / "mean_minus_variance_penalty.svg",
            "Mean - Variance Penalty",
            penalty_values,
            "#0f766e",
        )

    def write_bar_svg(self, path: Path, title: str, values: Dict[str, float], color: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        width, height = 720, 420
        margin_left, margin_bottom = 80, 70
        plot_w, plot_h = width - margin_left - 40, height - 80 - margin_bottom
        max_v = max(1.0, max(values.values(), default=1.0))
        labels = list(values.keys())
        bar_w = plot_w / max(1, len(labels) * 2)
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#ffffff"/>',
            f'<text x="{width/2}" y="38" text-anchor="middle" font-size="22" font-family="Arial" fill="#111827">{title}</text>',
            f'<line x1="{margin_left}" y1="{height-margin_bottom}" x2="{width-40}" y2="{height-margin_bottom}" stroke="#374151"/>',
            f'<line x1="{margin_left}" y1="80" x2="{margin_left}" y2="{height-margin_bottom}" stroke="#374151"/>',
        ]
        for idx, label in enumerate(labels):
            value = float(values[label])
            x = margin_left + (idx * 2 + 0.55) * bar_w
            bar_h = (value / max_v) * plot_h
            y = height - margin_bottom - bar_h
            parts.extend(
                [
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}" rx="3"/>',
                    f'<text x="{x + bar_w/2:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-size="16" font-family="Arial" fill="#111827">{value:.3f}</text>',
                    f'<text x="{x + bar_w/2:.1f}" y="{height - 34}" text-anchor="middle" font-size="16" font-family="Arial" fill="#111827">{label}</text>',
                ]
            )
        for tick in range(0, 6):
            value = max_v * tick / 5
            y = height - margin_bottom - (value / max_v) * plot_h
            parts.append(f'<text x="{margin_left-12}" y="{y+5:.1f}" text-anchor="end" font-size="12" font-family="Arial" fill="#4b5563">{value:.1f}</text>')
            parts.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width-40}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append("</svg>")
        path.write_text("\n".join(parts), encoding="utf-8")

    def write_docs(self, summary: Dict[str, Any]) -> None:
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        methods = f"""# Legacy vs GraphRAG Planner Experiment Methods

## Purpose
This experiment compares the `legacy` planner interviewer (in-memory graph, adaptive routing calibration phases, `src/legacy/`) against the `graphrag` (current) planner interviewer (Neo4j-backed entity retrieval and context injection, `src/orchestration/`) under identical automated interview conditions.

## Key Architectural Difference
Both agents are started via `POST /api/planner/start` — the only difference is the `"version"` field:
- `legacy`: uses `LegacyPlannerInterviewAgentSync`; in-memory graph manager with routing calibration phases; `debug_trace` uses schema `planner_debug_v1` with no `graph_rag_metrics` block
- `graphrag`: uses `PlannerInterviewAgentSync`; Neo4j-backed entity retrieval, ranking, and context injection; `debug_trace` contains `graph_rag_metrics` with `planner_retrieval`, `decision_context`, `write`, and `extraction` sub-sections

## Default Design
- Agents: `legacy` (version="legacy"), `graphrag` (version="graphrag")
- Runs per agent: {self.args.runs_per_agent}
- Legacy turns per run: {self.args.legacy_turns}
- Planner (GraphRAG) turns per run: {self.args.planner_turns}
- Interview mode: AI interviewee through `/api/planner/auto?single_turn=1`
- Graph reset: once before the experiment (Neo4j only), when Neo4j is enabled — legacy uses in-memory graph
- Planner tools enabled: {self.args.enable_planner_tools}
- Model override: `{self.args.model or "use .env"}`

## Per-Run Artifacts
Each run directory contains:
- `transcript.md`: readable full dialogue
- `turns.jsonl`: raw SSE events for each turn
- `run.json`: complete run payload
- `metrics.json`: extracted comparable metrics
- `score.json`: deterministic and optional LLM scorer output
- `planner_report.json`: planner session report (available for both agents)
- `graph_state.json`: graph state snapshot (in-memory for legacy, Neo4j for graphrag)

## Comparable Metrics (both agents)
- completed_turns and completion_rate
- avg_question_quality
- avg_information_gain
- avg_non_redundancy
- low_gain_ratio
- final_coverage
- action_continue_ratio / action_next_phase_ratio / action_end_ratio
- avg_interviewer_ms

GraphRAG planner additionally records:
- retrieval_nonempty_rate
- avg_ranked_entities
- avg_context_chars
- total_new_entities
- total_updated_entities
- total_relationships_written
- total_extracted_events

## Deterministic Score
The common score is identical for both agents — GraphRAG fields are not required:

`score = 0.28*question_quality + 0.24*information_gain + 0.20*non_redundancy + 0.18*coverage + 0.10*completion`

GraphRAG planner additionally reports `graph_observability_score` (not folded into the common score).

## Optional Scoring Agent
When `--use-llm-scorer` is set, `ConversationScorerAgent` scores the transcript on narrative coherence, emotional depth, question effectiveness, non-redundancy, topic coverage quality, and overall quality. Final score becomes:

`overall = (1 - llm_weight) * deterministic_score + llm_weight * llm_overall`

## Stability Penalty

`mean_minus_variance_penalty = mean(overall_score) - variance_penalty_weight * population_variance(overall_score)`
"""
        readme = f"""# Legacy vs GraphRAG Planner Experiment

Experiment ID: `{self.args.experiment_id}`

## Results
- Summary JSON: `../summary.json`
- Summary CSV: `../summary.csv`
- Mean score chart: `../charts/mean_score.svg`
- Mean minus variance penalty chart: `../charts/mean_minus_variance_penalty.svg`

## Current Aggregate
```json
{json.dumps(summary.get("agents", {}), ensure_ascii=False, indent=2)}
```

## Reproduce
```bash
python scripts/run_legacy_vs_planner_experiment.py --runs-per-agent {self.args.runs_per_agent} --legacy-turns {self.args.legacy_turns} --planner-turns {self.args.planner_turns}
```
"""
        (self.docs_dir / "METHODS.md").write_text(methods, encoding="utf-8")
        (self.docs_dir / "README.md").write_text(readme, encoding="utf-8")


def load_elder_info(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return dict(DEFAULT_ELDER_INFO)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("--elder-info-json must point to a JSON object")
    return data


def parse_args() -> ExperimentArgs:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-per-agent", type=int, default=5)
    parser.add_argument(
        "--turns",
        type=int,
        default=None,
        help="Optional shortcut to set both --legacy-turns and --planner-turns.",
    )
    parser.add_argument("--legacy-turns", type=int, default=30)
    parser.add_argument("--planner-turns", type=int, default=30)
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "results" / "legacy-vs-planner"))
    parser.add_argument("--experiment-id", default="")
    parser.add_argument("--elder-info-json", default="")
    parser.add_argument("--use-llm-scorer", action="store_true")
    parser.add_argument("--llm-weight", type=float, default=0.30)
    parser.add_argument("--variance-penalty-weight", type=float, default=1.0)
    parser.add_argument(
        "--model",
        default=os.getenv("COMPARE_EXPERIMENT_MODEL", "moonshot-v1-8k"),
        help="Set all chat/structured roles to one compatible model. Use '' to rely on .env role models.",
    )
    parser.add_argument("--enable-planner-tools", action="store_true")
    parser.add_argument("--no-reset-graph-before-experiment", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    ns = parser.parse_args()

    experiment_id = ns.experiment_id or f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    legacy_turns = ns.turns if ns.turns is not None else ns.legacy_turns
    planner_turns = ns.turns if ns.turns is not None else ns.planner_turns
    return ExperimentArgs(
        runs_per_agent=max(1, ns.runs_per_agent),
        legacy_turns=max(1, int(legacy_turns)),
        planner_turns=max(1, int(planner_turns)),
        output_dir=Path(ns.output_dir),
        experiment_id=experiment_id,
        use_llm_scorer=bool(ns.use_llm_scorer),
        llm_weight=clip01(ns.llm_weight),
        variance_penalty_weight=float(ns.variance_penalty_weight),
        model=(ns.model.strip() or None) if isinstance(ns.model, str) else ns.model,
        enable_planner_tools=bool(ns.enable_planner_tools),
        reset_graph_before_experiment=not bool(ns.no_reset_graph_before_experiment),
        continue_on_error=bool(ns.continue_on_error),
        elder_info=load_elder_info(ns.elder_info_json),
    )


def main() -> None:
    args = parse_args()
    runner = LegacyVsPlannerRunner(args)
    summary = runner.run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[done] results: {runner.experiment_dir}")


if __name__ == "__main__":
    main()
