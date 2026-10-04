# Hybrid Legal WS9 IR-CNL-Reasoner Implementation Tickets

## 1. Purpose

This backlog operationalizes the IR/CNL/reasoner integration blueprint into implementation-ready tickets with code targets, acceptance criteria, and test gates.

Reference spec:
- `docs/guides/legal_data/HYBRID_LEGAL_IR_CNL_REASONER_INTEGRATION_IMPROVEMENT_PLAN.md`

Scope assumptions:
1. WS8 contract and API hardening is complete.
2. V2 reasoner suite remains mandatory release gate.
3. All tickets preserve deterministic IDs, schema versions, and provenance.

## 2. How To Execute

1. Work one ticket at a time where possible.
2. Keep each change set testable with explicit gate command(s).
3. Do not relax deontic/temporal semantics to satisfy formatting-only goals.

## 3. Ticket Backlog

## HL-WS9-01: IR Grammar Lock and Parser Contract

Goal:
- Freeze near-EBNF IR grammar and align parser contract errors with stable machine-readable codes.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `docs/guides/legal_data/HYBRID_LEGAL_IR_CNL_REASONER_INTEGRATION_IMPROVEMENT_PLAN.md`
- `tests/reasoner/test_hybrid_v2_parse_replay.py`

Acceptance criteria:
1. Parser emits stable ambiguity/error code set for template collisions.
2. IR grammar section and parser behavior are aligned for all normative templates.
3. Strict mode continues to fail fast with actionable details.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## HL-WS9-02: Typed IR Dataclass and Canonical ID Registry v2.1

Goal:
- Expand or formalize typed IR dataclass coverage and canonical-ID utilities for entities/frames/norms/temporal constraints.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/models.py`
- `tests/reasoner/test_hybrid_v2_blueprint.py`

Acceptance criteria:
1. Deterministic ID policy documented and enforced in code paths.
2. Canonicalization produces stable IDs across replay runs.
3. Contract validator catches missing refs and orphaned IDs.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS9-03: CNL Template Expansion and Deterministic Temporal Parsing

Goal:
- Finalize unambiguous CNL templates for norms, definitions, and temporal constraints (`by`, `within`, `before`, `after`, `during`).

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/fixtures/cnl_parse_replay_v2_corpus.json`
- `tests/reasoner/test_hybrid_v2_parse_replay.py`

Acceptance criteria:
1. At least 10 canonical templates parse deterministically.
2. Definition templates (`means`, `includes`) map to explicit IR definition objects.
3. Temporal extraction is normalized and comparable across paraphrases.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## HL-WS9-04: Compiler Fidelity Pass (IR -> DCEC)

Goal:
- Tighten DCEC compiler rendering for deontic wrappers around frame events and EC dynamics links.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/fixtures/compiler_parity_v2_cases.json`
- `tests/reasoner/test_hybrid_v2_compiler_parity.py`

Acceptance criteria:
1. Deontic operators always wrap target frame/event terms, not slot predicates.
2. Temporal guards are present where IR temporal refs exist.
3. Output remains deterministic for parity fixtures.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## HL-WS9-05: Compiler Fidelity Pass (IR -> Temporal Deontic FOL)

Goal:
- Align Temporal Deontic FOL output with normalized frame-level semantics and quantifier discipline.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/fixtures/compiler_parity_v2_cases.json`
- `tests/reasoner/test_hybrid_v2_compiler_parity.py`

Acceptance criteria:
1. Free variables are quantified deterministically.
2. Temporal predicates preserve relation semantics from IR.
3. Parity assertions confirm no deontic-target drift vs DCEC output.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_compiler_parity.py -q`

## HL-WS9-06: Optimizer Hook Governance and Telemetry Hardening

Goal:
- Finalize optimizer acceptance/rejection semantics for canonical IR without semantic drift.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/optimizer_policy.py`
- `tests/reasoner/test_hybrid_v2_blueprint.py`

Acceptance criteria:
1. Rejection reasons are machine-readable and stable.
2. Optimizer cannot alter modality operator or target frame identity.
3. Decision envelope includes deterministic IDs and failure counts.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS9-07: KG Enrichment Hook with Reversible Frame Augmentation

Goal:
- Ensure KG enrichment remains additive, confidence-bounded, and reversible.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/kg_enrichment.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_kg_enrichment_adapter.py`

Acceptance criteria:
1. Enrichment writes include confidence and summary counters.
2. No semantic mutation of core normative frame meaning.
3. Rollback path removes only adapter-added data.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_kg_enrichment_adapter.py ipfs_datasets_py/tests/reasoner/test_hybrid_v2_blueprint.py -q`

## HL-WS9-08: Prover Backend Unification and Certificate Contract

Goal:
- Normalize theorem prover certificate envelopes and required payload keys across backends.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/prover_backends.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/test_prover_backend_registry.py`

Acceptance criteria:
1. Certificate payload keys satisfy backend matrix requirements.
2. Proof artifacts include backend, format, status, theorem, and assumptions.
3. Backend mismatch and malformed payloads fail with clear codes.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_prover_backend_registry.py -q`

## HL-WS9-09: Reasoner Query API Obligations and Proof Trace Completeness

Goal:
- Enforce proof obligations for `check_compliance`, `find_violations`, and `explain_proof`.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `ipfs_datasets_py/processors/legal_data/reasoner/v2_cli.py`
- `tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md`

Acceptance criteria:
1. Every proof step has `ir_refs` and provenance.
2. `explain_proof(format="nl")` reconstructs deterministic NL output.
3. Query APIs remain schema-stable and replay-safe.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py ipfs_datasets_py/tests/reasoner/test_hybrid_v2_cli.py -q`

## HL-WS9-10: CNL Round-Trip Regeneration Quality Pack

Goal:
- Build and validate reversible CNL/NL regeneration from IR for canonical legal templates.

Target files:
- `ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py`
- `tests/reasoner/fixtures/cnl_parse_paraphrase_equivalence_v2.json`
- `tests/reasoner/test_hybrid_v2_parse_replay.py`

Acceptance criteria:
1. Round-trip (`CNL -> IR -> NL`) is deterministic for canonical templates.
2. Lexicon overrides alter wording only, not semantic IDs.
3. Reconstructed NL remains explainable at proof-step granularity.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_parse_replay.py -q`

## HL-WS9-11: 8-Query Compliance/Violation/Conflict Regression Matrix

Goal:
- Lock expected behavior for compliance, violations, deadlines, exceptions, and conflicts.

Target files:
- `ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_IR_CNL_REASONER_INTEGRATION_IMPROVEMENT_PLAN.md`

Acceptance criteria:
1. Eight canonical query outcomes remain stable.
2. Proof root conclusions match expected semantics.
3. Violations/conflicts are machine-readable and deterministic.

Test gate:
- `PYTHONPATH=src:ipfs_datasets_py .venv/bin/python -m pytest ipfs_datasets_py/tests/reasoner/test_hybrid_v2_query_api_matrix.py -q`

## HL-WS9-12: CI and Release Gate Integration for IR-CNL-Reasoner Program

Goal:
- Operationalize WS9 with CI matrix checks and checklist evidence outputs.

Target files:
- `ipfs_datasets_py/.github/workflows/legal-v2-reasoner-ci.yml`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`
- `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md`

Acceptance criteria:
1. CI includes stable WS9 regression gates.
2. Checklist evidence paths are documented and repeatable.
3. Local parity commands remain aligned with workflow behavior.

Test gate:
- Workflow dispatch + local parity smoke and pytest artifacts.

## 4. Dependency Order

Recommended order:
1. `HL-WS9-01` -> `HL-WS9-02` -> `HL-WS9-03`
2. `HL-WS9-04` and `HL-WS9-05`
3. `HL-WS9-06`, `HL-WS9-07`, `HL-WS9-08`
4. `HL-WS9-09`, `HL-WS9-10`, `HL-WS9-11`
5. `HL-WS9-12`

Parallel-safe groups:
- (`HL-WS9-06`, `HL-WS9-07`, `HL-WS9-08`) after compiler stability
- (`HL-WS9-10`, `HL-WS9-11`) after API/proof contract lock

## 5. Definition of Done for WS9

Program-level done conditions:
1. All WS9 tickets are complete with passing test gates.
2. No unresolved schema drift in query/proof and compiler outputs.
3. Deterministic replay checks pass for parser, compiler, and proof artifacts.
4. CI and local release checklist evidence are green and linked.
