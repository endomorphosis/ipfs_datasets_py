# Hammer/Leanstral LegalIR Compiler System Promotion

Task: PORTAL-LIR-HAMMER-100  
Track: rollout  
Status: implemented  
Gate: `scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py compiler-system-promotion-gate`

## Decision Contract

The final promotion is fail-closed. The compiler system may be promoted only when the evidence envelope proves all of these domains are complete, mutually bound to the same promotion identifiers, and rollback-ready:

| Domain | Required Evidence |
| --- | --- |
| evaluation integrity | Leak-free split guard, fixed canary, multi-seed evidence, hard-negative coverage, and no staged rollout blockers. |
| external validity | Accepted external-validity promotion decision covering external benchmarks, fuzzing, uncertainty, schema compatibility, poisoning defenses, and rollback. |
| compiler source maps | Valid `legal-ir-source-map-v1` traceability for source spans, compiler nodes, decompiler output, and proof artifacts. |
| symbols | Complete `legal-ir-symbol-table-v1` resolution with no unresolved production symbols. |
| citations | Complete `legal-ir-citation-linker-v1` resolution with no unresolved or ambiguous citations. |
| temporal authority | Complete temporal authority binding with no open authority conflicts or expired authority windows. |
| ambiguity | First-class ambiguity evidence with all promotion-blocking ambiguities resolved or routed away from learned labels. |
| pass management | Deterministic pass graph/replay evidence preserving source maps and declared invalidation contracts. |
| backend conformance | Accepted backend conformance report with no silent obligation drops or promotion blockers. |
| reproducible builds | Build manifest with deterministic digests and reproducible compile output. |
| incremental compilation | Incremental compiler evidence proving cache correctness and invalidation validity. |
| semantic diffs | Semantic diff evidence with classified changes and no unclassified semantic deltas. |
| proof-carrying artifacts | Valid proof-carrying artifacts with trusted proof checks and native reconstruction evidence. |
| diagnostics | Structured diagnostics with LSP readiness and no open production errors. |
| APIs | Daemon-free CLI/API parity on stable JSON contracts. |
| interoperability | Interchange round-trip conformance with explicit lossy/lossless markers and unsupported diagnostics. |
| conformance evidence | End-to-end compiler conformance suite evidence for compile, proof, decompile, semantic diff, diagnostics, reproducibility, external benchmark isolation, hard negatives, source maps, backend conformance, and CLI/API behavior. |
| rollback readiness | Recorded rollback ID plus disable or restore action for the promoted compiler system. |

## Implementation

The final gate is exposed as `compiler_system_promotion_gate(payload, config=None)` and as a CLI subcommand:

```bash
python scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py \
  compiler-system-promotion-gate \
  --evidence-path workspace/rollout/compiler-system-promotion.json \
  --evidence-output workspace/rollout/compiler-system-decision.json \
  --report-output docs/implementation/reports/HAMMER_LEANSTRAL_LEGAL_IR_COMPILER_SYSTEM_PROMOTION.md
```

The gate composes persisted staged rollout and external-validity decisions when present, and recomputes those subgates from raw evidence envelopes when raw snapshots or external-validity packets are supplied. It also evaluates every compiler-productization evidence domain directly so a single headline `accepted` flag cannot bypass missing source maps, symbols, citations, authority, ambiguity, pass management, backend conformance, reproducibility, incremental compilation, semantic diffs, proof artifacts, diagnostics, APIs, interoperability, conformance evidence, or rollback metadata.

## Evidence Bindings

Promotion envelopes must bind the shared identifiers `promotion_id`, `compiler_commit`, `source_export_id`, `fixed_canary_id`, and `split_manifest_digest`. The gate rejects mismatches across evaluation integrity, external validity, conformance, and rollback packets.

## Rollback

Rollback readiness is mandatory. Evidence must include a rollback identifier and either a disable action or restorable rollback metadata. If the staged rollout or external-validity decision is supplied as a subgate decision, their rollback evidence is included in the final decision metrics, but explicit top-level rollback evidence remains the preferred operator artifact.

## Validation

Primary validation command:

```bash
/home/barberb/portland-laws.github.io/ipfs_datasets_py/.venv-cuda/bin/python -m pytest tests/unit/optimizers/logic_theorem_optimizer/test_compiler_system_promotion_gate.py tests/conformance/legal_ir/test_legal_ir_compiler_conformance.py -q
```

