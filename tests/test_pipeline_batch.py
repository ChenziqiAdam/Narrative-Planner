import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.batch_interview import (
    BatchConfig,
    InterviewRunner,
    compute_aggregate_stats,
    run_batch,
)
from src.pipeline.timing import Timer, TurnTiming


# ── Timer tests ───────────────────────────────────────────────────────────────

def test_timer_elapsed_ms():
    import time
    with Timer() as t:
        time.sleep(0.01)
    assert t.elapsed_ms >= 8.0


def test_timer_raises_before_exit():
    t = Timer()
    with pytest.raises(RuntimeError, match="before context manager exited"):
        _ = t.elapsed_ms


def test_turn_timing_to_dict():
    timing = TurnTiming(interviewee_total_ms=100.0, extraction_ms=50.0)
    d = timing.to_dict()
    assert d == {"interviewee_total_ms": 100.0, "extraction_ms": 50.0}


def test_turn_timing_to_dict_omits_none():
    timing = TurnTiming()
    assert timing.to_dict() == {}


# ── BatchConfig tests ─────────────────────────────────────────────────────────

def test_batch_config_defaults():
    cfg = BatchConfig(profile_path="some.json", interviewer_mode="baseline")
    assert cfg.max_turns == 20
    assert cfg.num_runs == 1
    assert cfg.output_dir == "results/batch"


def test_batch_config_from_yaml(tmp_path):
    yaml_content = (
        "profile_path: src/prompts/roles/elder_profile_1.json\n"
        "interviewer_mode: baseline\n"
        "max_turns: 10\n"
        "num_runs: 3\n"
        "basic_info:\n  name: 测试\n"
    )
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")
    cfg = BatchConfig.from_yaml(str(yaml_file))
    assert cfg.max_turns == 10
    assert cfg.num_runs == 3


# ── Stats tests ───────────────────────────────────────────────────────────────

def test_compute_aggregate_stats():
    rows = [{"interviewee_llm_ms": float(i * 100)} for i in range(1, 101)]
    stats = compute_aggregate_stats(rows, "interviewee_llm_ms")
    assert stats["mean"] == pytest.approx(5050.0)
    assert stats["p95"] == pytest.approx(9550.0, abs=200)


def test_compute_aggregate_stats_empty():
    assert compute_aggregate_stats([], "key") == {}


def test_compute_aggregate_stats_missing_key():
    assert compute_aggregate_stats([{"other": 1.0}], "key") == {}


# ── Stubs ─────────────────────────────────────────────────────────────────────

def _make_config(tmp_path, mode="baseline", runs=2, turns=3):
    return BatchConfig(
        profile_path="src/prompts/roles/elder_profile_1.json",
        interviewer_mode=mode,
        max_turns=turns,
        num_runs=runs,
        output_dir=str(tmp_path),
        basic_info={"name": "测试老人", "age": 80},
    )


def _stub_interviewee():
    agent = MagicMock()
    agent.sys_prompt = "test"
    agent.history = ""
    agent.initialize_conversation = MagicMock()
    agent._load_step_prompt = MagicMock(return_value="prompt")
    agent.step_with_metadata = MagicMock(return_value=('{"reply": "我很好"}', []))
    agent.record_turn = MagicMock()
    agent._create_completion = MagicMock()
    agent.tool_callables = {}
    return agent


def _stub_interviewer():
    agent = MagicMock()
    agent.initialize_conversation = MagicMock()
    agent.get_next_question = MagicMock(return_value="您能讲讲您的童年吗？")
    return agent


# ── Runner tests ──────────────────────────────────────────────────────────────

def test_runner_produces_turn_records(tmp_path):
    cfg = _make_config(tmp_path, turns=3)
    runner = InterviewRunner(cfg)
    with patch("src.pipeline.batch_interview.IntervieweeAgent", return_value=_stub_interviewee()), \
         patch("src.pipeline.batch_interview.BaselineAgent", return_value=_stub_interviewer()):
        result = runner.run_one(run_index=0)
    assert len(result["turns"]) == 3
    for turn in result["turns"]:
        assert "question" in turn and "answer" in turn and "timing" in turn


def test_runner_timing_keys_present(tmp_path):
    cfg = _make_config(tmp_path, turns=2)
    runner = InterviewRunner(cfg)
    with patch("src.pipeline.batch_interview.IntervieweeAgent", return_value=_stub_interviewee()), \
         patch("src.pipeline.batch_interview.BaselineAgent", return_value=_stub_interviewer()):
        result = runner.run_one(run_index=0)
    timing = result["turns"][0]["timing"]
    assert "interviewee_total_ms" in timing
    assert "interviewer_llm_ms" in timing


def test_runner_returns_metadata(tmp_path):
    cfg = _make_config(tmp_path, turns=1)
    runner = InterviewRunner(cfg)
    with patch("src.pipeline.batch_interview.IntervieweeAgent", return_value=_stub_interviewee()), \
         patch("src.pipeline.batch_interview.BaselineAgent", return_value=_stub_interviewer()):
        result = runner.run_one(run_index=0)
    assert result["run_index"] == 0
    assert result["mode"] == "baseline"
    assert result["turn_count"] == 1
    assert "transcript" in result


# ── Batch output tests ────────────────────────────────────────────────────────

def test_run_batch_writes_files(tmp_path):
    cfg = _make_config(tmp_path, runs=2, turns=2)
    with patch("src.pipeline.batch_interview.IntervieweeAgent", return_value=_stub_interviewee()), \
         patch("src.pipeline.batch_interview.BaselineAgent", return_value=_stub_interviewer()):
        run_batch(cfg)
    assert len(list(tmp_path.glob("run_*.jsonl"))) == 2
    summaries = list(tmp_path.glob("summary_*.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert "aggregate" in summary
    assert "interviewee_total_ms" in summary["aggregate"]


def test_run_batch_summary_structure(tmp_path):
    cfg = _make_config(tmp_path, runs=1, turns=1)
    with patch("src.pipeline.batch_interview.IntervieweeAgent", return_value=_stub_interviewee()), \
         patch("src.pipeline.batch_interview.BaselineAgent", return_value=_stub_interviewer()):
        run_batch(cfg)
    summary_file = next(tmp_path.glob("summary_*.json"))
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert "batch_id" in summary
    assert summary["config"]["mode"] == "baseline"
    assert summary["config"]["max_turns"] == 1
    assert summary["total_turns"] == 1


def test_custom_system_prompt_applied(tmp_path):
    cfg = _make_config(tmp_path, turns=1)
    cfg.custom_system_prompt = "你是测试老人。"
    stub = _stub_interviewee()
    with patch("src.pipeline.batch_interview.IntervieweeAgent", return_value=stub), \
         patch("src.pipeline.batch_interview.BaselineAgent", return_value=_stub_interviewer()):
        InterviewRunner(cfg).run_one(run_index=0)
    assert stub.sys_prompt == "你是测试老人。"
