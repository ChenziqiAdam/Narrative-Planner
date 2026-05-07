# Baseline vs Planner Experiment

Experiment ID: `smoke_codex_fixed`

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
        "session_id": "9c54aa49fec545d1b4ee180a56639c75",
        "status": "completed",
        "overall_score": 0.4346,
        "deterministic_score": 0.4346,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/smoke_codex_fixed/runs/baseline/run_01"
      }
    ]
  },
  "planner": {
    "run_count": 1,
    "mean_score": 0.7274,
    "variance": 0.0,
    "std": 0.0,
    "mean_minus_variance_penalty": 0.7274,
    "deterministic_mean": 0.7274,
    "avg_completed_turns": 1.0,
    "avg_information_gain": 0.9,
    "avg_non_redundancy": 1.0,
    "avg_final_coverage": 0.0,
    "runs": [
      {
        "run_index": 1,
        "session_id": "aac1a802a6954cfdac2213c300834d4f",
        "status": "completed",
        "overall_score": 0.7274,
        "deterministic_score": 0.7274,
        "llm_score": null,
        "run_dir": "/Users/oier/Downloads/Narrative-Planner/results/baseline-vs-planner/smoke_codex_fixed/runs/planner/run_01"
      }
    ],
    "graph_rag": {
      "retrieval_nonempty_rate_mean": 0.0,
      "avg_ranked_entities_mean": 8.0,
      "total_new_entities": 6,
      "total_relationships_written": 5
    }
  }
}
```

## Reproduce
```bash
python scripts/run_baseline_vs_planner_experiment.py --runs-per-agent 1 --turns 1
```
