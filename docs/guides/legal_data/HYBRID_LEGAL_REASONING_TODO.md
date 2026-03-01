# Hybrid Legal Reasoning TODO

Use this as the working execution checklist for the hybrid legal IR/CNL/reasoner program.

Status legend:
- `[ ]` not started
- `[-]` in progress
- `[x]` done
- `[!]` blocked

## Phase A: Contract and Schema
- [x] Freeze `ir_version=1.0` and `cnl_version=1.0` in code-level validators. (2026-03-01)
- [x] Add backward-compat fixture loader for existing `logic.hybrid.jsonld` artifacts. (2026-03-01)
- [x] Add schema checksum snapshot tests for core IR dataclasses. (2026-03-01)
- [x] Define canonical ID policy docstring contract (inputs, normalization, hash policy). (2026-03-01)

## Phase B: Parser and CNL
- [x] Implement strict CNL mode (`fail_on_ambiguity=True`). (2026-03-01)
- [x] Implement parse alternative ranking with confidence scores. (2026-03-01)
- [x] Add parser confidence fields on emitted norms/frames. (2026-03-01)
- [x] Add deterministic parse replay tests from fixed CNL corpus. (2026-03-01)
- [x] Add CNL definition templates (`means`, `includes`) parser support. (2026-03-01)

## Phase C: Normalization
- [x] Implement role alias normalization (`subject->agent`, `object->patient`). (2026-03-01)
- [x] Normalize verb/action lexical forms and temporal units. (2026-03-01)
- [ ] Add jurisdiction normalization policy (`Federal`, `State:<code>`, `Agency:<name>`).
- [ ] Add canonical predicate naming mode (`Act_<hash>`).
- [ ] Add ID-stability tests across repeated parse-normalize runs.

## Phase D: Compilers
- [ ] Implement DCEC compiler module with EC primitives (`Happens`, `Initiates`, `Terminates`, `HoldsAt`).
- [ ] Implement Temporal Deontic FOL compiler with quantifier normalization.
- [ ] Implement compiler provenance index (`formula_ref -> ir_refs -> source`).
- [ ] Add compiler parity fixture tests (IR to expected DCEC/TDFOL outputs).
- [ ] Add differential report tool for DCEC vs TDFOL inconsistencies.

## Phase E: Proof Objects and Explainability
- [ ] Implement normalized `ProofObject` schema.
- [ ] Add deterministic proof hash/ID policy.
- [ ] Implement proof replay validation (`proof_id` reproducibility).
- [ ] Implement `explain_proof(..., format="nl")` renderer.
- [ ] Ensure all proof steps include `ir_refs` and source provenance.

## Phase F: Optimizers
- [ ] Add optimizer chain orchestration (`post_parse`, `post_compile`).
- [ ] Add semantic floor guards per modality.
- [ ] Add acceptance policy (`gain >= threshold`, no floor regressions).
- [ ] Add optimizer audit log records for accepted/rejected candidates.
- [ ] Add benchmark suite for optimizer on/off comparisons.

## Phase G: Knowledge Graph Integration
- [ ] Implement entity-linking adapter from IR entities to KG IDs.
- [ ] Implement relation enrichment adapter for frame roles.
- [ ] Implement confidence-scored enrichment writes.
- [ ] Add reversible enrichment layer (can disable/remove KG additions).
- [ ] Add KG drift tests to prevent noisy relation explosion.

## Phase H: Theorem Provers
- [ ] Define `ProverBackend` interface and backend registry.
- [ ] Implement backend adapter #1 (SMT style).
- [ ] Implement backend adapter #2 (first-order prover style).
- [ ] Implement proof certificate normalization and storage.
- [ ] Implement certificate-to-IR trace mapping.

## Phase I: Query APIs
- [ ] Implement `check_compliance(query, time_context)` end-to-end.
- [ ] Implement `find_violations(state, time_range)` end-to-end.
- [ ] Implement `explain_proof(proof_id, format="nl")` end-to-end.
- [ ] Add conflict detection (`O` vs `F` overlap) in compliance flow.
- [ ] Add deadline and interval reasoning checks in violation flow.

## Phase J: Test Matrix (8 Queries)
- [ ] Q1 compliant wages-within-window.
- [ ] Q2 wages deadline violation.
- [ ] Q3 prohibited disclosure violation.
- [ ] Q4 exception-applied disclosure.
- [ ] Q5 late breach-notification violation.
- [ ] Q6 no violation when filed before deadline.
- [ ] Q7 modal conflict detection (`O` and `F` overlap).
- [ ] Q8 proof explanation reconstruction checks.

## Phase K: Rollout
- [ ] Shadow mode: run hybrid reasoner in parallel and compare outputs.
- [ ] Canary mode: low-risk query routing with proof audits.
- [ ] GA gate: pass quality, safety, and latency thresholds.
- [ ] Publish API + proof schema docs.
- [ ] Update operations runbook for optimizer/KG/prover toggles.

## Current Focus
- [-] Keep docs and implementation aligned while migration routes through `ipfs_datasets_py`.
- [x] Phase A baseline completed (`A1`-`A4`) with tests/docs. (2026-03-01)

## Execution Order (Dependency-Aware)

Follow this order to avoid rework:
1. Phase A (contracts) before parser/compiler changes.
2. Phase B + Phase C before Phase D (compilers rely on normalized IR).
3. Phase D + Phase E before Phase I (query APIs require stable proof objects).
4. Phase F/G/H can run partially in parallel after Phase D baseline is stable.
5. Phase J test matrix must run before Phase K rollout gates.

Blocking dependencies:
- `check_compliance` depends on: A, B, C, D, E.
- `find_violations` depends on: A, B, C, D, E.
- `explain_proof` depends on: E and NL regeneration path from B/C.
- KG enrichment (G) depends on canonical entity/frame contracts from A/C.
- Prover adapters (H) depend on deterministic compiler outputs from D.

## Now / Next / Later Board

### Now (active sprint)
- [x] A1 Freeze `ir_version=1.0` and `cnl_version=1.0` in runtime validators. (2026-03-01)
- [x] A2 Add backward-compat fixture loader for `logic.hybrid.jsonld`. (2026-03-01)
- [x] A3 Add schema checksum snapshot tests for IR dataclasses. (2026-03-01)
- [x] A4 Finalize canonical ID policy and hash-input contract docstrings. (2026-03-01)

### Next (queued)
- [x] B1 Strict CNL mode + ambiguity ranking. (2026-03-01)
- [x] C1 Role and temporal normalization. (2026-03-01)
- [x] D1 Initial DCEC compiler conformance fixture set. (2026-03-01)
- [x] D2 Temporal Deontic FOL compiler conformance fixture set. (2026-03-01)
- [x] D3 Compiler provenance index (`formula_ref -> ir_refs -> source`). (2026-03-01)
- [x] D4 Compiler parity fixture tests (`IR -> DCEC/TDFOL`). (2026-03-01)
- [x] E1 Normalized `ProofObject` schema. (2026-03-01)
- [x] E2 Deterministic proof hash/ID policy. (2026-03-01)
- [x] E3 Proof replay validation (`proof_id` reproducibility). (2026-03-01)
- [x] E5 Ensure all proof steps include `ir_refs` and source provenance. (2026-03-01)

### Later (after baseline green)
- [ ] F1 Optimizer acceptance policy and semantic floor gate.
- [ ] G1 KG linker/enricher adapter with reversible writes.
- [ ] H1 Prover backend adapters and certificate mapping.

## Sprint Cadence

Per sprint ceremony checklist:
- [ ] Select 3-6 TODO items with explicit acceptance checks.
- [ ] Mark selected items as `[-]` and add implementation notes below.
- [ ] Land code + tests + docs in the same sprint for each selected item.
- [ ] Run regression suite for phases touched.
- [ ] Mark completed items `[x]` with completion date.

## Implementation Notes Log

Use this section for short dated notes while executing TODO items.

- 2026-03-01: Created canonical plan and TODO tracker under `ipfs_datasets_py/docs/guides/legal_data/` and linked root compatibility stubs.
- 2026-03-01: Implemented `ir_version/cnl_version` runtime contract validation (`1.0`) and added legacy `logic.hybrid.jsonld` fixture loader with compatibility tests.
- 2026-03-01: Added IR dataclass schema checksum snapshot tests and documented canonical ID normalization/hash contract in `deterministic_id`.
- 2026-03-01: Added strict CNL ambiguity mode (`fail_on_ambiguity`), ranked modal parse alternatives, and parser confidence metadata on emitted frames/norms.
- 2026-03-01: Added deterministic CNL parse replay tests backed by a fixed corpus fixture and strict-mode replay rejection checks.
- 2026-03-01: Added CNL definition-template parsing (`means`, `includes`) emitting deterministic definition rules and coverage tests.
- 2026-03-01: Expanded `normalize_ir` for role alias canonicalization, action lexical normalization, and temporal duration unit normalization with dedicated tests.
- 2026-03-01: Added initial DCEC conformance fixture corpus and golden-output tests for representative obligation/prohibition/exception/permission cases.
- 2026-03-01: Added Temporal Deontic FOL conformance fixture corpus and golden-output tests for representative obligation/prohibition/exception/permission cases.
- 2026-03-01: Implemented deterministic compiler provenance index for DCEC/TDFOL outputs and added provenance shape/determinism tests.
- 2026-03-01: Added compiler parity fixtures asserting shared IR inputs compile to expected DCEC and TDFOL formulas, including replay-stability checks.
- 2026-03-01: Implemented normalized proof schema fields (`schema_version`, `proof_hash`, `created_at`), deterministic proof IDs/hashes, replay validation API, and fallback step provenance/IR refs with coverage tests.

## Definition of Ready (per TODO item)

Before starting an item:
- [ ] Scope is one sentence and testable.
- [ ] Target files/modules are identified.
- [ ] Acceptance test is specified.
- [ ] No unresolved upstream dependency.

## Definition of Done (per TODO item)

Before marking `[x]`:
- [ ] Code implemented.
- [ ] Tests added/updated and passing.
- [ ] Docs updated (if behavior or contract changed).
- [ ] Provenance/traceability preserved where applicable.
