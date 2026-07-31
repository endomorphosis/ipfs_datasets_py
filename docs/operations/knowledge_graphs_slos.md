# Knowledge Graphs — SLOs and Release Gates

**Status:** ratified (environment-labelled)  
**Task:** `KGP-030`  
**Goal:** `KGP-G090`  
**Harness:** `benchmarks/knowledge_graphs`  
**Baselines:** `benchmarks/knowledge_graphs/baselines`  
**Comparison:** `benchmarks.knowledge_graphs.baselines.compare`

## Purpose

This document ratifies service-level objectives and release gates for
knowledge-graph load behaviour. It does **not** claim portable absolute
latency or throughput numbers. Every absolute bound is bound to an
`environment_label` and multi-sample methodology (warmup, repetitions,
variance). Relative regression gates and zero-error correctness/security
gates apply to every environment.

## Non-negotiable gates

| Gate | Limit | Blocking |
|------|-------|----------|
| Correctness errors | **0** | Yes |
| Security errors (unauthorized read/write, cross-tenant leak, silent data loss, partial committed revision) | **0** | Yes |
| Unexplained p95 latency regression vs labelled baseline | **≤ 10%** | Yes |
| Unexplained throughput (`ops_per_s`) regression vs labelled baseline | **≤ 10%** | Yes |
| Run status | `success` | Yes |
| Golden / differential correctness (corpus suite) | pass | Yes (via KGP-028) |

“Unexplained” means no explicit, recorded explanation was attached to the
comparison for that metric. Documented environment changes (hardware class,
Python major version, storage backend swap) require **re-ratification**, not
a silent waiver.

Resource and recovery bounds declared on a labelled baseline are also
blocking when the candidate run shares that environment label
(`check_bounds=True`).

## Methodology (required for ratification)

Every labelled baseline records:

| Field | Requirement |
|-------|-------------|
| `environment_label` | Non-empty; identifies host class (OS, arch, Python) |
| `warmup_runs` | ≥ 1 discarded process-level warm-up run |
| `warmup_operations` | Profile-level op warm-ups (harness `warmup_operations`) |
| `repetitions` | ≥ 3 measured repetitions after warm-up |
| `variance_model` | `sample_std` (sample standard deviation) |
| `matrix_mode` / surfaces / storage | Exactly what was measured |
| Metric summaries | `median`, `mean`, `stdev`, `n`, `samples`, `bound`, `direction` |

Bound policy (default):

- **Lower-is-better** (p95, p99, recovery, RSS, FDs):  
  `bound = median + max(3·σ, 0.25·median, unit_floor)`
- **Higher-is-better** (throughput):  
  `bound = max(0, median − max(3·σ, 0.25·median))`

## Required baseline profiles

Per production hardening plan load suite:

| Profile | Shape / scope | Ratification |
|---------|---------------|--------------|
| `smoke` | 1 000 nodes / 5 000 edges | Multi-sample measurement |
| `corpus_211` | Full 211-AI corpus replay hook | Multi-sample measurement |
| `corpus_cvefixes` | Available CVEfixes corpus replay | Multi-sample measurement |
| `synthetic_large` | 1 000 000 nodes / 10 000 000 edges | Environment-gated scaled proxy until full lab re-ratification |
| `concurrent_mixed` | ≥ 16 graph IDs, mixed read/write/query | Multi-sample measurement |

Optional: `tiny` (CI-mandatory harness correctness).

Artifacts live under:

```text
benchmarks/knowledge_graphs/baselines/environments/<environment_label>/profiles/<profile>.json
```

Catalog index: `benchmarks/knowledge_graphs/baselines/catalog.json`.

## Reference-lab labelled bounds

**Environment label:** `reference-lab-linux`  
**Source measurement label:** `ci-linux-aarch64-py3.12`  
**Methodology:** 1 warm-up run discarded + 3 measured repetitions; harness
internal `warmup_operations` per profile; `matrix_mode=storage`, surface
`python`, profile storage set; variance `sample_std`.

> Absolute numbers below are **not portable**. Re-ratify on any new host
> class before enforcing absolute bounds. Relative 10% gates and zero-error
> gates always apply.

### smoke (1k / 5k)

| Metric | Median | Bound (ceiling/floor) | Direction |
|--------|--------|------------------------|-----------|
| p95_ms | ~48.5 | median + max(3σ, 25%) | lower is better |
| p99_ms | ~51.9 | same policy | lower is better |
| ops_per_s | ~48.5 | median − max(3σ, 25%) | higher is better |
| recovery_ms_mean | ~18.3 | ceiling policy | lower is better |
| max_rss_bytes | ~42.9 MiB | ceiling policy | lower is better |

### corpus_211 (211-AI replay hook)

| Metric | Median | Direction |
|--------|--------|-----------|
| p95_ms | ~18.9 | lower is better |
| ops_per_s | ~117 | higher is better |
| recovery_ms_mean | ~5.5 | lower is better |

### corpus_cvefixes (available CVEfixes)

| Metric | Median | Direction |
|--------|--------|-----------|
| p95_ms | ~26.6 | lower is better |
| ops_per_s | ~81.5 | higher is better |
| recovery_ms_mean | ~7.6 | lower is better |

### concurrent_mixed (≥16 graphs)

| Metric | Median | Direction |
|--------|--------|-----------|
| p95_ms | ~19.3 | lower is better |
| ops_per_s | ~452 | higher is better |
| recovery_ms_mean | ~12.7 | lower is better |
| graph_count | 16 | configuration |

### synthetic_large (1M / 10M)

Status: **`environment_gated`**. Full graph materialization of 1M nodes /
10M edges is not executed in default CI. The checked-in baseline is scaled
from multi-sample `smoke` measurements on the same host class and must be
**re-ratified with repeated full runs** on dedicated lab hardware before
absolute SLOs bind. Until then:

- Relative p95 / throughput 10% gates apply when candidate receipts are
  compared against the labelled baseline.
- Correctness / security error budgets remain **zero**.
- Operators must set `re_ratify_on_lab_hardware=true` methodology notes when
  promoting to `status=ratified`.

Exact numeric summaries are in
`environments/reference-lab-linux/profiles/synthetic_large.json`.

## Comparison API

```python
from benchmarks.knowledge_graphs.baselines import (
    load_baseline,
    compare_to_baseline,
    compare_receipt_to_baseline,
    REGRESSION_RATIO_LIMIT,
)

assert REGRESSION_RATIO_LIMIT == 0.10

baseline = load_baseline("smoke", environment_label="reference-lab-linux")
result = compare_to_baseline(
    baseline,
    candidate_metrics={
        "p95_ms": 50.0,
        "ops_per_s": 47.0,
        "p99_ms": 55.0,
        "recovery_ms_mean": 20.0,
        "max_rss_bytes": 50_000_000,
    },
    correctness_errors=0,
    security_errors=0,
    status="success",
    # explanations={"p95_ms": "expected after storage backend swap; re-ratifying"},
)
if not result.passed:
    for gate in result.blocking_failures:
        print(gate.name, gate.detail)
```

Receipt path:

```python
result = compare_receipt_to_baseline(receipt_dict, baseline, check_bounds=True)
```

## How to re-ratify on a new environment

1. Label the environment:  
   `{ci|dev|lab}-{system}-{machine}-py{major}.{minor}`  
   (example: `lab-linux-x86_64-py3.12`).
2. For each required profile, run the harness:
   - 1 warm-up full run (discard)
   - ≥3 measured runs
   - Prefer `matrix_mode=storage`, surface `python`, profile storage set
3. Aggregate with `ratify_profile_runs` / `aggregate_samples`.
4. Write  
   `benchmarks/knowledge_graphs/baselines/environments/<label>/profiles/<profile>.json`.
5. Refresh `catalog.json`.
6. Update the tables in this document for the new label.
7. Run:

```bash
python -m pytest -q tests/load/knowledge_graphs/test_baseline_comparison.py
```

## Operational alerts (guidance)

| Condition | Severity | Response |
|-----------|----------|----------|
| correctness_errors > 0 | critical | Block release; open incident; do not waive |
| security_errors > 0 | critical | Block release; security review |
| p95 regression > 10% unexplained | high | Block release; profile & explain or re-ratify |
| throughput regression > 10% unexplained | high | Block release; profile & explain or re-ratify |
| recovery_ms_mean above labelled bound | high | Investigate reopen/query path |
| RSS / FD growth vs bound | medium | Check for leaks (see KGP-031 soak) |

Telemetry series (from KGP-032 operations package) that support these gates:

- `kg_ops_operation_duration_ms` (histogram → p95/p99)
- `kg_ops_operations_total{status}`
- Process RSS / open FDs from load receipts (`resources.*`)

## Related documents

- Plan: `docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md` (Load and longevity)
- Runbook: `docs/operations/knowledge_graphs_runbook.md`
- Harness: `benchmarks/knowledge_graphs/README.md`
- Baseline package: `benchmarks/knowledge_graphs/baselines/README.md`
