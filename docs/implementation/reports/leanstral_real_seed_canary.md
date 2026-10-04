# Leanstral Real Seed Canary

- Schema: `legal-ir-leanstral-real-seed-canary-v2`
- Mode: `dry-run`
- Production evidence: `non-production dry run`
- Selected tasks: 5 of 5 source records
- Verified tasks: 5
- Seeded tasks: 0
- Runtime seconds: 0.002559
- Production promotion allowed: `false`
- Observed throughput materially improved: `false` (0.000000)
- Synthetic/projected throughput improvement: `0.235573`
- Promotion blockers: `actual_isolated_implementations_missing`, `compiler_development_throughput_not_materially_improved`, `dry_run_no_production_promotion`, `no_accepted_compiler_decompiler_patch`, `no_observed_paired_metrics`, `no_provider_or_verified_cache_evidence`, `no_real_evidence_records`, `no_seeded_tasks`, `no_verifier_evidence`, `state_to_accepted_patch_lag_reduction_below_25_percent`

## Seeded Task Limit
- Maximum TODOs permitted: `5`
- Configured maximum TODOs: `5`
- Bounded selected TODOs: `5`
- Queue path: `workspace/leanstral-seed-canary/todos.jsonl`

## Paired Evaluation Metrics
| metric | Leanstral | control | relative improvement | regressed |
| --- | ---: | ---: | ---: | --- |
| `compiler_ir_cross_entropy` | 0.313197 | 0.351260 | 0.108361 | `false` |
| `compiler_ir_cosine` | 0.926895 | 0.905440 | 0.023696 | `false` |
| `learned_ir_view_cross_entropy` | 0.267918 | 0.296630 | 0.096794 | `false` |
| `learned_ir_view_cosine` | 0.951856 | 0.931140 | 0.022248 | `false` |
| `theorem_validity` | 1.000000 | 1.000000 | 0.000000 | `false` |
| `proof_validity` | 1.000000 | 1.000000 | 0.000000 | `false` |
| `graph_validity` | 1.000000 | 1.000000 | 0.000000 | `false` |
| `provenance_validity` | 1.000000 | 1.000000 | 0.000000 | `false` |
| `anti_copy_penalty` | 0.005200 | 0.007500 | 0.306667 | `false` |
| `mutation_validity` | 1.000000 | 1.000000 | 0.000000 | `false` |
| `validation_rejection_rate` | 0.112725 | 0.180000 | 0.373750 | `false` |
| `task_to_accepted_patch_rate` | 0.673448 | 0.545020 | 0.235639 | `false` |
| `cycle_time_seconds` | 1872.914512 | 2450.000000 | 0.235545 | `false` |
| `state_to_patch_lag` | 3.210755 | 4.200000 | 0.235535 | `false` |

## Evidence Provenance
- `packet_kind_counts`: {"synthetic_fixture": 5}
- `production_eligible_task_count`: 0
- `provider_or_verified_cache_task_count`: 0
- `real_record_count`: 0
- `seeded_production_eligible_task_count`: 0
- `synthetic_fixture_record_count`: 5
- `verifier_passed_task_count`: 0

## Paired Metrics Provenance
- `metric_kind_counts`: {"synthetic_projection": 5}
- `observed_improvement_task_count`: 0
- `synthetic_metrics_reported_as_observed`: false
- `synthetic_projection_task_count`: 5

## Isolated Implementation Evidence
- `accepted_compiler_decompiler_patch_count`: 0
- `actual_isolated_implementation_arm_count`: 0
- `control_accepted_patch_count`: 0
- `guardrail_regressions`: []
- `leanstral_accepted_patch_count`: 0
- `max_autoencoder_cycle_overhead`: 0.0
- `max_transient_execution_failure_rate`: 0.0
- `missing_isolated_implementation_arm_count`: 10
- `required_isolated_implementation_arm_count`: 10
- `task_count`: 5

## Hard Guardrails
- `anti_copy_passed`: 5
- `hard_guardrail_regressions`: []
- `promotion_allowed`: false
- `provenance_passed`: 5
- `schema_passed`: 5
- `selected_task_count`: 5
- `verified_task_count`: 5
- `verifier_passed`: 5

## Rollout Decision Gates
- `accepted_compiler_decompiler_patch_count`: 0
- `accepted_compiler_decompiler_patch_requirement_met`: false
- `actual_isolated_implementation_arm_count`: 0
- `actual_isolated_implementation_requirement_met`: false
- `autoencoder_cycle_overhead`: 0.0
- `autoencoder_cycle_overhead_requirement_met`: true
- `frozen_holdout_metric_regressions`: []
- `frozen_holdout_metrics_non_regressing`: true
- `implementation_guardrail_regressions`: []
- `max_autoencoder_cycle_overhead`: 0.1
- `max_transient_execution_failure_rate`: 0.05
- `min_accepted_compiler_patches`: 1
- `min_state_accepted_patch_lag_reduction`: 0.25
- `min_task_accepted_patch_rate_improvement`: 0.2
- `non_metric_guardrail_regressions`: []
- `non_metric_guardrails_non_regressing`: true
- `required_isolated_implementation_arm_count`: 10
- `state_to_accepted_patch_lag_relative_reduction`: 0.235535
- `state_to_accepted_patch_lag_requirement_met`: false
- `task_to_accepted_patch_rate_relative_improvement`: 0.235639
- `task_to_accepted_patch_rate_requirement_met`: true
- `transient_execution_failure_rate`: 0.0
- `transient_execution_failure_requirement_met`: true

## Throughput Decision
- `material_threshold`: 0.2
- `observed_improvement`: 0.0
- `synthetic_projected_improvement`: 0.2355728933564926
- `throughput_materially_improved`: false

## Task-To-Accepted-Patch Rate
- Leanstral `0.673448` vs control `0.545020`; relative improvement `0.235639`; regressed `false`

## Cycle Time
- Leanstral `1872.914512` vs control `2450.000000`; relative improvement `0.235545`; regressed `false`

## State-To-Accepted-Patch Lag
- Leanstral `3.210755` vs control `4.200000`; relative improvement `0.235535`; regressed `false`

## Rollback Commands
```bash
export LEANSTRAL_LEGAL_IR_MODE=off
pkill -f 'run_leanstral_seed_canary.py' || true
python scripts/ops/legal_ir/run_leanstral_seed_canary.py --dry-run --max-todos 5 --report-path docs/implementation/reports/leanstral_real_seed_canary.md
rm -f workspace/leanstral-seed-canary/todos.jsonl
```

## Paired Tasks

### 1. `leanstral-seed-pair-a10514de3366fee0`
- Cluster: `lir-cluster-b7b8d4c828f548d2`
- Surface: `external_provers.router`
- Family: `prover`
- Verified: `true`; seeded: `false`; audit verified: `false`
- Evidence provenance: `synthetic_fixture`; metrics: `synthetic_projection`
- Isolated implementations: Leanstral `false`; control `false`
- Patch outcomes: Leanstral `missing`; control `missing`
- Leanstral TODO: `leanstral-seed-pair-a10514de3366fee0-leanstral`
- Control TODO: `leanstral-seed-pair-a10514de3366fee0-control`
- Regressions: `none`

### 2. `leanstral-seed-pair-eb29fbc1933c6502`
- Cluster: `lir-cluster-fda24c331480bfd5`
- Surface: `deontic.ir`
- Family: `deontic`
- Verified: `true`; seeded: `false`; audit verified: `false`
- Evidence provenance: `synthetic_fixture`; metrics: `synthetic_projection`
- Isolated implementations: Leanstral `false`; control `false`
- Patch outcomes: Leanstral `missing`; control `missing`
- Leanstral TODO: `leanstral-seed-pair-eb29fbc1933c6502-leanstral`
- Control TODO: `leanstral-seed-pair-eb29fbc1933c6502-control`
- Regressions: `none`

### 3. `leanstral-seed-pair-dfb6429bdc623d2b`
- Cluster: `lir-cluster-e77b0212bdc71365`
- Surface: `external_provers.router`
- Family: `prover`
- Verified: `true`; seeded: `false`; audit verified: `false`
- Evidence provenance: `synthetic_fixture`; metrics: `synthetic_projection`
- Isolated implementations: Leanstral `false`; control `false`
- Patch outcomes: Leanstral `missing`; control `missing`
- Leanstral TODO: `leanstral-seed-pair-dfb6429bdc623d2b-leanstral`
- Control TODO: `leanstral-seed-pair-dfb6429bdc623d2b-control`
- Regressions: `none`

### 4. `leanstral-seed-pair-4a7f3c2183bb3419`
- Cluster: `lir-cluster-93f402990b1ef2ae`
- Surface: `external_provers.router`
- Family: `prover`
- Verified: `true`; seeded: `false`; audit verified: `false`
- Evidence provenance: `synthetic_fixture`; metrics: `synthetic_projection`
- Isolated implementations: Leanstral `false`; control `false`
- Patch outcomes: Leanstral `missing`; control `missing`
- Leanstral TODO: `leanstral-seed-pair-4a7f3c2183bb3419-leanstral`
- Control TODO: `leanstral-seed-pair-4a7f3c2183bb3419-control`
- Regressions: `none`

### 5. `leanstral-seed-pair-b70235a1bbfb94c6`
- Cluster: `lir-cluster-a3d46a0b4e660b31`
- Surface: `deontic.ir`
- Family: `deontic`
- Verified: `true`; seeded: `false`; audit verified: `false`
- Evidence provenance: `synthetic_fixture`; metrics: `synthetic_projection`
- Isolated implementations: Leanstral `false`; control `false`
- Patch outcomes: Leanstral `missing`; control `missing`
- Leanstral TODO: `leanstral-seed-pair-b70235a1bbfb94c6-leanstral`
- Control TODO: `leanstral-seed-pair-b70235a1bbfb94c6-control`
- Regressions: `none`

## Machine Readable Summary

```json
{
  "accepted_compiler_decompiler_patch_count": 0,
  "aggregate_comparisons": {
    "anti_copy_penalty": {
      "control": 0.0075,
      "delta": 0.0023,
      "direction": "lower_is_better",
      "improved": true,
      "leanstral": 0.0052,
      "metric": "anti_copy_penalty",
      "regressed": false,
      "relative_improvement": 0.306667
    },
    "compiler_ir_cosine": {
      "control": 0.90544,
      "delta": 0.021455,
      "direction": "higher_is_better",
      "improved": true,
      "leanstral": 0.926895,
      "metric": "compiler_ir_cosine",
      "regressed": false,
      "relative_improvement": 0.023696
    },
    "compiler_ir_cross_entropy": {
      "control": 0.35126,
      "delta": 0.038063,
      "direction": "lower_is_better",
      "improved": true,
      "leanstral": 0.313197,
      "metric": "compiler_ir_cross_entropy",
      "regressed": false,
      "relative_improvement": 0.108361
    },
    "cycle_time_seconds": {
      "control": 2450.0,
      "delta": 577.085488,
      "direction": "lower_is_better",
      "improved": true,
      "leanstral": 1872.914512,
      "metric": "cycle_time_seconds",
      "regressed": false,
      "relative_improvement": 0.235545
    },
    "graph_validity": {
      "control": 1.0,
      "delta": 0.0,
      "direction": "higher_is_better",
      "improved": false,
      "leanstral": 1.0,
      "metric": "graph_validity",
      "regressed": false,
      "relative_improvement": 0.0
    },
    "learned_ir_view_cosine": {
      "control": 0.93114,
      "delta": 0.020716,
      "direction": "higher_is_better",
      "improved": true,
      "leanstral": 0.951856,
      "metric": "learned_ir_view_cosine",
      "regressed": false,
      "relative_improvement": 0.022248
    },
    "learned_ir_view_cross_entropy": {
      "control": 0.29663,
      "delta": 0.028712,
      "direction": "lower_is_better",
      "improved": true,
      "leanstral": 0.267918,
      "metric": "learned_ir_view_cross_entropy",
      "regressed": false,
      "relative_improvement": 0.096794
    },
    "mutation_validity": {
      "control": 1.0,
      "delta": 0.0,
      "direction": "higher_is_better",
      "improved": false,
      "leanstral": 1.0,
      "metric": "mutation_validity",
      "regressed": false,
      "relative_improvement": 0.0
    },
    "proof_validity": {
      "control": 1.0,
      "delta": 0.0,
      "direction": "higher_is_better",
      "improved": false,
      "leanstral": 1.0,
      "metric": "proof_validity",
      "regressed": false,
      "relative_improvement": 0.0
    },
    "provenance_validity": {
      "control": 1.0,
      "delta": 0.0,
      "direction": "higher_is_better",
      "improved": false,
      "leanstral": 1.0,
      "metric": "provenance_validity",
      "regressed": false,
      "relative_improvement": 0.0
    },
    "state_to_patch_lag": {
      "control": 4.2,
      "delta": 0.989245,
      "direction": "lower_is_better",
      "improved": true,
      "leanstral": 3.210755,
      "metric": "state_to_patch_lag",
      "regressed": false,
      "relative_improvement": 0.235535
    },
    "task_to_accepted_patch_rate": {
      "control": 0.54502,
      "delta": 0.128428,
      "direction": "higher_is_better",
      "improved": true,
      "leanstral": 0.673448,
      "metric": "task_to_accepted_patch_rate",
      "regressed": false,
      "relative_improvement": 0.235639
    },
    "theorem_validity": {
      "control": 1.0,
      "delta": 0.0,
      "direction": "higher_is_better",
      "improved": false,
      "leanstral": 1.0,
      "metric": "theorem_validity",
      "regressed": false,
      "relative_improvement": 0.0
    },
    "validation_rejection_rate": {
      "control": 0.18,
      "delta": 0.067275,
      "direction": "lower_is_better",
      "improved": true,
      "leanstral": 0.112725,
      "metric": "validation_rejection_rate",
      "regressed": false,
      "relative_improvement": 0.37375
    }
  },
  "config": {
    "cache_dir": "",
    "dry_run": true,
    "material_throughput_improvement": 0.2,
    "max_autoencoder_cycle_overhead": 0.1,
    "max_source_span_copy_ratio": 0.25,
    "max_todos": 5,
    "max_transient_execution_failure_rate": 0.05,
    "metric_deadband": 0.0,
    "min_accepted_compiler_patches": 1,
    "min_state_accepted_patch_lag_reduction": 0.25,
    "min_task_accepted_patch_rate_improvement": 0.2,
    "model": "Leanstral",
    "provider": "mistral_vibe",
    "report_path": "docs/implementation/reports/leanstral_real_seed_canary.md",
    "require_actual_isolated_implementations": true,
    "require_verified_audit_for_promotion": true,
    "timeout_seconds": 300.0,
    "todo_queue_path": "workspace/leanstral-seed-canary/todos.jsonl",
    "vibe_agent": "lean"
  },
  "dry_run_no_mutation": {
    "dry_run": true,
    "dry_run_non_production": true,
    "max_todos": 5,
    "queue_append_count": 0,
    "source_mutation_count": 0,
    "synthetic_metrics_are_projection_only": true,
    "verified_candidates": 5
  },
  "evidence_provenance_summary": {
    "packet_kind_counts": {
      "synthetic_fixture": 5
    },
    "production_eligible_task_count": 0,
    "provider_or_verified_cache_task_count": 0,
    "real_record_count": 0,
    "seeded_production_eligible_task_count": 0,
    "synthetic_fixture_record_count": 5,
    "verifier_passed_task_count": 0
  },
  "hard_guardrail_regressions": [],
  "isolated_implementation_summary": {
    "accepted_compiler_decompiler_patch_count": 0,
    "actual_isolated_implementation_arm_count": 0,
    "control_accepted_patch_count": 0,
    "guardrail_regressions": [],
    "leanstral_accepted_patch_count": 0,
    "max_autoencoder_cycle_overhead": 0.0,
    "max_transient_execution_failure_rate": 0.0,
    "missing_isolated_implementation_arm_count": 10,
    "required_isolated_implementation_arm_count": 10,
    "task_count": 5
  },
  "paired_metrics_provenance_summary": {
    "metric_kind_counts": {
      "synthetic_projection": 5
    },
    "observed_improvement_task_count": 0,
    "synthetic_metrics_reported_as_observed": false,
    "synthetic_projection_task_count": 5
  },
  "projected_throughput_improvement": 0.235573,
  "promotion_allowed": false,
  "promotion_blockers": [
    "actual_isolated_implementations_missing",
    "compiler_development_throughput_not_materially_improved",
    "dry_run_no_production_promotion",
    "no_accepted_compiler_decompiler_patch",
    "no_observed_paired_metrics",
    "no_provider_or_verified_cache_evidence",
    "no_real_evidence_records",
    "no_seeded_tasks",
    "no_verifier_evidence",
    "state_to_accepted_patch_lag_reduction_below_25_percent"
  ],
  "rollout_decision_summary": {
    "accepted_compiler_decompiler_patch_count": 0,
    "accepted_compiler_decompiler_patch_requirement_met": false,
    "actual_isolated_implementation_arm_count": 0,
    "actual_isolated_implementation_requirement_met": false,
    "autoencoder_cycle_overhead": 0.0,
    "autoencoder_cycle_overhead_requirement_met": true,
    "frozen_holdout_metric_regressions": [],
    "frozen_holdout_metrics_non_regressing": true,
    "implementation_guardrail_regressions": [],
    "max_autoencoder_cycle_overhead": 0.1,
    "max_transient_execution_failure_rate": 0.05,
    "min_accepted_compiler_patches": 1,
    "min_state_accepted_patch_lag_reduction": 0.25,
    "min_task_accepted_patch_rate_improvement": 0.2,
    "non_metric_guardrail_regressions": [],
    "non_metric_guardrails_non_regressing": true,
    "required_isolated_implementation_arm_count": 10,
    "state_to_accepted_patch_lag_relative_reduction": 0.235535,
    "state_to_accepted_patch_lag_requirement_met": false,
    "task_to_accepted_patch_rate_relative_improvement": 0.235639,
    "task_to_accepted_patch_rate_requirement_met": true,
    "transient_execution_failure_rate": 0.0,
    "transient_execution_failure_requirement_met": true
  },
  "runtime_seconds": 0.002559,
  "schema_version": "legal-ir-leanstral-real-seed-canary-v2",
  "seeded_task_count": 0,
  "selected_task_count": 5,
  "shadow_summary": {
    "audit_validity": {
      "invalid": 5,
      "valid": 0,
      "verified": 0
    },
    "cache_summary": {
      "cache_hits": 0,
      "cache_misses": 5,
      "llm_calls": 0,
      "requests": 5
    },
    "evidence_provenance_summary": {
      "cached_real_packet_count": 0,
      "dry_run_reports_are_non_production": true,
      "live_canonical_state_packet_count": 0,
      "packet_kind_counts": {
        "synthetic_fixture": 5
      },
      "production_eligible_audit_count": 0,
      "provider_or_verified_cache_audit_count": 0,
      "real_record_count": 0,
      "synthetic_fixture_record_count": 5,
      "unknown_record_count": 0,
      "verifier_passed_audit_count": 0
    },
    "promotion_allowed": false,
    "promotion_blockers": [
      "dry_run_no_promotion",
      "no_provider_or_verified_cache_evidence",
      "no_real_evidence_records",
      "no_verifier_evidence",
      "verifier_guardrail_not_satisfied"
    ],
    "selected_cluster_count": 5
  },
  "source_record_count": 5,
  "tasks": [
    {
      "audit_verified": false,
      "cluster_id": "lir-cluster-b7b8d4c828f548d2",
      "comparisons": [
        {
          "control": 0.3465,
          "delta": 0.03771,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.30879,
          "metric": "compiler_ir_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.108831
        },
        {
          "control": 0.908,
          "delta": 0.02161,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.92961,
          "metric": "compiler_ir_cosine",
          "regressed": false,
          "relative_improvement": 0.0238
        },
        {
          "control": 0.28846,
          "delta": 0.027764,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.260696,
          "metric": "learned_ir_view_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.096249
        },
        {
          "control": 0.93538,
          "delta": 0.0205,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.95588,
          "metric": "learned_ir_view_cosine",
          "regressed": false,
          "relative_improvement": 0.021916
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "theorem_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "proof_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "graph_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "provenance_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.0065,
          "delta": 0.0021,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.0044,
          "metric": "anti_copy_penalty",
          "regressed": false,
          "relative_improvement": 0.323077
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "mutation_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.18,
          "delta": 0.06805,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.11195,
          "metric": "validation_rejection_rate",
          "regressed": false,
          "relative_improvement": 0.378056
        },
        {
          "control": 0.5425,
          "delta": 0.128507,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.671007,
          "metric": "task_to_accepted_patch_rate",
          "regressed": false,
          "relative_improvement": 0.236879
        },
        {
          "control": 2030.0,
          "delta": 480.8664,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 1549.1336,
          "metric": "cycle_time_seconds",
          "regressed": false,
          "relative_improvement": 0.23688
        },
        {
          "control": 3.4,
          "delta": 0.805392,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 2.594608,
          "metric": "state_to_patch_lag",
          "regressed": false,
          "relative_improvement": 0.23688
        }
      ],
      "compiler_surface": "external_provers.router",
      "control_implementation": {
        "accepted_patch": false,
        "arm": "control",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 3.4,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "control_metrics": {
        "anti_copy_penalty": 0.0065,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.908,
        "compiler_ir_cross_entropy": 0.3465,
        "cycle_time_seconds": 2030.0,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.93538,
        "learned_ir_view_cross_entropy": 0.28846,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 3.4,
        "task_to_accepted_patch_rate": 0.5425,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.18
      },
      "control_task": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "arm": "control",
        "cluster_id": "lir-cluster-b7b8d4c828f548d2",
        "compiler_surface": "external_provers.router",
        "dedup_key": "leanstral-shadow-4bd261e4d8679d16-control",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": false,
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "pair_id": "leanstral-seed-pair-a10514de3366fee0",
        "rank": 1,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "prover",
        "semantic_signature": "prover:formal_prover_gap:prover->temporal:route_failure_ratio",
        "source": "matched_control",
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "todo_id": "leanstral-seed-pair-a10514de3366fee0-control",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "dry_run": true,
      "evidence_ids": [
        "dry-run-evidence-001",
        "dry-run-evidence-002",
        "dry-run-evidence-003",
        "dry-run-evidence-004",
        "dry-run-evidence-005"
      ],
      "evidence_provenance": {
        "cached_real_packet_count": 0,
        "dominant_kind": "synthetic_fixture",
        "live_canonical_state_packet_count": 0,
        "live_provider_used": false,
        "packet_kind_counts": {
          "synthetic_fixture": 1
        },
        "production_eligible": false,
        "provider_or_verified_cache": false,
        "real_record_count": 0,
        "record_count": 1,
        "synthetic_fixture_record_count": 1,
        "unknown_record_count": 0,
        "verified_cache_used": false
      },
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "leanstral_implementation": {
        "accepted_patch": false,
        "arm": "leanstral",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 2.594608,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "leanstral_metrics": {
        "anti_copy_penalty": 0.0044,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.92961,
        "compiler_ir_cross_entropy": 0.30879,
        "cycle_time_seconds": 1549.1336,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.95588,
        "learned_ir_view_cross_entropy": 0.260696,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 2.594608,
        "task_to_accepted_patch_rate": 0.671007,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.11195
      },
      "leanstral_task": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "arm": "leanstral",
        "cluster_id": "lir-cluster-b7b8d4c828f548d2",
        "compiler_surface": "external_provers.router",
        "dedup_key": "leanstral-shadow-4bd261e4d8679d16-leanstral",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": true,
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "pair_id": "leanstral-seed-pair-a10514de3366fee0",
        "rank": 1,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "prover",
        "semantic_signature": "prover:formal_prover_gap:prover->temporal:route_failure_ratio",
        "source": "leanstral_seed_canary",
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "todo_id": "leanstral-seed-pair-a10514de3366fee0-leanstral",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "pair_id": "leanstral-seed-pair-a10514de3366fee0",
      "paired_metrics_provenance": {
        "kind": "synthetic_projection",
        "metric_record_count": 5,
        "observed_improvement_eligible": false,
        "production_evidence_eligible": false,
        "synthetic_projection": true
      },
      "rank": 1,
      "sample_ids": [
        "dry-run-sample-001",
        "dry-run-sample-002",
        "dry-run-sample-003",
        "dry-run-sample-004",
        "dry-run-sample-005"
      ],
      "seeded": false,
      "semantic_family": "prover",
      "semantic_signature": "prover:formal_prover_gap:prover->temporal:route_failure_ratio",
      "verification_reasons": [],
      "verified": true
    },
    {
      "audit_verified": false,
      "cluster_id": "lir-cluster-fda24c331480bfd5",
      "comparisons": [
        {
          "control": 0.3424,
          "delta": 0.037178,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.305222,
          "metric": "compiler_ir_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.108581
        },
        {
          "control": 0.9096,
          "delta": 0.021527,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.931127,
          "metric": "compiler_ir_cosine",
          "regressed": false,
          "relative_improvement": 0.023666
        },
        {
          "control": 0.292622,
          "delta": 0.02856,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.264062,
          "metric": "learned_ir_view_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.0976
        },
        {
          "control": 0.933216,
          "delta": 0.02104,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.954256,
          "metric": "learned_ir_view_cosine",
          "regressed": false,
          "relative_improvement": 0.022546
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "theorem_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "proof_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "graph_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "provenance_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.007,
          "delta": 0.0022,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.0048,
          "metric": "anti_copy_penalty",
          "regressed": false,
          "relative_improvement": 0.314286
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "mutation_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.18,
          "delta": 0.067635,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.112365,
          "metric": "validation_rejection_rate",
          "regressed": false,
          "relative_improvement": 0.37575
        },
        {
          "control": 0.5488,
          "delta": 0.129635,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.678435,
          "metric": "task_to_accepted_patch_rate",
          "regressed": false,
          "relative_improvement": 0.236215
        },
        {
          "control": 2240.0,
          "delta": 529.12384,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 1710.87616,
          "metric": "cycle_time_seconds",
          "regressed": false,
          "relative_improvement": 0.236216
        },
        {
          "control": 3.8,
          "delta": 0.897621,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 2.902379,
          "metric": "state_to_patch_lag",
          "regressed": false,
          "relative_improvement": 0.236216
        }
      ],
      "compiler_surface": "deontic.ir",
      "control_implementation": {
        "accepted_patch": false,
        "arm": "control",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 3.8,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "control_metrics": {
        "anti_copy_penalty": 0.007,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.9096,
        "compiler_ir_cross_entropy": 0.3424,
        "cycle_time_seconds": 2240.0,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.933216,
        "learned_ir_view_cross_entropy": 0.292622,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 3.8,
        "task_to_accepted_patch_rate": 0.5488,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.18
      },
      "control_task": {
        "action": "repair_deontic_bridge_quality_gate",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "arm": "control",
        "cluster_id": "lir-cluster-fda24c331480bfd5",
        "compiler_surface": "deontic.ir",
        "dedup_key": "leanstral-shadow-74fb040347f3c52e-control",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": false,
        "mutation_cases": [
          "invert_modality",
          "remove_exception"
        ],
        "pair_id": "leanstral-seed-pair-eb29fbc1933c6502",
        "rank": 2,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "deontic",
        "semantic_signature": "deontic:compiler_component_gap:deontic->temporal:obligation_scope",
        "source": "matched_control",
        "target_component": "deontic.ir",
        "target_metrics": [
          "deontic_decoder_slot_loss",
          "legal_ir_view_cross_entropy_loss"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "exception_scope_preserved"
        ],
        "todo_id": "leanstral-seed-pair-eb29fbc1933c6502-control",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "dry_run": true,
      "evidence_ids": [
        "dry-run-evidence-001",
        "dry-run-evidence-002",
        "dry-run-evidence-003",
        "dry-run-evidence-004",
        "dry-run-evidence-005"
      ],
      "evidence_provenance": {
        "cached_real_packet_count": 0,
        "dominant_kind": "synthetic_fixture",
        "live_canonical_state_packet_count": 0,
        "live_provider_used": false,
        "packet_kind_counts": {
          "synthetic_fixture": 1
        },
        "production_eligible": false,
        "provider_or_verified_cache": false,
        "real_record_count": 0,
        "record_count": 1,
        "synthetic_fixture_record_count": 1,
        "unknown_record_count": 0,
        "verified_cache_used": false
      },
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "leanstral_implementation": {
        "accepted_patch": false,
        "arm": "leanstral",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 2.902379,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "leanstral_metrics": {
        "anti_copy_penalty": 0.0048,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.931127,
        "compiler_ir_cross_entropy": 0.305222,
        "cycle_time_seconds": 1710.87616,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.954256,
        "learned_ir_view_cross_entropy": 0.264062,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 2.902379,
        "task_to_accepted_patch_rate": 0.678435,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.112365
      },
      "leanstral_task": {
        "action": "repair_deontic_bridge_quality_gate",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "arm": "leanstral",
        "cluster_id": "lir-cluster-fda24c331480bfd5",
        "compiler_surface": "deontic.ir",
        "dedup_key": "leanstral-shadow-74fb040347f3c52e-leanstral",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": true,
        "mutation_cases": [
          "invert_modality",
          "remove_exception"
        ],
        "pair_id": "leanstral-seed-pair-eb29fbc1933c6502",
        "rank": 2,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "deontic",
        "semantic_signature": "deontic:compiler_component_gap:deontic->temporal:obligation_scope",
        "source": "leanstral_seed_canary",
        "target_component": "deontic.ir",
        "target_metrics": [
          "deontic_decoder_slot_loss",
          "legal_ir_view_cross_entropy_loss"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "exception_scope_preserved"
        ],
        "todo_id": "leanstral-seed-pair-eb29fbc1933c6502-leanstral",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "pair_id": "leanstral-seed-pair-eb29fbc1933c6502",
      "paired_metrics_provenance": {
        "kind": "synthetic_projection",
        "metric_record_count": 5,
        "observed_improvement_eligible": false,
        "production_evidence_eligible": false,
        "synthetic_projection": true
      },
      "rank": 2,
      "sample_ids": [
        "dry-run-sample-001",
        "dry-run-sample-002",
        "dry-run-sample-003",
        "dry-run-sample-004",
        "dry-run-sample-005"
      ],
      "seeded": false,
      "semantic_family": "deontic",
      "semantic_signature": "deontic:compiler_component_gap:deontic->temporal:obligation_scope",
      "verification_reasons": [],
      "verified": true
    },
    {
      "audit_verified": false,
      "cluster_id": "lir-cluster-e77b0212bdc71365",
      "comparisons": [
        {
          "control": 0.3545,
          "delta": 0.038376,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.316124,
          "metric": "compiler_ir_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.108254
        },
        {
          "control": 0.904,
          "delta": 0.021418,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.925418,
          "metric": "compiler_ir_cosine",
          "regressed": false,
          "relative_improvement": 0.023692
        },
        {
          "control": 0.297148,
          "delta": 0.0286,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.268548,
          "metric": "learned_ir_view_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.096248
        },
        {
          "control": 0.930844,
          "delta": 0.0205,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.951344,
          "metric": "learned_ir_view_cosine",
          "regressed": false,
          "relative_improvement": 0.022023
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "theorem_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "proof_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "graph_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "provenance_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.0075,
          "delta": 0.0023,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.0052,
          "metric": "anti_copy_penalty",
          "regressed": false,
          "relative_improvement": 0.306667
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "mutation_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.18,
          "delta": 0.06709,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.11291,
          "metric": "validation_rejection_rate",
          "regressed": false,
          "relative_improvement": 0.372722
        },
        {
          "control": 0.5425,
          "delta": 0.127674,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.670174,
          "metric": "task_to_accepted_patch_rate",
          "regressed": false,
          "relative_improvement": 0.235344
        },
        {
          "control": 2450.0,
          "delta": 576.5928,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 1873.4072,
          "metric": "cycle_time_seconds",
          "regressed": false,
          "relative_improvement": 0.235344
        },
        {
          "control": 4.2,
          "delta": 0.988445,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 3.211555,
          "metric": "state_to_patch_lag",
          "regressed": false,
          "relative_improvement": 0.235344
        }
      ],
      "compiler_surface": "external_provers.router",
      "control_implementation": {
        "accepted_patch": false,
        "arm": "control",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 4.2,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "control_metrics": {
        "anti_copy_penalty": 0.0075,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.904,
        "compiler_ir_cross_entropy": 0.3545,
        "cycle_time_seconds": 2450.0,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.930844,
        "learned_ir_view_cross_entropy": 0.297148,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 4.2,
        "task_to_accepted_patch_rate": 0.5425,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.18
      },
      "control_task": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "arm": "control",
        "cluster_id": "lir-cluster-e77b0212bdc71365",
        "compiler_surface": "external_provers.router",
        "dedup_key": "leanstral-shadow-ce9d53ab33c557a7-control",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": false,
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "pair_id": "leanstral-seed-pair-dfb6429bdc623d2b",
        "rank": 3,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "prover",
        "semantic_signature": "prover:compiler_component_gap:prover->temporal:failure_ratio",
        "source": "matched_control",
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "todo_id": "leanstral-seed-pair-dfb6429bdc623d2b-control",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "dry_run": true,
      "evidence_ids": [
        "dry-run-evidence-001",
        "dry-run-evidence-002",
        "dry-run-evidence-003",
        "dry-run-evidence-004",
        "dry-run-evidence-005"
      ],
      "evidence_provenance": {
        "cached_real_packet_count": 0,
        "dominant_kind": "synthetic_fixture",
        "live_canonical_state_packet_count": 0,
        "live_provider_used": false,
        "packet_kind_counts": {
          "synthetic_fixture": 1
        },
        "production_eligible": false,
        "provider_or_verified_cache": false,
        "real_record_count": 0,
        "record_count": 1,
        "synthetic_fixture_record_count": 1,
        "unknown_record_count": 0,
        "verified_cache_used": false
      },
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "leanstral_implementation": {
        "accepted_patch": false,
        "arm": "leanstral",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 3.211555,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "leanstral_metrics": {
        "anti_copy_penalty": 0.0052,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.925418,
        "compiler_ir_cross_entropy": 0.316124,
        "cycle_time_seconds": 1873.4072,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.951344,
        "learned_ir_view_cross_entropy": 0.268548,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 3.211555,
        "task_to_accepted_patch_rate": 0.670174,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.11291
      },
      "leanstral_task": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "arm": "leanstral",
        "cluster_id": "lir-cluster-e77b0212bdc71365",
        "compiler_surface": "external_provers.router",
        "dedup_key": "leanstral-shadow-ce9d53ab33c557a7-leanstral",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": true,
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "pair_id": "leanstral-seed-pair-dfb6429bdc623d2b",
        "rank": 3,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "prover",
        "semantic_signature": "prover:compiler_component_gap:prover->temporal:failure_ratio",
        "source": "leanstral_seed_canary",
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "todo_id": "leanstral-seed-pair-dfb6429bdc623d2b-leanstral",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "pair_id": "leanstral-seed-pair-dfb6429bdc623d2b",
      "paired_metrics_provenance": {
        "kind": "synthetic_projection",
        "metric_record_count": 5,
        "observed_improvement_eligible": false,
        "production_evidence_eligible": false,
        "synthetic_projection": true
      },
      "rank": 3,
      "sample_ids": [
        "dry-run-sample-001",
        "dry-run-sample-002",
        "dry-run-sample-003",
        "dry-run-sample-004",
        "dry-run-sample-005"
      ],
      "seeded": false,
      "semantic_family": "prover",
      "semantic_signature": "prover:compiler_component_gap:prover->temporal:failure_ratio",
      "verification_reasons": [],
      "verified": true
    },
    {
      "audit_verified": false,
      "cluster_id": "lir-cluster-93f402990b1ef2ae",
      "comparisons": [
        {
          "control": 0.3585,
          "delta": 0.038774,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.319726,
          "metric": "compiler_ir_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.108156
        },
        {
          "control": 0.902,
          "delta": 0.021385,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.923385,
          "metric": "compiler_ir_cosine",
          "regressed": false,
          "relative_improvement": 0.023708
        },
        {
          "control": 0.30061,
          "delta": 0.028934,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.271676,
          "metric": "learned_ir_view_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.096251
        },
        {
          "control": 0.92908,
          "delta": 0.0205,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.94958,
          "metric": "learned_ir_view_cosine",
          "regressed": false,
          "relative_improvement": 0.022065
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "theorem_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "proof_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "graph_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "provenance_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.008,
          "delta": 0.0024,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.0056,
          "metric": "anti_copy_penalty",
          "regressed": false,
          "relative_improvement": 0.3
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "mutation_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.18,
          "delta": 0.066925,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.113075,
          "metric": "validation_rejection_rate",
          "regressed": false,
          "relative_improvement": 0.371806
        },
        {
          "control": 0.5425,
          "delta": 0.127531,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.670031,
          "metric": "task_to_accepted_patch_rate",
          "regressed": false,
          "relative_improvement": 0.23508
        },
        {
          "control": 2660.0,
          "delta": 625.3128,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 2034.6872,
          "metric": "cycle_time_seconds",
          "regressed": false,
          "relative_improvement": 0.23508
        },
        {
          "control": 4.6,
          "delta": 1.081368,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 3.518632,
          "metric": "state_to_patch_lag",
          "regressed": false,
          "relative_improvement": 0.23508
        }
      ],
      "compiler_surface": "external_provers.router",
      "control_implementation": {
        "accepted_patch": false,
        "arm": "control",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 4.6,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "control_metrics": {
        "anti_copy_penalty": 0.008,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.902,
        "compiler_ir_cross_entropy": 0.3585,
        "cycle_time_seconds": 2660.0,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.92908,
        "learned_ir_view_cross_entropy": 0.30061,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 4.6,
        "task_to_accepted_patch_rate": 0.5425,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.18
      },
      "control_task": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "arm": "control",
        "cluster_id": "lir-cluster-93f402990b1ef2ae",
        "compiler_surface": "external_provers.router",
        "dedup_key": "leanstral-shadow-61039e7425f6da22-control",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": false,
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "pair_id": "leanstral-seed-pair-4a7f3c2183bb3419",
        "rank": 4,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "prover",
        "semantic_signature": "prover:synthesis_focus_gap:prover->temporal:failure_ratio",
        "source": "matched_control",
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "todo_id": "leanstral-seed-pair-4a7f3c2183bb3419-control",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "dry_run": true,
      "evidence_ids": [
        "dry-run-evidence-001",
        "dry-run-evidence-002",
        "dry-run-evidence-003",
        "dry-run-evidence-004",
        "dry-run-evidence-005"
      ],
      "evidence_provenance": {
        "cached_real_packet_count": 0,
        "dominant_kind": "synthetic_fixture",
        "live_canonical_state_packet_count": 0,
        "live_provider_used": false,
        "packet_kind_counts": {
          "synthetic_fixture": 1
        },
        "production_eligible": false,
        "provider_or_verified_cache": false,
        "real_record_count": 0,
        "record_count": 1,
        "synthetic_fixture_record_count": 1,
        "unknown_record_count": 0,
        "verified_cache_used": false
      },
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "leanstral_implementation": {
        "accepted_patch": false,
        "arm": "leanstral",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 3.518632,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "leanstral_metrics": {
        "anti_copy_penalty": 0.0056,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.923385,
        "compiler_ir_cross_entropy": 0.319726,
        "cycle_time_seconds": 2034.6872,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.94958,
        "learned_ir_view_cross_entropy": 0.271676,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 3.518632,
        "task_to_accepted_patch_rate": 0.670031,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.113075
      },
      "leanstral_task": {
        "action": "repair_multiview_legal_ir_prover_gate",
        "allowed_paths": [
          "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
          "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py"
        ],
        "arm": "leanstral",
        "cluster_id": "lir-cluster-93f402990b1ef2ae",
        "compiler_surface": "external_provers.router",
        "dedup_key": "leanstral-shadow-61039e7425f6da22-leanstral",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": true,
        "mutation_cases": [
          "unsupported_modal_system"
        ],
        "pair_id": "leanstral-seed-pair-4a7f3c2183bb3419",
        "rank": 4,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "prover",
        "semantic_signature": "prover:synthesis_focus_gap:prover->temporal:failure_ratio",
        "source": "leanstral_seed_canary",
        "target_component": "external_provers.router",
        "target_metrics": [
          "legal_ir_multiview_proof_failure_ratio"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "proof_route_is_distinct_from_proof"
        ],
        "todo_id": "leanstral-seed-pair-4a7f3c2183bb3419-leanstral",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "pair_id": "leanstral-seed-pair-4a7f3c2183bb3419",
      "paired_metrics_provenance": {
        "kind": "synthetic_projection",
        "metric_record_count": 5,
        "observed_improvement_eligible": false,
        "production_evidence_eligible": false,
        "synthetic_projection": true
      },
      "rank": 4,
      "sample_ids": [
        "dry-run-sample-001",
        "dry-run-sample-002",
        "dry-run-sample-003",
        "dry-run-sample-004",
        "dry-run-sample-005"
      ],
      "seeded": false,
      "semantic_family": "prover",
      "semantic_signature": "prover:synthesis_focus_gap:prover->temporal:failure_ratio",
      "verification_reasons": [],
      "verified": true
    },
    {
      "audit_verified": false,
      "cluster_id": "lir-cluster-a3d46a0b4e660b31",
      "comparisons": [
        {
          "control": 0.3544,
          "delta": 0.038277,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.316123,
          "metric": "compiler_ir_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.108005
        },
        {
          "control": 0.9036,
          "delta": 0.021335,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.924935,
          "metric": "compiler_ir_cosine",
          "regressed": false,
          "relative_improvement": 0.023611
        },
        {
          "control": 0.30431,
          "delta": 0.029701,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.274609,
          "metric": "learned_ir_view_cross_entropy",
          "regressed": false,
          "relative_improvement": 0.097601
        },
        {
          "control": 0.92718,
          "delta": 0.02104,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.94822,
          "metric": "learned_ir_view_cosine",
          "regressed": false,
          "relative_improvement": 0.022692
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "theorem_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "proof_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "graph_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "provenance_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.0085,
          "delta": 0.0025,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.006,
          "metric": "anti_copy_penalty",
          "regressed": false,
          "relative_improvement": 0.294118
        },
        {
          "control": 1.0,
          "delta": 0.0,
          "direction": "higher_is_better",
          "improved": false,
          "leanstral": 1.0,
          "metric": "mutation_validity",
          "regressed": false,
          "relative_improvement": 0.0
        },
        {
          "control": 0.18,
          "delta": 0.066675,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 0.113325,
          "metric": "validation_rejection_rate",
          "regressed": false,
          "relative_improvement": 0.370417
        },
        {
          "control": 0.5488,
          "delta": 0.128792,
          "direction": "higher_is_better",
          "improved": true,
          "leanstral": 0.677592,
          "metric": "task_to_accepted_patch_rate",
          "regressed": false,
          "relative_improvement": 0.234679
        },
        {
          "control": 2870.0,
          "delta": 673.5316,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 2196.4684,
          "metric": "cycle_time_seconds",
          "regressed": false,
          "relative_improvement": 0.23468
        },
        {
          "control": 5.0,
          "delta": 1.1734,
          "direction": "lower_is_better",
          "improved": true,
          "leanstral": 3.8266,
          "metric": "state_to_patch_lag",
          "regressed": false,
          "relative_improvement": 0.23468
        }
      ],
      "compiler_surface": "deontic.ir",
      "control_implementation": {
        "accepted_patch": false,
        "arm": "control",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 5.0,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "control_metrics": {
        "anti_copy_penalty": 0.0085,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.9036,
        "compiler_ir_cross_entropy": 0.3544,
        "cycle_time_seconds": 2870.0,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.92718,
        "learned_ir_view_cross_entropy": 0.30431,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 5.0,
        "task_to_accepted_patch_rate": 0.5488,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.18
      },
      "control_task": {
        "action": "repair_deontic_bridge_quality_gate",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "arm": "control",
        "cluster_id": "lir-cluster-a3d46a0b4e660b31",
        "compiler_surface": "deontic.ir",
        "dedup_key": "leanstral-shadow-c7b5d47236779a3a-control",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": false,
        "mutation_cases": [
          "invert_modality",
          "remove_exception"
        ],
        "pair_id": "leanstral-seed-pair-b70235a1bbfb94c6",
        "rank": 5,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "deontic",
        "semantic_signature": "deontic:synthesis_focus_gap:deontic->temporal:obligation_scope",
        "source": "matched_control",
        "target_component": "deontic.ir",
        "target_metrics": [
          "deontic_decoder_slot_loss",
          "legal_ir_view_cross_entropy_loss"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "exception_scope_preserved"
        ],
        "todo_id": "leanstral-seed-pair-b70235a1bbfb94c6-control",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "dry_run": true,
      "evidence_ids": [
        "dry-run-evidence-001",
        "dry-run-evidence-002",
        "dry-run-evidence-003",
        "dry-run-evidence-004",
        "dry-run-evidence-005"
      ],
      "evidence_provenance": {
        "cached_real_packet_count": 0,
        "dominant_kind": "synthetic_fixture",
        "live_canonical_state_packet_count": 0,
        "live_provider_used": false,
        "packet_kind_counts": {
          "synthetic_fixture": 1
        },
        "production_eligible": false,
        "provider_or_verified_cache": false,
        "real_record_count": 0,
        "record_count": 1,
        "synthetic_fixture_record_count": 1,
        "unknown_record_count": 0,
        "verified_cache_used": false
      },
      "guardrails": {
        "anti_copy": {
          "max_observed_source_span_copy_ratio": 0.0,
          "passed": true,
          "reasons": []
        },
        "passed": false,
        "provenance": {
          "missing": [],
          "passed": true
        },
        "schema": {
          "audit_response_schema_version": "",
          "cluster_schema_version": "legal-ir-introspection-analysis-v1",
          "passed": true
        },
        "verifier": {
          "passed": false,
          "reasons": [
            "dry_run_no_provider_audit"
          ],
          "verifier_outcome": "not-run"
        }
      },
      "leanstral_implementation": {
        "accepted_patch": false,
        "arm": "leanstral",
        "autoencoder_cycle_overhead": 0.0,
        "compiler_or_decompiler_patch": false,
        "guardrail_regressions": [
          "missing_isolated_implementation"
        ],
        "isolated": false,
        "locally_verified": false,
        "outcome": "missing",
        "patch_id": "",
        "source": {},
        "state_to_accepted_patch_lag": 3.8266,
        "transient_execution_failure_rate": 0.0,
        "validation_commands": [],
        "validation_worktree": ""
      },
      "leanstral_metrics": {
        "anti_copy_penalty": 0.006,
        "autoencoder_cycle_overhead": 0.0,
        "compiler_ir_cosine": 0.924935,
        "compiler_ir_cross_entropy": 0.316123,
        "cycle_time_seconds": 2196.4684,
        "graph_validity": 1.0,
        "learned_ir_view_cosine": 0.94822,
        "learned_ir_view_cross_entropy": 0.274609,
        "mutation_validity": 1.0,
        "proof_validity": 1.0,
        "provenance_validity": 1.0,
        "state_to_patch_lag": 3.8266,
        "task_to_accepted_patch_rate": 0.677592,
        "theorem_validity": 1.0,
        "transient_execution_failure_rate": 0.0,
        "validation_rejection_rate": 0.113325
      },
      "leanstral_task": {
        "action": "repair_deontic_bridge_quality_gate",
        "allowed_paths": [
          "ipfs_datasets_py/logic/modal/codec.py",
          "ipfs_datasets_py/logic/modal/decompiler.py"
        ],
        "arm": "leanstral",
        "cluster_id": "lir-cluster-a3d46a0b4e660b31",
        "compiler_surface": "deontic.ir",
        "dedup_key": "leanstral-shadow-c7b5d47236779a3a-leanstral",
        "evidence_ids": [
          "dry-run-evidence-001",
          "dry-run-evidence-002",
          "dry-run-evidence-003",
          "dry-run-evidence-004",
          "dry-run-evidence-005"
        ],
        "leanstral_enabled": true,
        "mutation_cases": [
          "invert_modality",
          "remove_exception"
        ],
        "pair_id": "leanstral-seed-pair-b70235a1bbfb94c6",
        "rank": 5,
        "requires_local_validation": true,
        "sample_ids": [
          "dry-run-sample-001",
          "dry-run-sample-002",
          "dry-run-sample-003",
          "dry-run-sample-004",
          "dry-run-sample-005"
        ],
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "semantic_family": "deontic",
        "semantic_signature": "deontic:synthesis_focus_gap:deontic->temporal:obligation_scope",
        "source": "leanstral_seed_canary",
        "target_component": "deontic.ir",
        "target_metrics": [
          "deontic_decoder_slot_loss",
          "legal_ir_view_cross_entropy_loss"
        ],
        "theorem_templates": [
          "modal_operator_preserved",
          "exception_scope_preserved"
        ],
        "todo_id": "leanstral-seed-pair-b70235a1bbfb94c6-leanstral",
        "validation_commands": [
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
          "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q"
        ]
      },
      "pair_id": "leanstral-seed-pair-b70235a1bbfb94c6",
      "paired_metrics_provenance": {
        "kind": "synthetic_projection",
        "metric_record_count": 5,
        "observed_improvement_eligible": false,
        "production_evidence_eligible": false,
        "synthetic_projection": true
      },
      "rank": 5,
      "sample_ids": [
        "dry-run-sample-001",
        "dry-run-sample-002",
        "dry-run-sample-003",
        "dry-run-sample-004",
        "dry-run-sample-005"
      ],
      "seeded": false,
      "semantic_family": "deontic",
      "semantic_signature": "deontic:synthesis_focus_gap:deontic->temporal:obligation_scope",
      "verification_reasons": [],
      "verified": true
    }
  ],
  "throughput_improvement": 0.0,
  "throughput_materially_improved": false,
  "todo_queue_path": "workspace/leanstral-seed-canary/todos.jsonl",
  "verified_task_count": 5
}
```
