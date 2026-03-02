# Hybrid Legal WS11 V3 Integration Implementation Tickets

## 1. Purpose

This backlog operationalizes the V3 architecture plan into implementation-ready tickets for code, tests, and operations.

Reference spec:
- `docs/guides/legal_data/HYBRID_LEGAL_V3_IR_CNL_REASONER_OPTIMIZER_KG_PROVER_PLAN.md`

Scope assumptions:
1. WS9 feature closure is complete and WS10 stabilization remains active.
2. V2 reasoner APIs stay backward compatible while V3 surfaces are added.
3. Deterministic IDs, schema versions, and provenance are mandatory.

## 2. How To Execute

1. Execute in dependency order where possible.
2. Keep each ticket independently testable.
3. Preserve modal/temporal scope discipline (wrappers external to predicates).
4. Reject semantic drift from optimizer/KG/prover hooks by policy gates.

Issue body templates:
- `docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_01_06.md`
- `docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_07_12.md`

Bulk issue kickoff:
- Dry-run: `bash ipfs_datasets_py/scripts/ops/legal_data/create_ws11_github_issues.sh`
- Create: `bash ipfs_datasets_py/scripts/ops/legal_data/create_ws11_github_issues.sh --create`

Created issues (2026-03-02):
- Meta tracker: https://github.com/endomorphosis/ipfs_datasets_py/issues/1176
- `HL-WS11-01`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1164
- `HL-WS11-02`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1165
- `HL-WS11-03`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1166
- `HL-WS11-04`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1167
- `HL-WS11-05`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1168
- `HL-WS11-06`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1169
- `HL-WS11-07`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1170
- `HL-WS11-08`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1171
- `HL-WS11-09`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1172
- `HL-WS11-10`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1173
- `HL-WS11-11`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1174
- `HL-WS11-12`: https://github.com/endomorphosis/ipfs_datasets_py/issues/1175

## 3. Ticket Backlog

## HL-WS11-01: V3 IR Schema Lock + Validator

Goal:
- Implement and freeze V3 IR schema contract (typed frames, norms, temporals, definitions, sources).

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/models.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/serialization.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py`

Acceptance criteria:
1. V3 schema validator rejects missing refs, orphan IDs, and invalid operators.
2. Deterministic canonical ID policy implemented for `ent`, `frm`, `tmp`, `nrm`, `src`.
3. Backward compatibility loader maps existing V2 payloads into valid V3 shape.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS11-02: CNL Grammar Hardening + Ambiguity Diagnostics

Goal:
- Enforce unambiguous CNL templates for norms/definitions/temporal clauses with stable parse error codes.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/cnl_parse_replay_v2_corpus.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py`

Acceptance criteria:
1. All normative templates (`shall`, `shall not`, `may`) parse deterministically.
2. Definition templates (`means`, `includes`) emit definition IR objects.
3. Ambiguous sentences fail with stable machine-readable codes and candidate traces.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## HL-WS11-03: Temporal Constraint Normalization Pack

Goal:
- Normalize `by`, `within`, `before`, `after`, `during` as external temporal objects with anchor discipline.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/compiler_parity_v2_cases.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py`

Acceptance criteria:
1. Temporal objects are not embedded inside target predicate argument lists.
2. Anchor resolution is deterministic for event/time references.
3. Temporal normalization is consistent across paraphrase variants.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## HL-WS11-04: Compiler V3 Pass (IR -> DCEC)

Goal:
- Compile V3 IR to DCEC/Event Calculus formulas with deontic wrappers over frame references.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py`

Acceptance criteria:
1. Deontic operators always wrap `FrameRef(...)` terms.
2. Event calculus primitives (`Happens`, `Initiates`, `Terminates`, `HoldsAt`) emitted for dynamic cases.
3. Temporal guards are applied as external guards, not predicate arity expansion.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## HL-WS11-05: Compiler V3 Pass (IR -> Temporal Deontic FOL)

Goal:
- Compile V3 IR to quantifier-normalized Temporal Deontic FOL with parity against DCEC semantics.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py`

Acceptance criteria:
1. Free variables are deterministically quantified.
2. Deontic wrappers preserve frame-level target semantics.
3. Temporal constraints map to explicit temporal predicates with anchor consistency.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## HL-WS11-06: Round-Trip CNL/NL Regeneration Contract

Goal:
- Add deterministic IR -> CNL/NL generation with style-safe paraphrase mode.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/fixtures/cnl_parse_paraphrase_equivalence_v2.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py`

Acceptance criteria:
1. Round-trip chain is deterministic for canonical templates.
2. Paraphrase mode never changes modal or temporal scope.
3. Regeneration supports proof explanation reconstruction.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## HL-WS11-07: Optimizer Hook Semantic-Drift Gate v3

Goal:
- Enforce optimizer equivalence policy envelope (`equivalence_ok`, `drift_score`, reason codes).

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/optimizer_policy.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py`

Acceptance criteria:
1. Optimizer cannot mutate modality operator or target frame identity.
2. Drift threshold violations are rejected with deterministic telemetry.
3. Acceptance/rejection decisions are replay-stable across runs.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS11-08: KG Hook Additive Enrichment Policy v3

Goal:
- Ensure KG writes are additive/reversible with confidence and provenance summaries.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/kg_enrichment.py`
- `ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py`

Acceptance criteria:
1. KG enrichment never mutates canonical IDs.
2. Enrichment summary includes stable counters for links/writes/reverts.
3. Rollback removes adapter-added fields only.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py -q`

## HL-WS11-09: Prover Certificate Contract v3

Goal:
- Normalize theorem-prover envelopes and enforce proof-step traceability to IR and source text.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/prover_backends.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/serialization.py`
- `ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py`

Acceptance criteria:
1. Required certificate keys validated per backend family.
2. Every proof step includes non-empty `ir_refs` and provenance.
3. Deterministic proof hash and replay verification pass.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py -q`

## HL-WS11-10: API Semantics Expansion (Compliance + Violations + Explain)

Goal:
- Validate V3 semantics across required APIs: compliance, violations, exceptions, deadlines, conflicts.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md`

Acceptance criteria:
1. API outputs preserve schema stability and include proof IDs.
2. Conflict and exception precedence behavior is deterministic.
3. Explanation payload is reconstructable into natural language.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## HL-WS11-11: 10-Example CNL Transformation Regression Pack

Goal:
- Add fixture-driven regression for ten transformation chains (`CNL -> IR -> DCEC/TDFOL -> NL`).

Target files:
- `ipfs_datasets_py/tests/reasoner/fixtures/cnl_v3_transformation_cases.json`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py`
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py`

Acceptance criteria:
1. Ten canonical examples pass deterministic transformation checks.
2. First five examples validate both DCEC and TDFOL outputs.
3. Round-trip NL outputs remain stable in strict mode.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## HL-WS11-12: 8-Query Proof Matrix Closure + Ops Runbook Update

Goal:
- Lock the 8-query proof matrix and operationalize WS11 evidence collection.

Target files:
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md`

Acceptance criteria:
1. Eight query scenarios produce expected statuses and proof roots.
2. Runbook includes WS11 local parity + artifact paths.
3. TODO board references WS11 backlog and current sprint tracking.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## 4. Dependency Order

Recommended order:
1. `HL-WS11-01` -> `HL-WS11-02` -> `HL-WS11-03`
2. `HL-WS11-04` and `HL-WS11-05`
3. `HL-WS11-06`
4. `HL-WS11-07`, `HL-WS11-08`, `HL-WS11-09`
5. `HL-WS11-10`, `HL-WS11-11`, `HL-WS11-12`

Parallel-safe groups:
- (`HL-WS11-07`, `HL-WS11-08`, `HL-WS11-09`) after compiler baseline is stable.
- (`HL-WS11-11`, `HL-WS11-12`) after API semantics lock.

## 5. Definition of Done (WS11)

1. All WS11 tickets pass listed test gates.
2. V3 schema/CNL/compiler/reasoner contracts are deterministic and documented.
3. Optimizer/KG/prover hooks are policy-gated with no semantic drift.
4. 10-example transformation pack and 8-query proof matrix are green.
5. Runbook + TODO provide repeatable artifact-driven release evidence.
