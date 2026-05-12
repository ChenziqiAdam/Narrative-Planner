# Baseline vs Planner Experiment

Experiment ID: `20260508_051612_93e58a`

## Results
- Summary JSON: `../summary.json`
- Summary CSV: `../summary.csv`
- Mean score chart: `../charts/mean_score.svg`
- Mean minus variance penalty chart: `../charts/mean_minus_variance_penalty.svg`

## Current Aggregate
```json
{
  "baseline": {
    "run_count": 10,
    "mean_score": 0.3583,
    "variance": 0.000136,
    "std": 0.0116,
    "mean_minus_variance_penalty": 0.3581,
    "deterministic_mean": 0.3583,
    "avg_completed_turns": 20.0,
    "avg_information_gain": 0.1,
    "avg_non_redundancy": 0.7439,
    "avg_final_coverage": 0.0,
    "runs": [
      {
        "run_index": 1,
        "session_id": "0169da17f10347718c8ef04b8dae034f",
        "status": "completed",
        "overall_score": 0.3437,
        "deterministic_score": 0.3437,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_01"
      },
      {
        "run_index": 2,
        "session_id": "8eaf8486dafe4b8fad9f8e65b3c037a6",
        "status": "completed",
        "overall_score": 0.35,
        "deterministic_score": 0.35,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_02"
      },
      {
        "run_index": 3,
        "session_id": "13dc32187b1b4dc2bbce6aaf21683e14",
        "status": "completed",
        "overall_score": 0.3447,
        "deterministic_score": 0.3447,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_03"
      },
      {
        "run_index": 4,
        "session_id": "80dee841cf6241b5ab7433c701ff78ab",
        "status": "completed",
        "overall_score": 0.3722,
        "deterministic_score": 0.3722,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_04"
      },
      {
        "run_index": 5,
        "session_id": "38206ab5f97d46108068fbdaec82e7a1",
        "status": "completed",
        "overall_score": 0.363,
        "deterministic_score": 0.363,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_05"
      },
      {
        "run_index": 6,
        "session_id": "253fd8b4ebfe4e87b5ab2ae685b4ac10",
        "status": "completed",
        "overall_score": 0.3427,
        "deterministic_score": 0.3427,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_06"
      },
      {
        "run_index": 7,
        "session_id": "37843910453d4c108db7fc73803fa511",
        "status": "completed",
        "overall_score": 0.3701,
        "deterministic_score": 0.3701,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_07"
      },
      {
        "run_index": 8,
        "session_id": "4065a69badc04b6fba8fdff9ab003771",
        "status": "completed",
        "overall_score": 0.3741,
        "deterministic_score": 0.3741,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_08"
      },
      {
        "run_index": 9,
        "session_id": "1db8c066280544c9b47a55715f7b0786",
        "status": "completed",
        "overall_score": 0.3576,
        "deterministic_score": 0.3576,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_09"
      },
      {
        "run_index": 10,
        "session_id": "b54cacabe765453da2af806406910fb4",
        "status": "completed",
        "overall_score": 0.3647,
        "deterministic_score": 0.3647,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/baseline/run_10"
      }
    ]
  },
  "planner": {
    "run_count": 10,
    "mean_score": 0.4731,
    "variance": 0.00053,
    "std": 0.023,
    "mean_minus_variance_penalty": 0.4726,
    "deterministic_mean": 0.4731,
    "avg_completed_turns": 32.7,
    "avg_information_gain": 0.6366,
    "avg_non_redundancy": 0.5864,
    "avg_final_coverage": 0.0,
    "runs": [
      {
        "run_index": 1,
        "session_id": "370807a246fa4462a70708138639560e",
        "status": "partial",
        "overall_score": 0.417,
        "deterministic_score": 0.417,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_01"
      },
      {
        "run_index": 2,
        "session_id": "11cbc9e6dbad429788985a1d54f758ce",
        "status": "partial",
        "overall_score": 0.4858,
        "deterministic_score": 0.4858,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_02"
      },
      {
        "run_index": 3,
        "session_id": "53197f9aa2e04ba2bde89d9892196035",
        "status": "partial",
        "overall_score": 0.4911,
        "deterministic_score": 0.4911,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_03"
      },
      {
        "run_index": 4,
        "session_id": "6530cf15d5fb49a0b866a65e6fe44538",
        "status": "partial",
        "overall_score": 0.4868,
        "deterministic_score": 0.4868,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_04"
      },
      {
        "run_index": 5,
        "session_id": "53612cc6e0fe4a82b71cd300e0ef1426",
        "status": "partial",
        "overall_score": 0.4514,
        "deterministic_score": 0.4514,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_05"
      },
      {
        "run_index": 6,
        "session_id": "41d639d8eb7d4393b73326e2956724f1",
        "status": "partial",
        "overall_score": 0.4781,
        "deterministic_score": 0.4781,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_06"
      },
      {
        "run_index": 7,
        "session_id": "70856a756eb547e9bc7d9edfb3d04d47",
        "status": "partial",
        "overall_score": 0.484,
        "deterministic_score": 0.484,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_07"
      },
      {
        "run_index": 8,
        "session_id": "136cca4e84744d04a20aea6643db172b",
        "status": "partial",
        "overall_score": 0.4937,
        "deterministic_score": 0.4937,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_08"
      },
      {
        "run_index": 9,
        "session_id": "5a4aee0b0bd648c99109cc90d0530f56",
        "status": "partial",
        "overall_score": 0.457,
        "deterministic_score": 0.457,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_09"
      },
      {
        "run_index": 10,
        "session_id": "687bf58175e14afda5160db76829587e",
        "status": "partial",
        "overall_score": 0.4865,
        "deterministic_score": 0.4865,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/20260508_051612_93e58a/runs/planner/run_10"
      }
    ],
    "graph_rag": {
      "retrieval_nonempty_rate_mean": 0.0,
      "avg_ranked_entities_mean": 69.7793,
      "total_new_entities": 699,
      "total_relationships_written": 1060
    }
  }
}
```

## Reproduce
```bash
python scripts/run_baseline_vs_planner_experiment.py --runs-per-agent 10 --baseline-turns 20 --planner-turns 50
```
