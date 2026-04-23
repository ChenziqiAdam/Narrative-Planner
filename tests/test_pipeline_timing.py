# tests/test_pipeline_timing.py
import time
import pytest
from src.pipeline.timing import Timer, TurnTiming


def test_timer_measures_elapsed_ms():
    with Timer() as t:
        time.sleep(0.01)
    assert t.elapsed_ms >= 10.0
    assert t.elapsed_ms < 500.0


def test_timer_raises_on_early_access():
    t = Timer()
    with pytest.raises(RuntimeError):
        _ = t.elapsed_ms


def test_turn_timing_to_dict_excludes_none():
    tt = TurnTiming(interviewee_llm_ms=123.4, interviewer_llm_ms=200.0,
                    interviewee_total_ms=300.0)
    d = tt.to_dict()
    assert d["interviewee_llm_ms"] == 123.4
    assert "extraction_ms" not in d


def test_turn_timing_to_dict_includes_planner_fields():
    tt = TurnTiming(interviewee_llm_ms=100.0, interviewer_llm_ms=150.0,
                    interviewee_total_ms=180.0, extraction_ms=50.0,
                    merge_ms=20.0, graph_ms=10.0, memory_ms=5.0, coverage_ms=3.0)
    d = tt.to_dict()
    assert d["extraction_ms"] == 50.0
    assert d["graph_ms"] == 10.0
