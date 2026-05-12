import math
from datetime import datetime
from unittest.mock import patch

from src.agents.graph_extraction_agent import GraphExtractionAgent
from src.agents.interviewee_agent import IntervieweeAgent
from src.state import SessionState, TurnRecord
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
        baseline_turns=1,
        planner_turns=1,
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


def test_interviewee_step_prompt_keeps_recent_history_bounded():
    with patch.object(IntervieweeAgent, "_load_sys_prompt", lambda self, basic_info=None: setattr(self, "sys_prompt", "")), \
        patch.object(IntervieweeAgent, "_load_tools", lambda self: None), \
        patch.object(IntervieweeAgent, "_init_client", lambda self: None), \
        patch("src.prompts.roles.elderly_promot.ElderPromptGenerator.load_elder_profile", return_value={}):
        agent = IntervieweeAgent("unused.json")

    agent.initialize_conversation({"name": "测试老人"})
    for idx in range(20):
        agent.record_turn(f"问题{idx}" + "很长" * 40, f"回答{idx}" + "也很长" * 40)

    with patch("src.agents.interviewee_agent.Config.INTERVIEWEE_HISTORY_MAX_TURNS", 3), \
        patch("src.agents.interviewee_agent.Config.INTERVIEWEE_HISTORY_MAX_CHARS", 1200):
        prompt = agent._load_step_prompt(agent.history, "当前问题")

    assert "前面还有 17 轮对话已省略" in prompt
    assert "问题19" in prompt
    assert "问题0" not in prompt
    assert len(prompt) <= 1300


def test_graph_extraction_compact_prompt_records_size_stats():
    agent = GraphExtractionAgent()
    state = SessionState(session_id="s1")
    state.transcript.append(
        TurnRecord(
            turn_id="t0",
            turn_index=1,
            timestamp=datetime.now(),
            interviewer_question="上一轮问题" * 80,
            interviewee_answer="上一轮回答" * 80,
        )
    )
    turn = TurnRecord(
        turn_id="t1",
        turn_index=2,
        timestamp=datetime.now(),
        interviewer_question="当前问题" * 200,
        interviewee_answer="当前回答" * 200,
    )

    with patch("src.agents.graph_extraction_agent.Config.GRAPH_EXTRACTION_COMPACT_PROMPT", True), \
        patch("src.agents.graph_extraction_agent.Config.GRAPH_EXTRACTION_CONTEXT_TURNS", 1), \
        patch("src.agents.graph_extraction_agent.Config.GRAPH_EXTRACTION_MAX_TURN_CHARS", 100), \
        patch("src.agents.graph_extraction_agent.Config.GRAPH_EXTRACTION_MAX_GRAPH_CONTEXT_CHARS", 50):
        prompt = agent._build_prompt(state, turn, graph_context="图谱上下文" * 100)

    assert "叙事图谱提取器" in prompt
    assert agent.last_input_chars["template_chars"] < 3500
    assert agent.last_input_chars["current_question_chars"] <= 303
    assert agent.last_input_chars["current_answer_chars"] <= 303
    assert agent.last_input_chars["graph_context_chars"] <= 53
