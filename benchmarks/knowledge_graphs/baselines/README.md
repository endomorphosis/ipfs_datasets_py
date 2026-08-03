# Knowledge Graph Load Baselines (KGP-030)

Environment-labelled performance baselines and regression gates for the
knowledge-graph load harness (`benchmarks.knowledge_graphs`).

## Principles

1. **No portable absolute SLOs.** Every baseline is bound to an
   `environment_label` (host class, CPU, Python version). Absolute p95 / p99 /
   throughput / recovery / RSS bounds are only meaningful under that label.
2. **Repeated samples.** Ratification requires warmup discard, ≥3 measured
   repetitions, and a recorded variance model (`sample_std`).
3. **Hard correctness gates.** Correctness and security error budgets are
   always **zero**.
4. **Relative release gate.** An *unexplained* regression greater than **10%**
   in p95 latency or throughput blocks release (KGP-G090 / plan §Load).

## Required profiles

| Profile | Plan size | Status |
|---------|-----------|--------|
| `smoke` | 1k nodes / 5k edges | ratified (measured) |
| `corpus_211` | full 211-AI replay hook | ratified (measured) |
| `corpus_cvefixes` | available CVEfixes replay | ratified (measured) |
| `synthetic_large` | 1M nodes / 10M edges | environment_gated (scaled proxy) |
| `concurrent_mixed` | ≥16 graphs mixed R/W/Q | ratified (measured) |

`tiny` is also baselined for CI-mandatory harness correctness.

## Layout

```
baselines/
  catalog.json
  catalog.py / compare.py / methodology.py / ratify.py
  environments/
    <environment_label>/
      environment.json
      profiles/
        smoke.json
        corpus_211.json
        ...
```

## Usage

```python
from benchmarks.knowledge_graphs.baselines import (
    load_baseline,
    load_catalog,
    compare_receipt_to_baseline,
    compare_to_baseline,
    REGRESSION_RATIO_LIMIT,
)

catalog = load_catalog()
assert set(catalog.required_profiles) <= {
    b.profile for b in catalog.baselines
}

baseline = load_baseline("smoke", environment_label="reference-lab-linux")
result = compare_to_baseline(
    baseline,
    candidate_metrics={"p95_ms": 50.0, "ops_per_s": 47.0, ...},
    correctness_errors=0,
    security_errors=0,
    status="success",
)
assert result.passed
```

Compare a live harness receipt:

```python
from benchmarks.knowledge_graphs import run_profile
from benchmarks.knowledge_graphs.baselines import compare_receipt_to_baseline, load_baseline

run = run_profile("tiny", work_dir="/tmp/kg", matrix_mode="storage",
                  surfaces=("python",), storage_profiles=("parquet",))
baseline = load_baseline("tiny", environment_label="reference-lab-linux")
# Relative regression gates; absolute bounds are advisory across hosts.
cmp = compare_receipt_to_baseline(
    run.receipt.to_json_dict(),
    baseline,
    check_bounds=False,  # set True only when environment_label matches
)
assert cmp.passed or cmp.blocking_failures
```

## Re-ratification

1. Run the profile with the harness (warmup + ≥3 repetitions).
2. Extract metrics via `extract_metrics_from_receipt`.
3. Call `ratify_profile_runs(...)` and write under
   `environments/<label>/profiles/<profile>.json`.
4. Rebuild `catalog.json` via `scan_environments()` / `write_json_atomic`.
5. Update `docs/operations/knowledge_graphs_slos.md` if bounds change.

`synthetic_large` full materialization requires dedicated lab hardware; the
checked-in baseline is scaled from multi-sample `smoke` runs and remains
`environment_gated` until full re-ratification.

## Validation

```bash
python -m pytest -q tests/load/knowledge_graphs/test_baseline_comparison.py
```
