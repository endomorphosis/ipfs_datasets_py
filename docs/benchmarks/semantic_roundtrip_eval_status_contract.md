# Semantic round-trip evaluation status contract

Interface: `SemanticRoundTripEvaluationStatus@1`  
Schema: `ipfs-datasets.semantic-roundtrip-evaluation-status.v1`  
Implementation: `benchmarks/semantic_roundtrip/evaluation_status.py`  
Tests: `tests/unit/benchmarks/semantic_roundtrip/test_evaluation_status.py`

## Problem

The 2026-07-27 replacement matrix completed 670/670 scheduled coordinates, but
most optional methods were **not fairly measured**:

| Raw failure reason | Coordinates | What actually happened |
|---|---:|---|
| `post_schedule_capability_unavailable` | 260 | All guided / autoencoder arms were `terminal_unsupported` (no reviewed causal L1 adapter) and sealed with loss `1.0` |
| `retry_exhausted` | 210 | Mostly Leanstral routes exhausted the preregistered recovery budget |
| _(success)_ | 200 | Real artifacts with selection gates evaluated |

Treating unsupported guided arms as semantic loss `1.0` polluted leaderboards
and "beats baseline" paired comparisons. This contract separates measurement
disposition from raw component failure tokens so rankings only use fairly
scored coordinates.

## Disjoint statuses

Every coordinate classifies into **exactly one** of:

### `not_measured`

The arm was never fairly measured. Sub-reasons:

| Reason | When |
|---|---|
| `terminal_unsupported` | Qualification is `terminal_unsupported`, or the historical failure token is `post_schedule_capability_unavailable` (guided path without a reviewed causal adapter) |
| `preflight_blocked` | Required launch preflight is missing or failed (live smoke / causal qualification) |

`not_measured` coordinates:

- must **not** appear on the default leaderboard;
- must **not** enter default paired baseline deltas as candidates;
- must **not** be described as semantic loss `1.0` defeats of the baseline.

### `runtime_failed`

Execution was attempted and failed at the runtime or provider boundary.
Sub-reasons:

| Reason | When |
|---|---|
| `retry_exhausted` | `FailureReason.RETRY_EXHAUSTED` / sealed `failure.reason == "retry_exhausted"` |
| `provider_error` | Provider/timeout/exception/endpoint errors and other incomplete runtime paths that are not fair semantic scores |

`runtime_failed` coordinates are reported for reliability diagnostics
(`accept_rate`, `retry_exhausted_rate`) but are excluded from default
semantic rankings.

### `semantic_scored`

Terminal **success** with the defined selection gates evaluated on real
artifacts (`source_copy_exclusion`, `polarity_preservation`,
`full_coverage`). Only this status contributes fair semantic loss to default
leaderboard and paired baseline comparisons.

## Default leaderboard and paired baseline policy

- **Deterministic baseline arm** (preregistered):

  `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`

- **Default leaderboard** admits only classifications with
  `status == semantic_scored`.
- **Default paired baseline comparisons** admit only `semantic_scored`
  candidates, paired against the baseline arm's own `semantic_scored`
  aggregates.
- Research reports may still *list* `not_measured` and `runtime_failed`
  counts, but must not rank them as semantic losses.

API surface:

- `classify_evaluation_status(...)` / `classify_coordinate_record(...)`
- `filter_leaderboard_classifications(...)`
- `filter_paired_baseline_classifications(...)`
- `is_default_leaderboard_eligible(...)`

## Matrix launch preflight (fail closed)

Before scored execution, every **scheduled** arm must present the preflight
evidence its class requires:

| Arm class | Required preflight |
|---|---|
| Guided (`guidance == guided` or `__guided__` in arm id) | `causal_qualification` with disposition/status `scored_supported` (reviewed causal L1 adapter) |
| Model-backed (model realizer or model constructor route `direct` / `symai`) | `live_smoke` per required route with `status=passed` **and** `model_inference_performed=true` |

Health-only probes (`model_inference_performed=false` or `health_only=true`)
do **not** satisfy live smoke.

API surface:

- `required_preflights_for_arm(arm)`
- `evaluate_matrix_launch_preflight(scheduled_arms, live_smokes=..., causal_qualification=...)`
- `assert_matrix_launch_preflight(...)` — raises `LaunchPreflightError` when
  any scheduled arm is missing required evidence

If any scheduled arm fails preflight, **matrix launch is blocked** (fail
closed). Unsupported guided arms must either:

1. become `scored_supported` via a reviewed causal adapter (EVAL-003 path a),
   or
2. be **removed from the scored schedule** and appear only as
   `not_measured` (EVAL-003 path b).

They must not be scheduled for semantic scoring under
`terminal_unsupported` qualification.

## Classification precedence

First match wins:

1. explicit / qualification `preflight_blocked` → `not_measured`
2. qualification `terminal_unsupported` → `not_measured`
3. failure `post_schedule_capability_unavailable` → `not_measured` /
   `terminal_unsupported`
4. failure `retry_exhausted` → `runtime_failed` / `retry_exhausted`
5. provider-boundary failure → `runtime_failed` / `provider_error`
6. component `success` with no failure reason → `semantic_scored` /
   `success`
7. any other terminal failure → `runtime_failed` / `provider_error`
   (conservative: do not invent a semantic score)

A `success` status carrying a failure reason is a contract error.

## 2026-07-27 replacement run mapping

Frozen report:
`docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json`

| Historical token | Count | Evaluation status | Reason |
|---|---:|---|---|
| `post_schedule_capability_unavailable` (12 guided arms × coordinates) | 260 | `not_measured` | `terminal_unsupported` |
| `retry_exhausted` | 210 | `runtime_failed` | `retry_exhausted` |
| success | 200 | `semantic_scored` | `success` |

Unit tests re-open that report, reclassify all 670 coordinates, and assert:

- guided arms → `not_measured` only;
- retry-exhausted rows → `runtime_failed` only;
- default leaderboard length equals the 200 successes;
- launching a schedule that still includes unsupported guided arms fails
  closed without `scored_supported` causal qualification.

## Normative machine-readable summary

```json
{
  "interface": "SemanticRoundTripEvaluationStatus@1",
  "schema_version": "ipfs-datasets.semantic-roundtrip-evaluation-status.v1",
  "statuses": ["not_measured", "runtime_failed", "semantic_scored"],
  "not_measured_reasons": ["terminal_unsupported", "preflight_blocked"],
  "runtime_failed_reasons": ["retry_exhausted", "provider_error"],
  "semantic_scored_reason": "success",
  "default_leaderboard": {
    "include": ["semantic_scored"],
    "exclude": ["not_measured", "runtime_failed"],
    "deterministic_baseline_arm_id": "typed_deontic__no_guidance__no_repair__not_applicable__deterministic"
  },
  "paired_baseline_comparisons": {
    "candidate_status_required": "semantic_scored",
    "baseline_arm_id": "typed_deontic__no_guidance__no_repair__not_applicable__deterministic"
  },
  "launch_preflight": {
    "policy": "fail_closed",
    "guided_requires": "causal_qualification.scored_supported",
    "model_backed_requires": "live_smoke.model_inference_performed",
    "health_only_insufficient": true
  },
  "historical_2026_07_27": {
    "scheduled": 670,
    "not_measured_guided": 260,
    "runtime_failed_retry_exhausted": 210,
    "semantic_scored_success": 200
  }
}
```

## Relationship to other EVAL tasks

- **EVAL-002** supplies live smokes with `model_inference_performed: true`.
- **EVAL-003** either marks guided arms `scored_supported` or keeps them
  out of the scored schedule as `not_measured`.
- **EVAL-004** diagnoses `retry_exhausted` without reclassifying it as a
  semantic score.
- **EVAL-009** research reports must exclude `not_measured` from semantic
  rankings and report reliability metrics separately.
