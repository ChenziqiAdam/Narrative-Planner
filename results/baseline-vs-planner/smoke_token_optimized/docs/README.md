# Baseline vs Planner Experiment

Experiment ID: `smoke_token_optimized`

## Results
- Summary JSON: `../summary.json`
- Summary CSV: `../summary.csv`
- Mean score chart: `../charts/mean_score.svg`
- Mean minus variance penalty chart: `../charts/mean_minus_variance_penalty.svg`

## Current Aggregate
```json
{
  "baseline": {
    "run_count": 1,
    "mean_score": 0.4346,
    "variance": 0.0,
    "std": 0.0,
    "mean_minus_variance_penalty": 0.4346,
    "deterministic_mean": 0.4346,
    "avg_completed_turns": 1.0,
    "avg_information_gain": 0.1,
    "avg_non_redundancy": 1.0,
    "avg_final_coverage": 0.0,
    "runs": [
      {
        "run_index": 1,
        "session_id": "5b8936b055e1437fa39a4009a8741dd0",
        "status": "completed",
        "overall_score": 0.4346,
        "deterministic_score": 0.4346,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/smoke_token_optimized/runs/baseline/run_01"
      }
    ]
  },
  "planner": {
    "run_count": 1,
    "mean_score": 0.6725,
    "variance": 0.0,
    "std": 0.0,
    "mean_minus_variance_penalty": 0.6725,
    "deterministic_mean": 0.6725,
    "avg_completed_turns": 1.0,
    "avg_information_gain": 0.75,
    "avg_non_redundancy": 1.0,
    "avg_final_coverage": 0.0,
    "runs": [
      {
        "run_index": 1,
        "session_id": "a7b7359172f64f2b8bd67dfaf66692d1",
        "status": "completed",
        "overall_score": 0.6725,
        "deterministic_score": 0.6725,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/smoke_token_optimized/runs/planner/run_01"
      }
    ],
    "graph_rag": {
      "retrieval_nonempty_rate_mean": 0.0,
      "avg_ranked_entities_mean": 7.0,
      "total_new_entities": 5,
      "total_relationships_written": 4
    }
  }
}
```

## Reproduce
```bash
python scripts/run_baseline_vs_planner_experiment.py --runs-per-agent 1 --baseline-turns 1 --planner-turns 1
```
