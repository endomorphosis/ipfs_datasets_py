# Semantic Round-Trip Evaluation Status Contract

**Interface:** `SemanticRoundTripEvaluationStatus@1`  
**Schema:** `ipfs-datasets.semantic-roundtrip-evaluation-status.v1`  
**Module:** `benchmarks.semantic_roundtrip.evaluation_status`

## Purpose

The 2026-07-27 replacement matrix shell completed 670/670 terminals, but most
optional methods were **not fairly measured**:

| Historical failure reason | Count | Fair interpretation |
| --- | ---: | --- |
| `post_schedule_capability_unavailable` | 260 | Guided / unsupported — never measured |
| `retry_exhausted` | 210 | Runtime / provider boundary failure |
| success | 200 | Fairly measured semantic score |

Without a disjoint taxonomy, loss `1.0` on unsupported guided arms polluted
default leaderboard rankings and “beats baseline” conclusions.

## Status taxonomy

Every coordinate classifies into **exactly one** of:

| Status | Reasons | Meaning |
| --- | --- | --- |
| `not_measured` | `terminal_unsupported`, `preflight_blocked` | Arm never fairly measured |
| `runtime_failed` | `retry_exhausted`, `provider_error` | Execution attempted; failed at runtime/provider boundary |
| `semantic_scored` | `success` | Terminal success with defined selection gates on real artifacts |

### Classification precedence

1. Explicit preflight block → `not_measured` / `preflight_blocked`
2. Qualification `terminal_unsupported` → `not_measured` / `terminal_unsupported`
3. Qualification or reason `preflight_blocked` → `not_measured` / `preflight_blocked`
4. Failure `post_schedule_capability_unavailable` → `not_measured` / `terminal_unsupported`
5. Failure `retry_exhausted` → `runtime_failed` / `retry_exhausted`
6. Provider-boundary failure → `runtime_failed` / `provider_error`
7. Terminal component success → `semantic_scored` / `success`
8. Any other terminal failure → `runtime_failed` / `provider_error` (conservative)

Success may not carry a `failure_reason`. Reasons must match status on sealed
records.

## Leaderboard and paired baseline policy

- Default leaderboard rankings admit only **`semantic_scored`** coordinates.
- Paired baseline comparisons admit only **`semantic_scored`** candidates.
- The preregistered deterministic baseline arm id is:

  `typed_deontic__no_guidance__no_repair__not_applicable__deterministic`

- Unsupported guided arms (historical loss `1.0`) **must not** appear as
  measured semantic defeats of the baseline.

## Matrix launch preflight (fail-closed)

Before scored execution, every scheduled arm must present the preflight
evidence its class requires:

| Arm class | Required preflight |
| --- | --- |
| Guided (`guidance=guided` or `__guided__` arm id) | `causal_qualification` with `scored_supported` disposition (or arm-local scored support) |
| Model-backed (`route` / constructor route in `{direct, symai}`, or `mode=model`) | `live_smoke` with passing status **and** real model inference (`model_inference_performed: true`; health-only probes alone fail closed) |

`evaluate_matrix_launch_preflight` returns a verdict.  
`assert_matrix_launch_preflight` raises `LaunchPreflightError` when any
required evidence is missing.

## Historical constants (2026-07-27 replacement run)

Frozen for contract tests:

- Scheduled coordinates: **670**
- Guided arms: **12**
- Guided coordinates (`not_measured`): **260**
- `retry_exhausted` (`runtime_failed`): **210**
- Successes (`semantic_scored`): **200**

Snapshot path:

`docs/performance_snapshots/2026-07-27_semantic_roundtrip_composition_replacement.json`

## Public API surface

- Enums: `EvaluationStatus`, `NotMeasuredReason`, `RuntimeFailedReason`
- Records: `EvaluationStatusRecord`, `ArmPreflightRequirement`, `LaunchPreflightVerdict`
- Classification: `classify_evaluation_status`, `classify_coordinate_record`,
  `classify_replacement_report_coordinates`,
  `classify_historical_replacement_failure_reason`
- Leaderboard filters: `is_default_leaderboard_eligible`,
  `filter_leaderboard_classifications`,
  `filter_paired_baseline_classifications`,
  `is_deterministic_baseline_arm`
- Preflight: `required_preflights_for_arm`, `evaluate_matrix_launch_preflight`,
  `assert_matrix_launch_preflight`
- Aggregates: `count_statuses`, `count_reasons`

## Validation

```bash
PYTHONPATH=. python -m pytest tests/unit/benchmarks/semantic_roundtrip/test_evaluation_status.py -q
```
