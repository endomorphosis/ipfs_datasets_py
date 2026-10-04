# Hammer/Leanstral External Validity Promotion Report

- Task: `PORTAL-LIR-HAMMER-084`
- Gate schema: `legal-ir-hammer-leanstral-external-validity-promotion-v1`
- Gate command: `scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py external-validity-gate`
- Default decision: fail closed

## Promotion Contract

The final Hammer/Leanstral rollout promotion is allowed only when one evidence envelope binds all external-validity packets listed below. A missing packet, unsupported schema, blocked status, metric regression, stale binding, or rollback-readiness gap blocks promotion.

| Evidence domain | Required proof |
| --- | --- |
| `leak_free_splits` | `legal-ir-eval-splits-v1` evidence must authorize representation promotion without protected split leakage. |
| `semantic_metrics` | `legal-ir-semantic-equivalence-metrics-v1` must include complete structural, deontic, counterexample, graph, temporal, decompiler, and proof-obligation scores at threshold. |
| `typed_decoding` | `legal-ir-typed-grammar-decoder-v1` must show typed grammar acceptance, zero rejection evidence, and no source-copy placeholder penalty. |
| `uncertainty` | `legal-ir-uncertainty-v1` must permit promotion with no blocked, unsupported, or failed families. |
| `fuzzing` | `legal-ir-metamorphic-differential-fuzzing-v1` must pass metamorphic/differential fuzzing and emit trusted negatives. |
| `hard_negatives` | `legal-ir-hard-negative-effect-v1` or curriculum evidence must reduce semantic-equivalence false positives while preserving trusted positives. |
| `multi_seed_statistics` | `legal-ir-hammer-leanstral-multi-seed-promotion-v1` is recomputed by the rollout gate and must pass paired confidence intervals. |
| `schema_compatibility` | `legal-ir-schema-evolution-v1` compatibility evidence must be reusable and free of error issues. |
| `poisoning_defenses` | `legal-ir-premise-security-v1` must bind the rule `legal_source_text_is_data_not_instructions` and prove poisoned payloads are rejected before training, proof, or promotion. |
| `external_benchmark_scores` | `legal-ir-external-benchmark-report-v1` must pass expert benchmark packets separately from internal canary metrics. |
| `rollback_readiness` | Drift monitor or rollback metadata must prove promoted learned guidance is reversible and no rollback is already required. |

## Binding Requirements

The evidence envelope must include `evidence_bindings` for:

- `promotion_id`
- `compiler_commit`
- `source_export_id`
- `fixed_canary_id`
- `split_manifest_digest`

Any packet that declares one of these identifiers must match the envelope. The gate reports every source used for a binding, so stale canary, split, export, or compiler evidence cannot be silently mixed into a promotion.

## Operator Command

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python \
  scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py external-validity-gate \
  --evidence-path workspace/legal_ir/external_validity_evidence.json \
  --evidence-output workspace/legal_ir/external_validity_decision.json \
  --report-output docs/implementation/reports/HAMMER_LEANSTRAL_EXTERNAL_VALIDITY_REPORT.md
```

The command exits `0` only when the promotion is accepted. It exits non-zero and publishes the blocking failures when any required evidence is absent or inconsistent.

## Current Implementation

The gate is implemented in `scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py` as `external_validity_promotion_gate`. The CLI can also render a fresh Markdown decision report with `render_external_validity_report`.
