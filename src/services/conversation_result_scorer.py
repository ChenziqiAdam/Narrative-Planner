from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Optional

from src.agents.conversation_scorer_agent import ConversationScorerAgent


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _safe_mean(values: Iterable[float]) -> float:
    vals = [float(v) for v in values]
    if not vals:
        return 0.0
    return float(mean(vals))


@dataclass
class ScoreResult:
    overall_score: float
    deterministic_score: float
    llm_score: Optional[float]
    deterministic_breakdown: Dict[str, float]
    llm_breakdown: Dict[str, float]
    analysis_notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 4),
            "deterministic_score": round(self.deterministic_score, 4),
            "llm_score": None if self.llm_score is None else round(self.llm_score, 4),
            "deterministic_breakdown": {k: round(v, 4) for k, v in self.deterministic_breakdown.items()},
            "llm_breakdown": {k: round(v, 4) for k, v in self.llm_breakdown.items()},
            "analysis_notes": list(self.analysis_notes),
        }


class ConversationResultScorer:
    """
    Scores planner conversation results saved under results/conversation(s).

    Hybrid score:
    - Deterministic (state metrics + action behavior): 0.7
    - LLM holistic score (optional): 0.3
    """

    def __init__(self, use_llm: bool = True, llm_weight: float = 0.3):
        self.use_llm = use_llm
        self.llm_weight = _clip01(llm_weight)
        self.det_weight = 1.0 - self.llm_weight
        self.llm_agent = ConversationScorerAgent() if use_llm else None

    def score_from_files(
        self,
        conversation_txt_path: str | Path,
        planner_state_json_path: str | Path,
        vector_name: str = "",
        vector: Optional[List[float]] = None,
    ) -> ScoreResult:
        conv_path = Path(conversation_txt_path)
        state_path = Path(planner_state_json_path)

        transcript_text = conv_path.read_text(encoding="utf-8") if conv_path.exists() else ""
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

        deterministic, breakdown, notes = self._score_deterministic(state)

        llm_breakdown: Dict[str, float] = {}
        llm_overall: Optional[float] = None

        if self.llm_agent:
            context = {
                "vector_name": vector_name,
                "vector": vector or [],
                "deterministic_score": round(deterministic, 4),
                "deterministic_breakdown": {k: round(v, 4) for k, v in breakdown.items()},
                "turn_count": len(state.get("transcript", []) or []),
                "session_metrics": state.get("session_metrics", {}),
            }
            llm_result = self.llm_agent.safe_score(transcript_text, deterministic_context=context)
            if llm_result:
                llm_breakdown = {
                    key: _clip01(float(value))
                    for key, value in (llm_result.get("scores", {}) or {}).items()
                }
                llm_overall = llm_breakdown.get("overall", _safe_mean(llm_breakdown.values()))
                summary = str(llm_result.get("summary", "")).strip()
                if summary:
                    notes.append(f"LLM summary: {summary}")

        if llm_overall is None:
            overall = deterministic
        else:
            overall = self.det_weight * deterministic + self.llm_weight * llm_overall

        return ScoreResult(
            overall_score=_clip01(overall),
            deterministic_score=_clip01(deterministic),
            llm_score=None if llm_overall is None else _clip01(llm_overall),
            deterministic_breakdown=breakdown,
            llm_breakdown=llm_breakdown,
            analysis_notes=notes,
        )

    def _score_deterministic(self, state: Dict[str, Any]) -> tuple[float, Dict[str, float], List[str]]:
        session_metrics = state.get("session_metrics", {}) or {}
        transcript = list(state.get("transcript", []) or [])
        evaluation_trace = list(state.get("evaluation_trace", []) or [])

        overall_theme_coverage = _clip01(float(session_metrics.get("overall_theme_coverage", 0.0) or 0.0))
        people_coverage = _clip01(float(session_metrics.get("people_coverage", 0.0) or 0.0))
        avg_turn_quality = _clip01(float(session_metrics.get("average_turn_quality", 0.0) or 0.0))
        avg_info_gain = _clip01(float(session_metrics.get("average_information_gain", 0.0) or 0.0))

        slot_coverage_map = session_metrics.get("overall_slot_coverage", {}) or {}
        slot_coverage = _clip01(_safe_mean(float(v) for v in slot_coverage_map.values()))

        non_redundancy_values = []
        low_gain_hits = 0
        for ev in evaluation_trace:
            if not isinstance(ev, dict):
                continue
            non_redundancy_values.append(float(ev.get("non_redundancy_score", 0.0) or 0.0))
            if float(ev.get("information_gain_score", 0.0) or 0.0) <= 0.08:
                low_gain_hits += 1

        non_redundancy = _clip01(_safe_mean(non_redundancy_values))
        low_gain_ratio = low_gain_hits / max(1, len(evaluation_trace))

        action_list: List[str] = []
        for turn in transcript:
            if not isinstance(turn, dict):
                continue
            planning = ((turn.get("debug_trace") or {}).get("planning") or {})
            action = str(planning.get("next_action", "")).strip()
            if action:
                action_list.append(action)

        continue_ratio = action_list.count("continue") / max(1, len(action_list))
        next_phase_ratio = action_list.count("next_phase") / max(1, len(action_list))
        end_ratio = action_list.count("end") / max(1, len(action_list))

        # Encourage balanced progression: mostly continue, some phase switches, very little early end.
        action_balance = _clip01(
            1.0
            - abs(continue_ratio - 0.70) * 0.7
            - abs(next_phase_ratio - 0.25) * 0.8
            - end_ratio * 1.2
        )

        information_effectiveness = _clip01(
            0.5 * avg_turn_quality
            + 0.3 * avg_info_gain
            + 0.2 * non_redundancy
        )

        structure_coverage = _clip01(
            0.4 * overall_theme_coverage
            + 0.3 * slot_coverage
            + 0.2 * people_coverage
            + 0.1 * _clip01(float(session_metrics.get("open_loop_closure_rate", 0.0) or 0.0))
        )

        efficiency = _clip01(1.0 - low_gain_ratio)

        deterministic = _clip01(
            0.4 * information_effectiveness
            + 0.35 * structure_coverage
            + 0.15 * action_balance
            + 0.10 * efficiency
        )

        notes = [
            f"turns={len(transcript)}",
            f"low_gain_ratio={low_gain_ratio:.3f}",
            f"action_mix=continue:{continue_ratio:.3f},next_phase:{next_phase_ratio:.3f},end:{end_ratio:.3f}",
        ]

        breakdown = {
            "information_effectiveness": information_effectiveness,
            "structure_coverage": structure_coverage,
            "action_balance": action_balance,
            "efficiency": efficiency,
            "overall_theme_coverage": overall_theme_coverage,
            "slot_coverage": slot_coverage,
            "people_coverage": people_coverage,
            "avg_turn_quality": avg_turn_quality,
            "avg_info_gain": avg_info_gain,
            "non_redundancy": non_redundancy,
            "low_gain_ratio": low_gain_ratio,
        }
        return deterministic, breakdown, notes


def aggregate_vector_scores(vector_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not vector_runs:
        return {}

    overall_values = [float(run["score"]["overall_score"]) for run in vector_runs]
    deterministic_values = [float(run["score"]["deterministic_score"]) for run in vector_runs]
    llm_values = [
        float(run["score"]["llm_score"])
        for run in vector_runs
        if run["score"].get("llm_score") is not None
    ]

    return {
        "run_count": len(vector_runs),
        "overall_mean": round(_safe_mean(overall_values), 4),
        "overall_std": round(float(pstdev(overall_values)) if len(overall_values) > 1 else 0.0, 4),
        "deterministic_mean": round(_safe_mean(deterministic_values), 4),
        "llm_mean": round(_safe_mean(llm_values), 4) if llm_values else None,
        "overall_min": round(min(overall_values), 4),
        "overall_max": round(max(overall_values), 4),
    }


def bootstrap_ci(values: List[float], rounds: int = 1000, alpha: float = 0.05) -> Dict[str, float]:
    import random

    if not values:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    if len(values) == 1:
        v = float(values[0])
        return {"mean": v, "ci_low": v, "ci_high": v}

    means: List[float] = []
    n = len(values)
    for _ in range(max(100, rounds)):
        sample = [values[random.randrange(n)] for _ in range(n)]
        means.append(_safe_mean(sample))

    means.sort()
    low_index = int((alpha / 2.0) * len(means))
    high_index = int((1.0 - alpha / 2.0) * len(means)) - 1
    low_index = max(0, min(low_index, len(means) - 1))
    high_index = max(0, min(high_index, len(means) - 1))

    return {
        "mean": round(_safe_mean(values), 4),
        "ci_low": round(float(means[low_index]), 4),
        "ci_high": round(float(means[high_index]), 4),
    }


def pareto_front(records: List[Dict[str, Any]], objectives: List[str]) -> List[str]:
    """
    Return vector names on Pareto front (maximize all objectives).
    Each record should contain:
      {"vector_name": str, "metrics": {obj: value}}
    """
    front: List[str] = []
    for i, rec_i in enumerate(records):
        name_i = str(rec_i["vector_name"])
        metrics_i = rec_i.get("metrics", {}) or {}

        dominated = False
        for j, rec_j in enumerate(records):
            if i == j:
                continue
            metrics_j = rec_j.get("metrics", {}) or {}
            no_worse = all(float(metrics_j.get(obj, 0.0)) >= float(metrics_i.get(obj, 0.0)) for obj in objectives)
            strictly_better = any(float(metrics_j.get(obj, 0.0)) > float(metrics_i.get(obj, 0.0)) for obj in objectives)
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(name_i)
    return sorted(set(front))
