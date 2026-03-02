# Hybrid Legal V2 Execution Workstreams

## 1. Purpose

This document converts the comprehensive architecture plan into execution-ready workstreams with concrete file/function targets, acceptance criteria, and test gates.

Reference specs:
- `HYBRID_LEGAL_COMPREHENSIVE_IMPROVEMENT_PLAN.md`
- `HYBRID_LEGAL_V2_OPTIMIZER_KG_PROVER_INTEGRATION_PLAN.md`

## 2. Current Baseline (Already Implemented)

Primary implementation anchors:
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/v2_cli.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/__init__.py`

Key functions/classes present now:
- `parse_cnl_to_ir`
- `normalize_ir`
- `compile_ir_to_dcec`
- `compile_ir_to_temporal_deontic_fol`
- `generate_cnl_from_ir`
- `check_compliance`
- `find_violations`
- `explain_proof`
- `run_v2_pipeline`
- `run_v2_pipeline_with_defaults`
- `DefaultOptimizerHookV2`
- `DefaultKGHookV2`
- `RegistryProverHookV2`

Current tests:
- `tests/reasoner/test_hybrid_v2_blueprint.py`
- `tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `tests/reasoner/test_hybrid_v2_cli.py`

## 3. Workstream Overview

WS1. IR Contract Hardening
WS2. CNL Grammar and Ambiguity Control
WS3. Compiler Parity and Formula Fidelity
WS4. Optimizer and KG Drift Safety
WS5. Prover Integration and Proof Object Canonicalization
WS6. Query Services and Explanations
WS7. Operationalization and CI Enforcement

---

## 4. WS1: IR Contract Hardening

Goal:
- Make the IR schema stable, explicit, and fully versioned for long-term composability.

Target files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/serialization.py`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_COMPREHENSIVE_IMPROVEMENT_PLAN.md`

Implementation checklist:
1. Add explicit `source_ref` to `NormV2` dataclass and enforce non-empty at parse time.
2. Add deterministic canonical ID utilities for all major IR nodes in a dedicated helper section.
3. Add IR version compatibility validator in `serialization.py` for V2 payloads.
4. Add strict schema assertion helper for test usage (`assert_ir_v2_contract`).

Definition of done:
- IR objects fail fast on missing IDs/provenance in strict mode.
- V2 schema compatibility helper returns actionable error strings.

Test gates:
- Extend `tests/reasoner/test_hybrid_v2_blueprint.py` with contract-validation cases.

---

## 5. WS2: CNL Grammar and Ambiguity Control

Goal:
- Ensure deterministic CNL parsing and bounded ambiguity handling.

Target files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/cnl_parse_replay_corpus.json`

Implementation checklist:
1. Expand parser template coverage for definitions (`means`, `includes`) and temporal forms.
2. Add ambiguity codes for repeated/competing markers (`if/when`, `unless/except`).
3. Add parser confidence/diagnostic payload for successful parse paths.
4. Add replay corpus tests for 10 canonical CNL templates.

Definition of done:
- Deterministic parse output for canonical CNL templates.
- Ambiguous cases produce predictable error codes and no silent fallback.

Test gates:
- Parser replay corpus fully green.

---

## 6. WS3: Compiler Parity and Formula Fidelity

Goal:
- Align DCEC and Temporal Deontic FOL outputs to shared semantics over the same IR.

Target files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/dcec_conformance_cases.json`
- `ipfs_datasets_py/tests/reasoner/fixtures/tdfol_conformance_cases.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py`

Implementation checklist:
1. Normalize temporal relation rendering consistency (`BY`, `WITHIN`, `BEFORE`, `AFTER`, `DURING`).
2. Add compiler parity checker helper that compares deontic target references and guard structures.
3. Add conformance fixtures for 5 legal sentence families (obligation/permission/prohibition + condition + temporal).
4. Add regression tests asserting parity constraints.

Definition of done:
- No divergence in deontic target frame references between compiler outputs.
- Temporal guards are present and semantically aligned in both outputs.

Test gates:
- DCEC/TDFOL conformance fixtures pass.

---

## 7. WS4: Optimizer and KG Drift Safety

Goal:
- Enforce semantic drift policy for optimizer/KG hooks while keeping additive enrichments.

Target files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/optimizer_policy.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/kg_enrichment.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py`

Implementation checklist:
1. Harden optimizer acceptance checks with explicit rejection reasons in report.
2. Add KG enrichment cap assertions for relation growth and confidence floor.
3. Add shadow reports for accepted vs rejected enrichment paths.
4. Add tests for threshold boundary behavior (`drift_score`, `confidence_floor`).

Definition of done:
- Pipeline never applies hook proposals that violate configured drift policy.
- Reports always include machine-readable rejection rationale.

Test gates:
- Drift-threshold and enrichment-cap tests pass.

---

## 8. WS5: Prover Integration and Proof Canonicalization

Goal:
- Standardize proof artifacts across prover backends with reproducible IDs.

Target files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/prover_backends.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/models.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`

Implementation checklist:
1. Define canonical proof envelope fields: backend, assumptions, theorem, status, certificate.
2. Add deterministic proof-id policy derived from normalized proof steps.
3. Ensure proof refs include IR refs and source refs.
4. Add backend parity tests over mock backends.

Definition of done:
- Proof objects replay deterministically over same IR and event/fact inputs.
- `explain_proof` can reconstruct NL explanation from proof + IR references.

Test gates:
- Query matrix proof fields validated for all cases.

---

## 9. WS6: Query Services and Explanations

Goal:
- Finalize query APIs for compliance, violations, and explanation with consistent contracts.

Target files:
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/v2_cli.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_cli.py`

Implementation checklist:
1. Enforce response schema for `check_compliance`, `find_violations`, `explain_proof`.
2. Ensure every violation item includes `norm_id`, `frame_id`, and violation type.
3. Add explanation formats (`nl`, `json`) with stable field names.
4. Add query contract tests for 8 canonical queries.

Definition of done:
- API schemas are stable and validated in test assertions.
- NL explanation clearly references legal rule and source sentence context.

Test gates:
- 8-query API matrix remains green with schema assertions.

---

## 10. WS7: Operationalization and CI Enforcement

Goal:
- Keep local tasks and CI execution paths aligned and lightweight.

Target files:
- `ipfs_datasets_py/.vscode/tasks.json`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`
- `ipfs_datasets_py/.github/workflows/` (new dedicated V2 workflow file)

Implementation checklist:
1. Keep VS Code tasks for:
- fixture batch pipeline run,
- V2 full reasoner suite,
- V2 CLI-only fast suite.
2. Add dedicated CI workflow that runs V2 suite on PR/push paths relevant to reasoner and docs.
3. Add runbook section for local/CI parity command set.
4. Add minimal artifacts upload for failed runs (test log only).

Definition of done:
- Local task command equals CI command semantics.
- CI workflow provides deterministic pass/fail signal for V2 stack.

Test gates:
- Workflow lint passes and can execute suite command successfully.

---

## 11. Cross-Workstream Risk Controls

1. Semantic drift guard:
- Any optimizer/KG change rejected when drift constraints fail.

2. Provenance guard:
- Source references must be preserved from parse to proof.

3. Determinism guard:
- Stable IDs, stable parser output, stable proof IDs.

4. Backward-compat guard:
- Existing V2 tests remain green at each workstream boundary.

## 12. Recommended Execution Order and Milestones

Milestone M1:
- WS1 + WS2 complete (IR contract + deterministic CNL parsing)

Milestone M2:
- WS3 + WS4 complete (compiler parity + drift-safe hooks)

Milestone M3:
- WS5 + WS6 complete (proof standardization + query contract hardening)

Milestone M4:
- WS7 complete (CI enforcement and operational parity)

## 13. Definition of Program Completion

Program is complete when:
- All workstream DoD criteria are met,
- V2 suite is green locally and in CI,
- Proof objects are reproducible and source-traceable,
- CNL -> IR -> Logic -> Proof -> NL loop is stable for canonical scenarios.

## 14. WS8 Ticket-to-Test Traceability Matrix

| Ticket | Primary tests | CI / gate |
|---|---|---|
| `HL-WS8-01` | `tests/reasoner/test_hybrid_v2_query_api_matrix.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-02` | `tests/reasoner/test_hybrid_v2_blueprint.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-03` | `tests/reasoner/test_hybrid_v2_parse_replay.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-04` | `tests/reasoner/test_hybrid_v2_compiler_parity.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-05` | `tests/reasoner/test_hybrid_v2_blueprint.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-06` | `tests/reasoner/test_kg_enrichment_adapter.py`, `tests/reasoner/test_hybrid_v2_blueprint.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-07` | `tests/reasoner/test_prover_backend_registry.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-08` | `tests/reasoner/test_hybrid_v2_query_api_matrix.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-09` | `tests/reasoner/test_hybrid_v2_cli.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-10` | `tests/reasoner/test_hybrid_v2_blueprint.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-11` | `tests/reasoner/test_hybrid_v2_parse_replay.py` | `Legal V2 Reasoner CI` suite |
| `HL-WS8-12` | `.github/workflows/legal-v2-reasoner-ci.yml` backend smoke matrix | workflow dispatch run + CI logs |
| `HL-WS8-13` | `scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py` smoke run | local ops task or CI smoke |
| `HL-WS8-14` | documentation diagnostics clean | docs review + diagnostics |
| `HL-WS8-15` | checklist dry-run in PR description | release review gate |
