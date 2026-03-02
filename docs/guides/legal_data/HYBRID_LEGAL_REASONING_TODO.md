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
- [x] Add jurisdiction normalization policy (`Federal`, `State:<code>`, `Agency:<name>`). (2026-03-01)
- [x] Add canonical predicate naming mode (`Act_<hash>`). (2026-03-01)
- [x] Add ID-stability tests across repeated parse-normalize runs. (2026-03-01)

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
- [x] Add optimizer chain orchestration (`post_parse`, `post_compile`). (2026-03-01)
- [x] Add semantic floor guards per modality. (2026-03-01)
- [x] Add acceptance policy (`gain >= threshold`, no floor regressions). (2026-03-01)
- [x] Add optimizer audit log records for accepted/rejected candidates. (2026-03-01)
- [x] Add benchmark suite for optimizer on/off comparisons. (2026-03-01)

## Phase G: Knowledge Graph Integration
- [x] Implement entity-linking adapter from IR entities to KG IDs. (2026-03-01)
- [x] Implement relation enrichment adapter for frame roles. (2026-03-01)
- [x] Implement confidence-scored enrichment writes. (2026-03-01)
- [x] Add reversible enrichment layer (can disable/remove KG additions). (2026-03-01)
- [x] Add KG drift tests to prevent noisy relation explosion. (2026-03-01)

## Phase H: Theorem Provers
- [x] Define `ProverBackend` interface and backend registry. (2026-03-01)
- [x] Implement backend adapter #1 (SMT style). (2026-03-01)
- [x] Implement backend adapter #2 (first-order prover style). (2026-03-01)
- [x] Implement proof certificate normalization and storage. (2026-03-01)
- [x] Implement certificate-to-IR trace mapping. (2026-03-01)

## Phase I: Query APIs
- [x] Implement `check_compliance(query, time_context)` end-to-end. (2026-03-01)
- [x] Implement `find_violations(state, time_range)` end-to-end. (2026-03-01)
- [x] Implement `explain_proof(proof_id, format="nl")` end-to-end. (2026-03-01)
- [x] Add conflict detection (`O` vs `F` overlap) in compliance flow. (2026-03-01)
- [x] Add deadline and interval reasoning checks in violation flow. (2026-03-01)

## Phase J: Test Matrix (8 Queries)
- [x] Q1 compliant wages-within-window. (2026-03-01)
- [x] Q2 wages deadline violation. (2026-03-01)
- [x] Q3 prohibited disclosure violation. (2026-03-01)
- [x] Q4 exception-applied disclosure. (2026-03-01)
- [x] Q5 late breach-notification violation. (2026-03-01)
- [x] Q6 no violation when filed before deadline. (2026-03-01)
- [x] Q7 modal conflict detection (`O` and `F` overlap). (2026-03-01)
- [x] Q8 proof explanation reconstruction checks. (2026-03-01)

## Phase K: Rollout
- [x] Shadow mode: run hybrid reasoner in parallel and compare outputs. (2026-03-01)
- [x] Canary mode: low-risk query routing with proof audits. (2026-03-01)
- [x] GA gate: pass quality, safety, and latency thresholds. (2026-03-01)
- [x] Publish API + proof schema docs. (2026-03-01)
- [x] Update operations runbook for optimizer/KG/prover toggles. (2026-03-01)

## Current Focus
- [-] Keep docs and implementation aligned while migration routes through `ipfs_datasets_py`.
- [x] Phase A baseline completed (`A1`-`A4`) with tests/docs. (2026-03-01)

## WS8 Execution Board (Active)

Source of truth for WS8 scope:
- `docs/guides/legal_data/HYBRID_LEGAL_WS8_IMPLEMENTATION_TICKETS.md`
- `docs/guides/legal_data/templates/HYBRID_LEGAL_WS8_ISSUE_BODIES_01_05.md`
- `docs/guides/legal_data/templates/HYBRID_LEGAL_WS8_ISSUE_BODIES_06_15.md`

Next program backlog (WS9 IR/CNL/Reasoner integration):
- `docs/guides/legal_data/HYBRID_LEGAL_IR_CNL_REASONER_INTEGRATION_IMPROVEMENT_PLAN.md`
- `docs/guides/legal_data/HYBRID_LEGAL_WS9_IR_CNL_REASONER_IMPLEMENTATION_TICKETS.md`

Post-WS9 stabilization backlog (WS10):
- `docs/guides/legal_data/HYBRID_LEGAL_WS10_POST_WS9_STABILIZATION_TICKETS.md`

Next program backlog (WS11 V3 integration execution):
- `docs/guides/legal_data/HYBRID_LEGAL_V3_IR_CNL_REASONER_OPTIMIZER_KG_PROVER_PLAN.md`
- `docs/guides/legal_data/HYBRID_LEGAL_WS11_V3_INTEGRATION_IMPLEMENTATION_TICKETS.md`

## WS10 Execution Board (Active)

Current sprint (2026-03-02):
- [-] `HL-WS10-01` CI Soak Tracking for Release Gate. (started 2026-03-02)
- [x] `HL-WS10-02` Schema Drift Sentinel Regression Gate. (2026-03-02)
- [x] `HL-WS10-03` Release Evidence Pack Automation. (2026-03-02)
- [x] `HL-WS10-04` Release Checklist Canonical Template. (2026-03-02)

WS10 local evidence (2026-03-02):
- CI soak seed snapshot: `artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/CI_SOAK_SNAPSHOT_20260302.md`.
- CI soak runs JSON: `artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/ci_soak_runs_20260302.json`.
- CI soak summary JSON: `artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/ci_soak_summary_20260302.json`.
- CI soak summary markdown: `artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/CI_SOAK_SUMMARY_20260302.md`.
- CI soak snapshot alias: `artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/CI_SOAK_SNAPSHOT_20260302.md` (generated by automation).
- Current streak state: `0` consecutive green days (latest recorded run conclusion: `failure`).
- Schema sentinel local gate: `artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/pytest_schema_drift_sentinel_20260302.txt` (`2 passed`).
- Release evidence pack script: `ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_release_evidence_pack.sh`.
- Release evidence pack manifest: `artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/EVIDENCE_PACK_MANIFEST.txt`.
- Release evidence pack pytest gate: `artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/pytest_reasoner_release_gate.txt` (`68 passed`).
- Release evidence pack backend smoke: `artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/backend_smoke_mock_smt.json`, `artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/backend_smoke_mock_fol.json` (both `passed=true`).
- Release evidence pack batch smoke: `artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/hybrid_v2_cli_batch_smoke.json` (`total=4`, `ok=4`, `error=0`).
- Canonical checklist template: `ipfs_datasets_py/docs/guides/legal_data/templates/HYBRID_LEGAL_RELEASE_CHECKLIST_TEMPLATE.md`.
- WS10 checklist artifact: `artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/WS10_RELEASE_CHECKLIST_20260302.md`.
- Runbook tracking procedure: `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` (section `11) WS10 CI Soak Tracking`).
- CI soak automation script: `ipfs_datasets_py/scripts/ops/legal_data/run_legal_v2_ci_soak_snapshot.sh`.
- CI soak summary builder: `ipfs_datasets_py/scripts/ops/legal_data/collect_legal_v2_ci_soak_snapshot.py`.
- Runbook schema sentinel procedure: `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` (section `12) WS10 Schema Drift Sentinel`).
- Runbook evidence-pack procedure: `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` (section `13) WS10 Release Evidence Pack Automation`).

## WS11 Execution Board (Planned)

Current sprint seed (2026-03-02):
- [x] `HL-WS11-01` V3 IR Schema Lock + Validator. (2026-03-02)
- [x] `HL-WS11-02` CNL Grammar Hardening + Ambiguity Diagnostics. (2026-03-02)
- [x] `HL-WS11-03` Temporal Constraint Normalization Pack. (2026-03-02)
- [x] `HL-WS11-04` Compiler V3 Pass (IR -> DCEC). (2026-03-02)
- [x] `HL-WS11-05` Compiler V3 Pass (IR -> Temporal Deontic FOL). (2026-03-02)
- [x] `HL-WS11-06` Round-Trip CNL/NL Regeneration Contract. (2026-03-02)
- [x] `HL-WS11-07` Optimizer Hook Semantic-Drift Gate v3. (2026-03-02)
- [x] `HL-WS11-08` KG Hook Additive Enrichment Policy v3. (2026-03-02)
- [x] `HL-WS11-09` Prover Certificate Contract v3. (2026-03-02)
- [x] `HL-WS11-10` API Semantics Expansion (Compliance + Violations + Explain). (2026-03-02)
- [x] `HL-WS11-11` 10-Example CNL Transformation Regression Pack. (2026-03-02)
- [x] `HL-WS11-12` 8-Query Proof Matrix Closure + Ops Runbook Update. (2026-03-02)

WS11 local evidence (2026-03-02):
- WS11-01 gate: `PYTHONPATH=src:/home/barberb/municipal_scrape_workspace/ipfs_datasets_py /home/barberb/municipal_scrape_workspace/.venv/bin/python -m pytest tests/reasoner/test_hybrid_v2_blueprint.py -q`.
- WS11-01 result: `30 passed`.
- WS11-02 gate: `PYTHONPATH=src:. ../.venv/bin/python -m pytest tests/reasoner/test_hybrid_v2_parse_replay.py -q`.
- WS11-02 result: `13 passed`.
- WS11-03/04/05 gate: `PYTHONPATH=src:. ../.venv/bin/python -m pytest tests/reasoner/test_hybrid_v2_compiler_parity.py -q`.
- WS11-03/04/05 result: `6 passed`.
- WS11-06..12 gate: `PYTHONPATH=src:. ../.venv/bin/python -m pytest tests/reasoner/test_hybrid_v2_blueprint.py tests/reasoner/test_kg_enrichment_adapter.py tests/reasoner/test_prover_backend_registry.py tests/reasoner/test_hybrid_v2_query_api_matrix.py tests/reasoner/test_hybrid_v2_parse_replay.py tests/reasoner/test_hybrid_v2_compiler_parity.py -q`.
- WS11-06..12 result: `69 passed`.
- WS11-06..12 artifact: `artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/pytest_reasoner_ws11.txt` (`69 passed`).
- WS11 release evidence manifest: `artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/EVIDENCE_PACK_MANIFEST.txt`.
- WS11 release pytest gate: `artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/pytest_reasoner_release_gate.txt` (`73 passed`).
- WS11 release backend smoke: `artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/backend_smoke_mock_smt.json`, `artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/backend_smoke_mock_fol.json` (both `passed=true`).
- WS11 release batch smoke: `artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/hybrid_v2_cli_batch_smoke.json` (`total=4`, `ok=4`, `error=0`).
- WS11 checklist artifact: `artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/WS11_RELEASE_CHECKLIST_20260302.md`.
- V3 schema utilities: `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/serialization.py` (`SUPPORTED_V3_*`, `deterministic_v3_canonical_id`, `map_v2_payload_to_v3`, `validate_v3_ir_payload`).
- Package exports: `ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/__init__.py`.

WS11 source-of-truth backlog:
- `docs/guides/legal_data/HYBRID_LEGAL_WS11_V3_INTEGRATION_IMPLEMENTATION_TICKETS.md`

WS11 issue kickoff command:
- Dry-run: `bash ipfs_datasets_py/scripts/ops/legal_data/create_ws11_github_issues.sh`
- Create: `bash ipfs_datasets_py/scripts/ops/legal_data/create_ws11_github_issues.sh --create`

WS11 GitHub issues (created 2026-03-02):
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

## WS9 Execution Board (Active)

Current sprint (2026-03-02):
- [x] `HL-WS9-01` IR Grammar Lock and Parser Contract. (2026-03-02)
- [x] `HL-WS9-02` Typed IR Dataclass and Canonical ID Registry v2.1. (2026-03-02)
- [x] `HL-WS9-03` CNL Template Expansion and Deterministic Temporal Parsing. (2026-03-02)
- [x] `HL-WS9-04` Compiler Fidelity Pass (IR -> DCEC). (2026-03-02)
- [x] `HL-WS9-05` Compiler Fidelity Pass (IR -> Temporal Deontic FOL). (2026-03-02)
- [x] `HL-WS9-06` Optimizer Hook Governance and Telemetry Hardening. (2026-03-02)
- [x] `HL-WS9-07` KG Enrichment Hook with Reversible Frame Augmentation. (2026-03-02)
- [x] `HL-WS9-08` Prover Backend Unification and Certificate Contract. (2026-03-02)
- [x] `HL-WS9-09` Reasoner Query API Obligations and Proof Trace Completeness. (2026-03-02)
- [x] `HL-WS9-10` CNL Round-Trip Regeneration Quality Pack. (2026-03-02)
- [x] `HL-WS9-11` Query API Matrix Closure and Determinism Sweep. (2026-03-02)
- [x] `HL-WS9-12` CI/Runbook Operationalization and Evidence Pack. (2026-03-02)

WS9 local dry-run evidence (2026-03-02):
- Tests: `artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/pytest_reasoner_ws9.txt` (`68 passed`).
- Backend matrix parity: `artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_mock_smt.json`, `artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_mock_fol.json` (both `passed=true`).
- E2E fixture batch smoke: `artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/hybrid_v2_cli_batch_smoke.json` (`total=4`, `ok=4`, `error=0`).
- Standalone checklist: `artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/WS9_RELEASE_CHECKLIST_20260302.md`.
- CI gate updates: `ipfs_datasets_py/.github/workflows/legal-v2-reasoner-ci.yml` (added WS9 trigger paths and `test_kg_enrichment_adapter.py` to required suite).

Ready queue:

Current sprint (2026-03-02):
- [x] `HL-WS8-01` Contract Snapshot Lockfile. (2026-03-02)
- [x] `HL-WS8-02` IR Contract Error Code Registry. (2026-03-02)
- [x] `HL-WS8-04` Temporal Guard Conformance Expansion. (2026-03-02)
- [x] `HL-WS8-05` Optimizer Rejection Telemetry Envelope. (2026-03-02)
- [x] `HL-WS8-06` KG Enrichment Explainability Summary. (2026-03-02)
- [x] `HL-WS8-08` Query API JSON Schema Export. (2026-03-02)

Backlog (ready queue):
- [x] `HL-WS8-03` Parser Paraphrase Equivalence Corpus. (2026-03-02)
- [x] `HL-WS8-07` Prover Envelope Compatibility Table. (2026-03-02)
- [x] `HL-WS8-09` Batch CLI Summary Contract. (2026-03-02)
- [x] `HL-WS8-10` Proof Store Retention Policy. (2026-03-02)
- [x] `HL-WS8-11` CNL Lexicon Extension Hooks. (2026-03-02)
- [x] `HL-WS8-12` CI Workflow Matrix for Prover Backends. (2026-03-02)
- [x] `HL-WS8-13` Performance Baseline Snapshot. (2026-03-02)
- [x] `HL-WS8-14` Ticket-to-Test Traceability Table. (2026-03-02)
- [x] `HL-WS8-15` Release Readiness Checklist v2. (2026-03-02)

## WS8 Release Readiness Checklist v2

Use this checklist in PR descriptions before release/canary promotion.

Contracts:
- [ ] V2 query/proof contract snapshots are current.
- [ ] Contract error-code registry changes (if any) are documented.
- Artifact link: 

Tests:
- [ ] Required WS8 ticket test gates are green.
- [ ] No unresolved schema-drift failures.
- Artifact link: 

CI:
- [ ] `Legal V2 Reasoner CI` full suite is green.
- [ ] Prover backend smoke matrix (`mock_smt`, `mock_fol`) is green.
- Artifact link: 

Observability:
- [ ] Baseline timing artifact captured (`benchmark_hybrid_v2_reasoner.py`).
- [ ] Any performance regressions above threshold are triaged.
- Artifact link: 

Rollback:
- [ ] Rollback path for optimizer/KG/prover toggles is documented.
- [ ] Incident response conditions reviewed with release owner.
- Artifact link: 

WS8 local dry-run evidence (2026-03-02):
- Contracts: `ipfs_datasets_py/tests/reasoner/fixtures/hybrid_v2_api_schema_snapshot.json`, `ipfs_datasets_py/docs/guides/legal_data/schemas/v2_check_compliance.schema.json`, `ipfs_datasets_py/docs/guides/legal_data/schemas/v2_find_violations.schema.json`, `ipfs_datasets_py/docs/guides/legal_data/schemas/v2_explain_proof.schema.json`.
- Tests: `artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/pytest_reasoner_ws8.txt` (`52 passed`, no schema-drift failures).
- CI parity: `artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/backend_smoke_mock_smt.json`, `artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/backend_smoke_mock_fol.json` (both `passed=true`), plus workflow matrix in `ipfs_datasets_py/.github/workflows/legal-v2-reasoner-ci.yml`.
- Observability: `artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/hybrid_v2_perf_baseline.json`.
- Rollback references: `ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` (section `0) Hybrid V2 Pipeline CLI`, hook toggles and run commands).

WS8 done definition:
- [x] High-priority tickets (`01`, `02`, `04`, `05`, `06`, `08`, `09`, `10`, `12`) completed. (2026-03-02)
- [ ] `Legal V2 Reasoner CI` green on `main` for 7 consecutive days.
- [ ] No unresolved schema drift in query/proof envelopes.

Immediate next action:
- [x] Define next-program sprint backlog (post-WS9) and acceptance gates. (2026-03-02)
- [x] Start `HL-WS10-01` CI soak tracking workflow and add first evidence snapshot link. (2026-03-02)
- [ ] Continue daily `HL-WS10-01` CI soak tracking until `7 consecutive days green` is met.

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
- [x] D5 Differential report tool for DCEC vs TDFOL inconsistencies. (2026-03-01)
- [x] E1 Normalized `ProofObject` schema. (2026-03-01)
- [x] E2 Deterministic proof hash/ID policy. (2026-03-01)
- [x] E3 Proof replay validation (`proof_id` reproducibility). (2026-03-01)
- [x] E4 `explain_proof(..., format="nl")` renderer. (2026-03-01)
- [x] E5 Ensure all proof steps include `ir_refs` and source provenance. (2026-03-01)

### Later (after baseline green)
- [x] F1 Optimizer acceptance policy and semantic floor gate. (2026-03-01)
- [x] G1 KG linker/enricher adapter with reversible writes. (2026-03-01)
- [x] H1 Prover backend adapters and certificate mapping. (2026-03-01)

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
- 2026-03-01: Added deterministic compiler differential report (`compile_differential_report`) with per-norm consistency checks and mismatch diagnostics/tests.
- 2026-03-01: Implemented normalized proof schema fields (`schema_version`, `proof_hash`, `created_at`), deterministic proof IDs/hashes, replay validation API, and fallback step provenance/IR refs with coverage tests.
- 2026-03-01: Implemented deterministic NL proof renderer contract (`renderer_version`, `query_summary`, structured step narratives) with fixture-backed renderer tests.
- 2026-03-01: Added a dedicated Phase I/J 8-query fixture matrix (`wages`, `disclosure`, `breach`, conflict, and proof explanation) with end-to-end reasoner assertions for compliance, violations, and explainability.
- 2026-03-01: Added shadow-mode rollout harness (`run_formal_logic_shadow_mode.sh`) and machine-readable audit builder (`build_shadow_mode_audit.py` + `build_shadow_mode_audit(...)`) with gate checks and origin-count reporting; current sample audit reports one failing floor (`final_decoded_enumeration_integrity_mean`).
- 2026-03-01: Added canary routing policy (`build_canary_mode_decision`) and ops entrypoints (`select_formal_logic_canary_mode.py`, `run_formal_logic_canary_mode.sh`) to select baseline/hybrid route by risk level with proof-audit requirements.
- 2026-03-01: Added GA gate assessment policy (`build_ga_gate_assessment`) and ops entrypoints (`assess_formal_logic_ga_gate.py`, `run_formal_logic_ga_gate.sh`) for quality/safety/latency thresholds with optional runtime-latency stats mode.
- 2026-03-01: Published API/proof schema documentation and operations runbook for shadow/canary/GA controls, artifact interpretation, and rollout/rollback actions.
- 2026-03-01: Implemented optimizer acceptance policy with per-modality semantic floors, no-regression gain checks, and deterministic audit decisions (`build_optimizer_acceptance_decision`) plus ops assessment script.
- 2026-03-01: Added stage orchestration plan (`build_optimizer_chain_plan`) and chain runner scripts to apply `post_parse`/`post_compile` optimizer toggles in `run_formal_logic_regression_check.sh` via plan-driven env settings.
- 2026-03-02: Closed `HL-WS9-11` by extending query API determinism checks and preserving stable proof-trace behavior in matrix coverage (`tests/reasoner/test_hybrid_v2_query_api_matrix.py`).
- 2026-03-02: Closed `HL-WS9-12` by operationalizing WS9 evidence workflow in runbook, expanding `Legal V2 Reasoner CI` trigger/suite coverage, and generating local artifacts under `artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/`.
- 2026-03-01: Added optimizer on/off benchmark suite (`build_optimizer_onoff_benchmark`, benchmark assessment script, and `run_formal_logic_optimizer_benchmark.sh`) with deterministic comparison artifact output.
- 2026-03-01: Implemented KG entity-linking and role-relation enrichment adapters with confidence scoring plus reversible apply/rollback writes (`build_entity_link_adapter`, `build_relation_enrichment_adapter`, `apply_kg_enrichment`, `rollback_kg_enrichment`) and dedicated adapter tests.
- 2026-03-01: Added KG drift assessment guard (`build_kg_drift_assessment`) and tests to detect relation growth/relations-per-frame explosion.
- 2026-03-01: Added `ProverBackend` interface and `ProverBackendRegistry` with reference SMT/FOL mock backends plus registry tests (`create_default_prover_registry`).
- 2026-03-01: Implemented concrete theorem-prover adapters (`SMTStyleProverAdapter`, `FirstOrderProverAdapter`) with backend-specific certificate payload fields and registry coverage tests.
- 2026-03-01: Integrated deterministic proof certificate generation into reasoner proof storage, added normalized certificate payload/hash fields, and persisted certificate-to-IR trace mapping through serialization.
- 2026-03-01: Added jurisdiction normalization policy in `normalize_ir` (`Federal`, `State:<code>`, `Agency:<name>`) and expanded normalization tests for canonical predicate mode plus parse-normalize ID stability.
- 2026-03-01: Added ops exporter (`export_proof_certificates_audit.py`) plus runner (`run_formal_logic_proof_certificate_audit.sh`) to emit standalone proof certificate/trace-map audit artifacts.
- 2026-03-01: Added optional regression-run hook (`RUN_PROOF_CERT_AUDIT_AFTER_RUN=1`) in `run_formal_logic_regression_check.sh` to auto-export proof-certificate audit artifacts when a proof store is present.
- 2026-03-01: Updated canary runner to execute proof-certificate audit export when canary decision requires proof audit (`proof_audit_required=true`, toggle `RUN_PROOF_AUDIT_IF_REQUIRED=1`).
- 2026-03-01: Added fast smoke script (`run_formal_logic_canary_proof_audit_smoke.sh`) to validate canary proof-audit contract + export path with synthetic artifacts.
- 2026-03-01: Added fast smoke script (`run_formal_logic_regression_proof_audit_smoke.sh`) to validate regression proof-audit hook contract + export path with synthetic artifacts.
- 2026-03-01: Added aggregate smoke script (`run_formal_logic_proof_audit_integration_smoke.sh`) to run both proof-audit smoke paths and emit consolidated summary artifact output.
- 2026-03-01: Added workspace VS Code tasks for proof-audit smokes (`Legal smoke: proof-audit canary|regression|integration`) in `.vscode/tasks.json`.
- 2026-03-01: Added runbook section documenting VS Code task usage for proof-audit smoke labels plus expected artifacts and pass condition.
- 2026-03-01: Hardened integration smoke failure diagnostics (summary path + per-log tails) and documented smoke troubleshooting flow in operations runbook.
- 2026-03-01: Added machine-readable `error_code` and `failure_reasons` fields to proof-audit integration smoke summary for CI/alert routing.
- 2026-03-01: Added triage helper (`assess_formal_logic_proof_audit_integration_summary.py`) that maps `failure_reasons` to remediation commands and emits `triage.json`.
- 2026-03-01: Extended triage helper with `--format markdown` support to emit human-readable incident reports (`triage.md`), documented markdown invocation in runbook/README, and added VS Code task `Legal smoke: proof-audit triage (markdown)`.
- 2026-03-01: Updated integration smoke runner to auto-generate triage artifacts (`triage.json`, `triage.md`) after `summary.json` with env toggles for enable/disable and output paths.
- 2026-03-01: Added VS Code integration-smoke task variants for triage control (`json triage only`, `summary only`) to reduce manual env editing during CI/operator runs.
- 2026-03-01: Added matrix smoke orchestrator (`run_formal_logic_proof_audit_integration_matrix_smoke.sh`) and task to run all integration modes in one command and emit consolidated matrix report JSON.
- 2026-03-01: Completed scope-1 root->submodule task ownership migration: legal smoke tasks are canonical in `ipfs_datasets_py/.vscode/tasks.json`, root `.vscode/tasks.json` now excludes legal smoke ownership, and migration mapping was recorded in `ROOT_TO_SUBMODULE_SCOPE1_MANIFEST_2026-03-01.tsv`.
- 2026-03-01: Completed scope-2 reasoner migration: moved `src/municipal_scrape_workspace/hybrid_legal_ir.py` and `tests/reasoner/*` into canonical submodule locations (`ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/`, `ipfs_datasets_py/tests/reasoner/`), added a root compatibility shim, and recorded mapping in `ROOT_TO_SUBMODULE_SCOPE2_MANIFEST_2026-03-01.tsv`.
- 2026-03-01: Scope-3 progress: migrated remaining unmoved root ops analyzer (`analyze_formal_logic_entropy.py`) into canonical submodule scripts with root wrapper compatibility, and created `ROOT_TO_SUBMODULE_SCOPE3_MANIFEST_2026-03-01.tsv` documenting pointer docs plus deferred generated `data/state_laws/*/parsed/jsonld` artifact migration pending storage-policy decision.
- 2026-03-01: User decision: do not migrate `data/state_laws/*/parsed/jsonld` artifacts yet because state-law extraction/parsing is still actively being worked; keep this dataset in root workspace until that workstream stabilizes.
- 2026-03-01: Migrated canonical legal smoke task ownership from workspace root `.vscode/tasks.json` to `ipfs_datasets_py/.vscode/tasks.json`; root wrappers remain compatibility-only.
- 2026-03-02: Reviewed `HL-WS8-01` artifacts; confirmed fixture-backed query API schema snapshot lock test and snapshot fixture are present (`tests/reasoner/test_hybrid_v2_query_api_matrix.py`, `tests/reasoner/fixtures/hybrid_v2_api_schema_snapshot.json`).
- 2026-03-02: Local shell could not execute pytest (`pytest` unavailable in current PATH/interpreter); validation pending run in the project test environment.
- 2026-03-02: Started `HL-WS8-02`; added stable contract error-code registry + structured `IRContractValidationError` details/codes in `hybrid_v2_blueprint.py`, updated contract tests, and documented code set in the master integration plan.
- 2026-03-02: Started `HL-WS8-04`; expanded `compiler_parity_v2_cases.json` to 12 cases with temporal coverage counts `within/by/before/after/during = 2 each`, added fixture-coverage assertion test, and added `during X to Y` temporal extraction for interval guards.
- 2026-03-02: Started `HL-WS8-05`; normalized optimizer telemetry envelope in `run_v2_pipeline` with deterministic `decision_id`, explicit `rejected_reason_codes`, and `failure_count`, and added determinism/shape assertions in blueprint tests.
- 2026-03-02: Started `HL-WS8-06`; normalized `kg_report` summary counts (`entity_link_count`, `relation_candidate_count`, `entity_write_count`, `relation_write_count`) for accepted/rejected/no-hook paths and added assertions in blueprint/KG adapter tests.
- 2026-03-02: Started `HL-WS8-08`; added V2 query API schema artifacts under `docs/guides/legal_data/schemas/`, linked schema paths in API/proof docs, and added runtime required-key/type schema assertions in `test_hybrid_v2_query_api_matrix.py`.
- 2026-03-02: Started `HL-WS8-09`; stabilized CLI summary with `schema_version` + deterministic toggle/backend fields and added machine-readable `error_code` for error rows in `v2_cli.py` with coverage in `test_hybrid_v2_cli.py`.
- 2026-03-02: Started `HL-WS8-10`; implemented bounded in-memory V2 proof store with configurable capacity, deterministic oldest-first eviction, and explicit `explain_proof` behavior for evicted proof IDs (`evicted proof_id: ...`) plus retention tests.
- 2026-03-02: Started `HL-WS8-11`; added optional `lexicon_overrides` input for `generate_cnl_from_ir` (modal/predicate/entity/clause/temporal tokens) and tests showing rendering customization does not change canonical IDs and remains deterministic.
- 2026-03-02: Started `HL-WS8-12`; expanded `.github/workflows/legal-v2-reasoner-ci.yml` with `mock_smt/mock_fol` backend smoke matrix (primary full suite preserved) and added matching local parity smoke commands in the operations runbook.
- 2026-03-02: Started `HL-WS8-07`; documented prover backend compatibility matrix (payload key requirements per backend family) and added mandatory certificate payload key assertions in `test_prover_backend_registry.py`.
- 2026-03-02: Started `HL-WS8-03`; added `cnl_parse_paraphrase_equivalence_v2.json` and semantic signature assertions ensuring equivalent paraphrases match on norm operator + target-frame semantics + temporal relation, while non-equivalent pairs are explicitly asserted as non-equivalent.
- 2026-03-02: Started `HL-WS8-13`; added `scripts/ops/legal_data/benchmark_hybrid_v2_reasoner.py` to emit per-stage timing baseline artifacts and documented interpretation/threshold guidance in the execution playbook.
- 2026-03-02: Started `HL-WS8-14`; added copy/paste-ready WS8 ticket-to-test traceability matrices to execution workstreams and implementation tickets docs with explicit CI/gate mapping.
- 2026-03-02: Started `HL-WS8-15`; added release readiness checklist v2 with required artifact-link fields for contracts/tests/CI/observability/rollback.
- 2026-03-02: Validation checkpoint: targeted WS8 pytest suite passed (`52 passed`) across parse replay, prover registry, CLI, blueprint, compiler parity, query matrix, and KG adapter tests.
- 2026-03-02: Completed `HL-WS8-12`; captured local backend matrix smoke evidence for `mock_smt` and `mock_fol` (`passed=true`) under `artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/backend_smoke_*.json`.
- 2026-03-02: Completed `HL-WS8-15`; captured release-checklist dry-run evidence bundle under `artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/` (`pytest_reasoner_ws8.txt`, `hybrid_v2_perf_baseline.json`) and linked contract/rollback references.
- 2026-03-02: Completed `HL-WS9-01`; added structured `CNLParseError` with stable parse error codes (`V2_CNL_PARSE_EMPTY_SENTENCE`, `V2_CNL_PARSE_UNSUPPORTED_MODAL`, `V2_CNL_PARSE_AMBIGUOUS_MARKERS`), added prefix activation-clause support (`if/when ... , <normative clause>`), and validated parser gate (`tests/reasoner/test_hybrid_v2_parse_replay.py`: `9 passed`).
- 2026-03-02: Completed `HL-WS9-02`; added canonical ID registry validator (`validate_v2_canonical_id_registry`) + structured `IDRegistryValidationError` and stable ID-registry code set (`V2_IDREG_*`) for namespace/ref integrity checks, exported new contracts in package `__init__`, and validated parser/blueprint gates (`32 passed`).
- 2026-03-02: Completed `HL-WS9-03`; extended temporal parser with normalized `within <duration> of <anchor>` support, expanded replay corpus to 12 canonical templates, added paraphrase-equivalence cases for within-anchor and prefix-when forms, and added explicit tests for template coverage + definition object mapping + temporal normalization (`tests/reasoner/test_hybrid_v2_parse_replay.py`: `12 passed`).
- 2026-03-02: Completed `HL-WS9-04` and `HL-WS9-05`; preserved frame-ref deontic wrapping invariants in both compilers and fixed temporal guard fidelity by carrying `within` anchor semantics into compiler output (`Within(t,PT24H,incident_discovery)`), expanded compiler parity fixture corpus, and validated compiler gate (`tests/reasoner/test_hybrid_v2_compiler_parity.py`: `6 passed`).
- 2026-03-02: Completed `HL-WS9-06`; added optimizer semantic invariants rejecting candidate IR mutation of norm modality/target frame identity (`modality_changed`, `target_frame_changed`, `norm_set_changed`), included invariant failures in optimizer telemetry, and added regression tests proving mutation rejection (`tests/reasoner/test_hybrid_v2_blueprint.py`: `25 passed`).
- 2026-03-02: Completed `HL-WS9-07` and `HL-WS9-08`; applied the same semantic invariant guardrail to KG hook acceptance (rejecting frame/norm semantic mutations with machine-readable `invariant_failures`) and added strict normalized prover-envelope validation (schema/required fields/backend payload-key matrix) with backward-compatible coercion for legacy prover hooks, then validated blueprint + prover registry gates (`31 passed`).
- 2026-03-02: Completed `HL-WS9-09` and `HL-WS9-10`; enforced proof-store trace completeness (`steps`, `ir_refs`, `source_refs`) before persistence, added query-matrix checks for explain-proof trace/provenance presence and deterministic repeated explain outputs, and improved CNL round-trip quality by rendering parseable natural durations (`PT24H -> 24 hours`, `P7D -> 1 week`) with optional `within ... of <anchor>` regeneration; parser/query gates passed (`20 passed`).

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
