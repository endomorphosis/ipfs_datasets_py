# Hybrid Legal Reasoning TODO

## WS11 Execution Board

### WS11 Sprint Backlog

| # | Issue | Title | Status |
|---|---|---|---|
| 1 | #1164 | HL-WS11-01: Lock V3 IR Schema and Deterministic ID Validator | ✅ Done |
| 2 | #1165 | HL-WS11-02: Harden CNL Grammar and Ambiguity Diagnostics for V3 | ✅ Done |
| 3 | #1166 | HL-WS11-03: Normalize Temporal Constraints as External V3 Objects | ✅ Done |
| 4 | #1167 | HL-WS11-04: Implement V3 DCEC Compiler Pass with FrameRef Deontic Wrapping | ✅ Done |
| 5 | #1168 | HL-WS11-05: Implement V3 Temporal Deontic FOL Compiler Pass | ✅ Done |
| 6 | #1169 | HL-WS11-06: Add Deterministic V3 Round-Trip CNL/NL Regeneration Contract | ✅ Done |
| 7 | #1170 | HL-WS11-07: Enforce V3 Optimizer Semantic-Drift Gate and Decision Envelope | ✅ Done |
| 8 | #1171 | HL-WS11-08: Enforce Additive/Reversible KG Enrichment Policy for V3 | ✅ Done |
| 9 | #1172 | HL-WS11-09: Normalize V3 Prover Certificate Contract and Proof Traceability | ✅ Done |
| 10 | #1173 | HL-WS11-10: Expand V3 API Semantics for Compliance/Violations/Explainability | ✅ Done |
| 11 | #1174 | HL-WS11-11: Add 10-Example V3 CNL Transformation Regression Pack | ✅ Done |
| 12 | #1175 | HL-WS11-12: Close 8-Query V3 Proof Matrix and Operationalize WS11 Evidence | ✅ Done |

### WS11 Evidence Artifacts

| Artifact | Status | Location |
|---|---|---|
| 108 passing tests | ✅ Green | `ipfs_datasets_py/tests/reasoner/` |
| CNL parse corpus (12 cases) | ✅ Present | `fixtures/cnl_parse_replay_v2_corpus.json` |
| Compiler parity fixture (7 cases) | ✅ Present | `fixtures/compiler_parity_v2_cases.json` |
| Paraphrase equivalence (5 groups) | ✅ Present | `fixtures/cnl_parse_paraphrase_equivalence_v2.json` |
| V3 transformation pack (10 cases) | ✅ Present | `fixtures/cnl_v3_transformation_cases.json` |
| API + proof schema docs | ✅ Present | `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md` |
| Operations runbook | ✅ Present | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` |
| V3 IR schema + validator | ✅ In `serialization.py` | `validate_v3_ir_payload`, `map_v2_payload_to_v3` |
| CNL parser + ambiguity diagnostics | ✅ In `hybrid_v2_blueprint.py` | `parse_cnl_to_ir_with_diagnostics` |
| Temporal external objects | ✅ In `hybrid_v2_blueprint.py` | `TemporalConstraintV2` as standalone IR node |
| DCEC compiler (FrameRef wrapping) | ✅ In `hybrid_v2_blueprint.py` | `compile_ir_to_dcec` |
| TDFOL compiler (time-quantified) | ✅ In `hybrid_v2_blueprint.py` | `compile_ir_to_temporal_deontic_fol` |
| Round-trip CNL generation | ✅ In `hybrid_v2_blueprint.py` | `generate_cnl_from_ir` |
| Optimizer semantic-drift gate | ✅ In `run_v2_pipeline` | `_semantic_invariant_failures`, `DefaultOptimizerHookV2` |
| KG enrichment additive/rollback | ✅ In `kg_enrichment.py` | `apply_kg_enrichment`, `rollback_kg_enrichment` |
| Prover certificate contract | ✅ In `prover_backends.py` | `normalize_prover_result`, `_validate_normalized_prover_envelope` |
| 8-query compliance matrix | ✅ In `test_hybrid_v2_query_api_matrix.py` | `TestEightQueryProofMatrix` |

## Post-WS11 Deferred Items

- [ ] Frontend explanation rendering integration (use `explain_proof` API output)
- [ ] Multi-norm conflict resolution priority semantics
- [ ] V3 IR JSON schema formalization (JSON Schema draft)
- [ ] Extended backend compatibility matrix (Isabelle, Lean 4)
- [ ] Temporal window query API (deadline/deadline-miss detection)
- [ ] Cross-jurisdiction norm merger policy
