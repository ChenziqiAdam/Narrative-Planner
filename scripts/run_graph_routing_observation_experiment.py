from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.interviewee_agent import IntervieweeAgent
from src.config import Config
from src.orchestration.session_orchestrator import SessionOrchestrator


DEFAULT_PROFILE_PATH = PROJECT_ROOT / "src" / "prompts" / "roles" / "elder_profile_example.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results" / "graph-routing-observation"


class ScriptedProfileInterviewee:
    """Deterministic fallback simulator backed by profile memory events."""

    def __init__(self, profile_path: Path):
        self.profile_path = profile_path
        self.profile_data = _load_profile(profile_path)
        self.memory_events = _extract_memory_events(self.profile_data)
        self.turn_index = 0

    def answer(self, question: str) -> tuple[str, List[Dict[str, Any]]]:
        self.turn_index += 1
        if self.turn_index % 9 == 0:
            return "嗯，是的，那时候差不多就是这样。", []
        if self.turn_index % 13 == 0:
            return "这个我有点记不清了，年纪大了，有些细节想不起来。", []

        event = self.memory_events[(self.turn_index - 1) % max(len(self.memory_events), 1)]
        event_name = event.get("event_name") or event.get("description") or "那件事"
        details = event.get("details") or event.get("description") or event.get("typical_dialogue") or ""
        tags = "、".join(event.get("tags") or [])
        answer = f"说起这个，我就想到{event_name}。{details}"
        if tags:
            answer += f" 这事现在想起来，和{tags}都有关系。"
        if self.turn_index % 5 == 0:
            answer += " 回头看，那段经历让我明白做人要踏实，也要顾着家里人。"
        return answer[:420], [{"tool": "scripted_profile_memory", "args": {"turn_index": self.turn_index}, "result": event}]


def _load_profile(profile_path: Path) -> Dict[str, Any]:
    with profile_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _extract_elder_info(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    root = profile_data.get("elder_profile", profile_data)
    basic = root.get("basic_info", {}) or {}
    age = basic.get("age")
    birth_year = basic.get("birth_year")
    if not birth_year and isinstance(age, str):
        import re

        match = re.search(r"(18|19|20)\d{2}", age)
        birth_year = int(match.group(0)) if match else None
    return {
        "name": basic.get("name"),
        "age": age if isinstance(age, int) else None,
        "birth_year": birth_year,
        "hometown": basic.get("hometown"),
        "background": basic.get("life_background_summary") or basic.get("identity_experience"),
        "current_residence": basic.get("current_residence"),
        "identity_experience": basic.get("identity_experience"),
        "speaking_style": (root.get("personality_and_style", {}) or {}).get("speaking_style"),
    }


def _extract_memory_events(profile_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    root = profile_data.get("elder_profile", profile_data)
    events: List[Dict[str, Any]] = []
    for period in (root.get("life_memories_by_period", {}) or {}).values():
        events.extend(period.get("memory_events", []) or [])
    return events or [
        {
            "event_name": "早年生活",
            "description": root.get("basic_info", {}).get("life_background_summary", ""),
            "details": root.get("basic_info", {}).get("life_background_summary", ""),
            "tags": ["profile_summary"],
        }
    ]


def _wait_background(orchestrator: SessionOrchestrator, timeout_seconds: float = 8.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        threads = list(orchestrator._profile_threads.values()) + list(orchestrator._evaluation_threads.values())
        if not threads:
            return
        for thread in threads:
            thread.join(timeout=0.05)


def _profile_snapshot(orchestrator: SessionOrchestrator) -> Dict[str, Any]:
    state = orchestrator._require_state()
    profile = state.dynamic_profile
    if not profile:
        return {}
    return {
        "update_count": profile.update_count,
        "last_updated_turn_id": profile.last_updated_turn_id,
        "last_update_reason": profile.last_update_reason,
        "planner_guidance": list(profile.planner_guidance or []),
        "profile_quality": dict(profile.profile_quality or {}),
    }


def _build_turn_record(
    orchestrator: SessionOrchestrator,
    result: Dict[str, Any],
    answer: str,
    memory_calls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    state = orchestrator._require_state()
    turn = state.transcript[-1]
    debug_trace = turn.debug_trace or {}
    routing = debug_trace.get("routing", {}) or {}
    predicted = routing.get("predicted", {}) or {}
    actual = routing.get("actual", {}) or {}
    return {
        "turn_index": turn.turn_index,
        "turn_id": turn.turn_id,
        "interviewer_question": turn.interviewer_question,
        "interviewee_answer": answer,
        "next_question": result.get("question"),
        "next_action": result.get("action"),
        "response_path": {
            "predicted_route": predicted.get("route"),
            "confidence": predicted.get("confidence"),
            "reasons": predicted.get("reasons", []),
            "llm_used": predicted.get("llm_used"),
            "effective_route": routing.get("effective_route"),
            "observe_only": routing.get("observe_only"),
        },
        "routing_signals": predicted.get("signals", {}),
        "routing_scores": predicted.get("scores", {}),
        "routing_actual": actual,
        "merge_record": debug_trace.get("merge", {}),
        "graphrag": debug_trace.get("graphrag", {}),
        "profile_update_decision": debug_trace.get("profile_update", {}),
        "profile_after_turn": _profile_snapshot(orchestrator),
        "extracted_events": result.get("extracted_events", []),
        "graph_changes": result.get("graph_changes", {}),
        "interviewee_memory_calls": memory_calls,
    }


def _write_outputs(
    output_dir: Path,
    session_id: str,
    payload: Dict[str, Any],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{session_id}.json"
    md_path = output_dir / f"{session_id}.md"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    lines = [
        f"# Graph Routing Observation Experiment: {session_id}",
        "",
        f"- Turns: {payload['summary']['turns']}",
        f"- Profile: {payload['profile_path']}",
        f"- Simulator: {payload['simulator']}",
        f"- Routing observe-only: {payload['config']['TURN_ROUTING_OBSERVE_ONLY']}",
        "",
        "## Routing Metrics",
        "",
        "```json",
        json.dumps(payload["summary"].get("graph_routing_metrics", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Turns",
        "",
    ]
    for turn in payload["turns"]:
        path = turn["response_path"]
        actual = turn["routing_actual"]
        merge = turn["merge_record"]
        profile_update = turn["profile_update_decision"]
        lines.extend(
            [
                f"### Turn {turn['turn_index']}",
                "",
                f"- Predicted route: `{path.get('predicted_route')}` confidence={path.get('confidence')}",
                f"- Effective route: `{path.get('effective_route')}` observe_only={path.get('observe_only')}",
                f"- Actual update value: `{actual.get('actual_update_value')}` high_value={actual.get('high_value_update')} answer_local_high_value={actual.get('answer_local_high_value_update')} safe_skip={actual.get('skip_would_be_safe')} answer_local_safe_skip={actual.get('answer_local_skip_would_be_safe')}",
                f"- Merge: new={len(merge.get('new_event_ids', []) or [])}, updated={len(merge.get('updated_event_ids', []) or [])}, fallback={merge.get('fallback_reasons', [])}",
                f"- Profile update: should_update={profile_update.get('should_update')} reason={profile_update.get('reason')}",
                "",
                f"**Q:** {turn['interviewer_question']}",
                "",
                f"**A:** {turn['interviewee_answer']}",
                "",
                f"**Next:** {turn['next_question']}",
                "",
                "**Merge decisions**",
                "",
                "```json",
                json.dumps(merge.get("decisions", []), ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    with md_path.open("w", encoding="utf-8") as file:
        file.write("\n".join(lines))

    return json_path, md_path


async def run_experiment(args: argparse.Namespace) -> Dict[str, Any]:
    Config.ENABLE_TURN_ROUTING_POLICY = True
    Config.TURN_ROUTING_OBSERVE_ONLY = True
    Config.ENABLE_GRAPH_FAST_PATH = False
    Config.ENABLE_DEFERRED_GRAPH_UPDATE = False
    if args.model:
        Config.CHAT_MODEL_NAME = args.model
        Config.INTERVIEWER_MODEL_NAME = args.model
        Config.INTERVIEWEE_MODEL_NAME = args.model

    profile_path = Path(args.profile_path).resolve()
    profile_data = _load_profile(profile_path)
    elder_info = _extract_elder_info(profile_data)
    session_id = args.session_id or f"graph_routing_{uuid.uuid4().hex[:8]}"

    orchestrator = SessionOrchestrator(session_id=session_id, mode="planner")
    orchestrator.initialize_session(elder_info)

    scripted = ScriptedProfileInterviewee(profile_path)
    llm_interviewee = None
    if args.simulator == "llm":
        llm_interviewee = IntervieweeAgent(profile_path=str(profile_path))
        llm_interviewee.initialize_conversation(elder_info)

    turns: List[Dict[str, Any]] = []
    simulator_used = args.simulator
    try:
        for _ in range(args.turns):
            question = orchestrator.get_pending_question_result()["question"]
            memory_calls: List[Dict[str, Any]]
            if llm_interviewee is not None:
                try:
                    prompt = llm_interviewee._load_step_prompt(llm_interviewee.history, question)
                    answer, memory_calls = llm_interviewee.step_with_metadata(prompt)
                    llm_interviewee.record_turn(question, answer)
                except Exception as exc:
                    if not args.fallback_scripted:
                        raise
                    simulator_used = "llm_with_scripted_fallback"
                    answer, memory_calls = scripted.answer(question)
                    memory_calls.append({"tool": "llm_interviewee_error", "args": {}, "result": str(exc)})
            else:
                answer, memory_calls = scripted.answer(question)

            result = await orchestrator.process_user_response(answer)
            _wait_background(orchestrator)
            turns.append(_build_turn_record(orchestrator, result, answer, memory_calls))
    finally:
        await orchestrator.close()

    evaluation_state = orchestrator.get_evaluation_state()
    payload = {
        "session_id": session_id,
        "profile_path": str(profile_path),
        "simulator": simulator_used,
        "config": {
            "ENABLE_TURN_ROUTING_POLICY": Config.ENABLE_TURN_ROUTING_POLICY,
            "TURN_ROUTING_OBSERVE_ONLY": Config.TURN_ROUTING_OBSERVE_ONLY,
            "ENABLE_GRAPH_FAST_PATH": Config.ENABLE_GRAPH_FAST_PATH,
            "ENABLE_DEFERRED_GRAPH_UPDATE": Config.ENABLE_DEFERRED_GRAPH_UPDATE,
        },
        "elder_info": elder_info,
        "summary": {
            "turns": len(turns),
            "graph_routing_metrics": evaluation_state.get("graph_routing_metrics", {}),
            "graphrag_metrics": evaluation_state.get("graphrag_metrics", {}),
            "dynamic_profile_metrics": evaluation_state.get("dynamic_profile_metrics", {}),
            "planner_decision_metrics": evaluation_state.get("planner_decision_metrics", {}),
            "session_metrics": evaluation_state.get("session_metrics", {}),
        },
        "turns": turns,
        "final_dynamic_profile": evaluation_state.get("dynamic_profile", {}),
    }
    json_path, md_path = _write_outputs(Path(args.output_dir), session_id, payload)
    payload["output_files"] = {"json": str(json_path), "markdown": str(md_path)}
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a graph routing observe-only interview experiment.")
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--profile-path", default=str(DEFAULT_PROFILE_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--session-id", default="")
    parser.add_argument("--simulator", choices=["llm", "scripted"], default="llm")
    parser.add_argument("--fallback-scripted", action="store_true", default=True)
    parser.add_argument("--model", default="", help="Optional model override for interviewer/interviewee.")
    return parser.parse_args()


def main() -> None:
    payload = asyncio.run(run_experiment(parse_args()))
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["output_files"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
