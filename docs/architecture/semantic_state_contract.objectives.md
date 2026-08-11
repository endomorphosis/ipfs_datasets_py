# Python semantic-state producer objectives

This objective heap is implemented by
`docs/architecture/semantic_state_contract.todo.md` with task prefix `## DSS-`.
The reviewed design is `docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md`.
All goals are active planning records, but every implementation task is blocked
by the manual unresolved dependency gate `DSS-000`.

## Objective tree

```text
DSS-G000  Python-first semantic-state producer contract
|-- DSS-G010  Sealed producer authority and closed payload models
|-- DSS-G020  Acyclic symbol Merkle state and capsule/source admission
|-- DSS-G030  Environment invalidation and test/proof assurance
`-- DSS-G040  Public bundle, controlled acceptance, and release handoff
```

## DSS-G000 Python-first semantic-state producer contract

- Status: active
- Parent:
- Depends on:
- Fib priority: 55
- Priority: P0
- Track: semantic-state
- Bundle: dss/program
- Goal: Publish a deterministic datasets-owned Python semantic-state producer that the sealed accelerate harness can consume without assuming scanner, CID, persistence, context, scheduling, execution, receipt, or wire-envelope authority.
- Evidence: dss/dependency-seal@1, dss/payload-models@1, dss/symbol-merkle@1, dss/capsule@1, dss/source-admission@1, dss/binding-invalidation@1, dss/test-selection@1, dss/oracle@1, dss/public-api@1, dss/controlled-e2e@1, dss/import-safety@1
- Acceptance criteria: dss/dependency-seal@1; dss/payload-models@1; dss/symbol-merkle@1; dss/capsule@1; dss/source-admission@1; dss/binding-invalidation@1; dss/test-selection@1; dss/oracle@1; dss/public-api@1; dss/controlled-e2e@1; dss/import-safety@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state, tests/unit/logic/software_contracts/semantic_state, tests/fixtures/software_contracts/semantic_state, docs/software_contracts/SEMANTIC_STATE_CONTRACT.md
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state tests/unit/logic/software_contracts/semantic_index tests/unit/logic/software_contracts/test_content_identity.py tests/unit/logic/software_contracts/test_python_frontend.py tests/unit/logic/software_contracts/test_repository_manifest.py tests/unit/logic/software_contracts/test_resolver.py tests/cli/test_semantic_index_cli.py
- Acceptance: One canonical repaired ISI view deterministically produces an acyclic symbol DAG, capsules, root bundle, additive environment invalidation, explainable test/proof selection, and honest oracle metrics; cold and verified-incremental results match; uncertainty forces source or full fallback; imports are hermetic.
- Gap task: DSS-000 through DSS-011
- Refinement: Do not create a scanner/CID/CAS/context/worktree/scheduler/receipt/benchmark or MCP++ envelope authority.

## DSS-G010 Sealed producer authority and closed payload models

- Status: active
- Parent: DSS-G000
- Depends on:
- Fib priority: 13
- Priority: P0
- Track: contracts
- Bundle: dss/contracts
- Goal: Seal the exact final ISI and KSR revisions plus the reviewed MCP++ and accelerate consumer contracts, then define every self-verifying semantic-state payload before algorithms are implemented.
- Evidence: dss/dependency-seal@1, dss/payload-models@1
- Acceptance criteria: dss/dependency-seal@1; dss/payload-models@1
- Outputs: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md, docs/architecture/semantic_state_contract.objectives.md, docs/architecture/semantic_state_contract.todo.md, config/semantic_state_contract_dependencies.seal.json, scripts/validate_semantic_state_contract_dependencies.py, tests/unit/logic/software_contracts/semantic_state/test_dependency_seal.py, ipfs_datasets_py/logic/software_contracts/semantic_state/models.py, ipfs_datasets_py/logic/software_contracts/semantic_state/schemas/semantic-state.payload.schema.json
- Validation: python3.12 scripts/validate_semantic_state_contract_dependencies.py --check config/semantic_state_contract_dependencies.seal.json && python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_dependency_seal.py tests/unit/logic/software_contracts/semantic_state/test_models.py tests/unit/logic/software_contracts/semantic_state/test_payload_schema.py
- Acceptance: Unresolved, forged, dirty, origin-mismatched, unreachable, schema-incompatible, non-Python-3.12, or failing producer authorities are rejected; closed models accept only strict reviewed values and reverify every claimed CID.
- Gap task: DSS-000, DSS-001
- Refinement: `software_contracts.content` remains the only content-identity implementation and generic MCP++ records remain external.

## DSS-G020 Acyclic symbol Merkle state and capsule/source admission

- Status: active
- Parent: DSS-G000
- Depends on: DSS-G010
- Fib priority: 21
- Priority: P0
- Track: semantic-materialization
- Bundle: dss/materialization
- Goal: Materialize an acyclic symbol-level Merkle state, compile deterministic authoritative capsules with bounded incremental reuse, and admit capsules or exact tree-bound source according to freshness and confidence.
- Evidence: dss/symbol-merkle@1, dss/capsule@1, dss/source-admission@1
- Acceptance criteria: dss/symbol-merkle@1; dss/capsule@1; dss/source-admission@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/merkle.py, ipfs_datasets_py/logic/software_contracts/semantic_state/capsules.py, ipfs_datasets_py/logic/software_contracts/semantic_state/freshness.py, ipfs_datasets_py/logic/software_contracts/semantic_state/source.py, tests/unit/logic/software_contracts/semantic_state/test_merkle.py, tests/unit/logic/software_contracts/semantic_state/test_capsules.py, tests/unit/logic/software_contracts/semantic_state/test_freshness.py, tests/unit/logic/software_contracts/semantic_state/test_source.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_merkle.py tests/unit/logic/software_contracts/semantic_state/test_capsules.py tests/unit/logic/software_contracts/semantic_state/test_freshness.py tests/unit/logic/software_contracts/semantic_state/test_source.py
- Acceptance: Recursive calls/inheritance cannot form CID cycles; capsules preserve only producer-authoritative facts; per-symbol relevant binding projections avoid unrelated invalidation; verified previous-bundle reuse equals cold output; heuristic, opaque, stale, unknown, or edited code requires exact producer-bound source.
- Gap task: DSS-003, DSS-004, DSS-006
- Refinement: Links point to fact CIDs, not symbol-node/capsule CIDs; source reads never fall back to the ambient filesystem.

## DSS-G030 Environment invalidation and test/proof assurance

- Status: active
- Parent: DSS-G000
- Depends on: DSS-G010
- Fib priority: 21
- Priority: P0
- Track: incremental-assurance
- Bundle: dss/assurance
- Goal: Preserve the repaired ISI invalidation plan, add explicit policy/interface/lock/config/generated/toolchain obligations, and select tests/proofs from typed evidence with honest selected-versus-full metrics.
- Evidence: dss/binding-invalidation@1, dss/test-selection@1, dss/oracle@1
- Acceptance criteria: dss/binding-invalidation@1; dss/test-selection@1; dss/oracle@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/bindings.py, ipfs_datasets_py/logic/software_contracts/semantic_state/invalidation.py, ipfs_datasets_py/logic/software_contracts/semantic_state/test_selection.py, ipfs_datasets_py/logic/software_contracts/semantic_state/oracle.py, tests/unit/logic/software_contracts/semantic_state/test_bindings.py, tests/unit/logic/software_contracts/semantic_state/test_invalidation.py, tests/unit/logic/software_contracts/semantic_state/test_test_selection.py, tests/unit/logic/software_contracts/semantic_state/test_oracle.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_bindings.py tests/unit/logic/software_contracts/semantic_state/test_invalidation.py tests/unit/logic/software_contracts/semantic_state/test_test_selection.py tests/unit/logic/software_contracts/semantic_state/test_oracle.py
- Acceptance: Binding changes stale the correct derived artifacts without rewriting source; previous/current views retain deleted/renamed dependency truth; every selected test/proof has a bounded reason path; controlled cases have zero false negatives and missed regressions; uncertainty visibly selects full fallback.
- Gap task: DSS-005, DSS-007, DSS-008
- Refinement: Selection is a pure datasets result; accelerate executes it and owns the 40-task benchmark rather than reselecting.

## DSS-G040 Public bundle, controlled acceptance, and release handoff

- Status: active
- Parent: DSS-G000
- Depends on: DSS-G020, DSS-G030
- Fib priority: 34
- Priority: P0
- Track: release
- Bundle: dss/release
- Goal: Export the exactly closed storage-neutral API and prove the scanner-to-selection contract on a controlled Python repository before accelerate or kit consumes it.
- Evidence: dss/public-api@1, dss/controlled-e2e@1, dss/import-safety@1
- Acceptance criteria: dss/public-api@1; dss/controlled-e2e@1; dss/import-safety@1
- Outputs: tests/fixtures/software_contracts/semantic_state, ipfs_datasets_py/logic/software_contracts/semantic_state/api.py, ipfs_datasets_py/logic/software_contracts/semantic_state/__init__.py, tests/unit/logic/software_contracts/semantic_state/test_api.py, tests/unit/logic/software_contracts/semantic_state/test_public_semantic_state_pipeline.py, tests/unit/logic/software_contracts/semantic_state/test_selection_oracle_acceptance.py, tests/unit/logic/software_contracts/semantic_state/test_mcp_payload_boundary.py, tests/unit/logic/software_contracts/semantic_state/test_import_safety.py, tests/unit/logic/software_contracts/semantic_state/test_regressions.py, docs/software_contracts/SEMANTIC_STATE_CONTRACT.md
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state tests/unit/logic/software_contracts/semantic_index tests/cli/test_semantic_index_cli.py
- Acceptance: Public final-ISI scan/diff/invalidate data produces deterministic cold/incremental bundles with no manufactured edge; all controlled mutation and fallback cases pass; payloads remain application data rather than copied MCP++ envelopes; schema packaging and hermetic imports are proven; the accelerate consumer interface is frozen exactly.
- Gap task: DSS-002, DSS-009, DSS-010, DSS-011
- Refinement: `DSS-002` is scheduled early because it owns independent fixture data; it does not weaken the goal dependency or create a benchmark authority.
