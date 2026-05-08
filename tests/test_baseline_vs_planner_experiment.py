import math

from scripts.run_baseline_vs_planner_experiment import (
    CompareExperimentRunner,
    ExperimentArgs,
    deterministic_score,
    extract_common_metrics,
    extract_graph_metrics,
    parse_sse_events,
)


def test_parse_sse_events_extracts_json_payloads():
    raw = 'data: {"role":"interviewee","text":"答复"}\n\ndata: {"role":"done"}\n\n'

    events = parse_sse_events(raw)

    assert events == [
        {"role": "interviewee", "text": "答复"},
        {"role": "done"},
    ]


def test_extract_graph_metrics_aggregates_planner_trace():
    turns = [
        {
            "events": [
                {
                    "role": "interviewer",
                    "debug_trace": {
                        "graph_rag_metrics": {
                            "planner_retrieval": {
                                "is_empty": False,
                                "ranked_entity_count": 6,
                            },
                            "decision_context": {"context_char_count": 300},
                            "write": {
                                "new_entity_count": 2,
                                "updated_entity_count": 1,
                                "relationship_count": 3,
                            },
                            "extraction": {"event_count": 1},
                        }
                    },
                }
            ]
        }
    ]

    metrics = extract_graph_metrics(turns)

    assert metrics["turns_with_graph_metrics"] == 1
    assert metrics["retrieval_nonempty_rate"] == 1.0
    assert metrics["avg_ranked_entities"] == 6.0
    assert metrics["total_new_entities"] == 2
    assert metrics["total_relationships_written"] == 3


def test_extract_common_metrics_and_score_are_comparable_without_graph_fields():
    turns = [
        {
            "status": "completed",
            "events": [
                {
                    "role": "interviewer",
                    "action": "continue",
                    "turn_evaluation": {
                        "question_quality_score": 0.8,
                        "information_gain_score": 0.6,
                        "non_redundancy_score": 0.9,
                    },
                    "timing": {"interviewer_llm_ms": 123.0},
                }
            ],
        }
    ]
    evaluation_state = {"coverage_metrics": {"overall_coverage": 0.5}}

    metrics = extract_common_metrics("baseline", turns, evaluation_state, target_turns=2)
    score = deterministic_score(metrics)

    assert metrics["completion_rate"] == 0.5
    assert metrics["avg_question_quality"] == 0.8
    assert metrics["graph_rag"] == {}
    assert score["deterministic_score"] == 0.688


def test_summary_uses_mean_minus_population_variance_penalty(tmp_path):
    args = ExperimentArgs(
        runs_per_agent=2,
        turns=1,
        output_dir=tmp_path,
        experiment_id="test",
        use_llm_scorer=False,
        llm_weight=0.3,
        variance_penalty_weight=1.0,
        model=None,
        enable_planner_tools=False,
        reset_graph_before_experiment=False,
        continue_on_error=True,
        elder_info={},
    )
    runner = CompareExperimentRunner(args)
    runs = [
        {
            "agent": "baseline",
            "run_index": 1,
            "session_id": "b1",
            "status": "completed",
            "run_dir": "b1",
            "metrics": {"completed_turns": 1},
            "score": {"overall_score": 0.6, "deterministic_score": 0.6},
        },
        {
            "agent": "baseline",
            "run_index": 2,
            "session_id": "b2",
            "status": "completed",
            "run_dir": "b2",
            "metrics": {"completed_turns": 1},
            "score": {"overall_score": 0.8, "deterministic_score": 0.8},
        },
        {
            "agent": "planner",
            "run_index": 1,
            "session_id": "p1",
            "status": "completed",
            "run_dir": "p1",
            "metrics": {"completed_turns": 1, "graph_rag": {}},
            "score": {"overall_score": 0.7, "deterministic_score": 0.7},
        },
    ]

    summary = runner.build_summary(runs)

    assert summary["agents"]["baseline"]["mean_score"] == 0.7
    assert math.isclose(summary["agents"]["baseline"]["variance"], 0.01)
    assert summary["agents"]["baseline"]["mean_minus_variance_penalty"] == 0.69
