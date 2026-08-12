# Python semantic-state producer supervisor taskboard

Consumable by `ipfs_accelerate_py.agent_supervisor` with task prefix `DSS-`
and board namespace `datasets-semantic-state-v1`.

Protected operator-owned artifacts:

- `docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md`
- `docs/architecture/semantic_state_contract.objectives.md`
- `docs/architecture/semantic_state_contract.todo.md`
- `config/semantic_state_contract_dependencies.seal.json`
- `scripts/validate_semantic_state_contract_dependencies.py`
- `tests/unit/logic/software_contracts/semantic_state/test_dependency_seal.py`

`DSS-000` is an unresolved manual authority gate. No implementation task is
eligible until an operator replaces the remaining final ISI placeholders,
records its exact commit/tree/schema/extractor/interface/tests, validates every
checkout and complete authority fingerprint, commits that sealed state, and
marks only `DSS-000` completed. The final ISI is always supplied through a
separate clean `${DSS_ISI_CHECKOUT}`; the phase-two checkout is never its own
phase-one pin. Workers must never complete or weaken this gate.

The package is
`ipfs_datasets_py.logic.software_contracts.semantic_state`. It consumes the
final public semantic-index view without rescanning, reparsing, re-identifying,
or re-resolving Python. It calls `software_contracts.content` as the only
canonicalization/CID authority. It emits storage-neutral bundles/views and pure
selection results; it does not own persistence, scheduling, context packing,
worktrees, model invocation, receipts, generic MCP++ envelopes, or the
accelerate-owned 40-task benchmark.

## Parallel waves

```text
D0  DSS-000 (manual unresolved dependency seal)
D1  DSS-001 | DSS-002
D2  DSS-003 | DSS-005
D3  DSS-004 | DSS-007
D4  DSS-006 | DSS-008
D5  DSS-009
D6  DSS-010
D7  DSS-011
```

## DSS-000 Seal final producer and consumer authorities

- Status: completed
- Completion: manual
- Priority: P0
- Track: control
- Depends on:
- Goal id: DSS-G010
- Outputs: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md, docs/architecture/semantic_state_contract.objectives.md, docs/architecture/semantic_state_contract.todo.md, config/semantic_state_contract_dependencies.seal.json, scripts/validate_semantic_state_contract_dependencies.py, tests/unit/logic/software_contracts/semantic_state/test_dependency_seal.py
- Validation: python3.12 scripts/validate_semantic_state_contract_dependencies.py --check config/semantic_state_contract_dependencies.seal.json --repo incremental_semantic_index=${DSS_ISI_CHECKOUT} --repo kit_state_roots=${DSS_KIT_CHECKOUT} --repo mcp_plus_plus=${DSS_MCP_PLUS_PLUS_CHECKOUT} --repo accelerate_harness=${DSS_ACCELERATE_CHECKOUT} --run-tests && python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_dependency_seal.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/control
- Parallel lane: dss-control
- Resource class: cpu-small
- Implementation timeout seconds: 1800
- Provider role: operator-only
- Context budget tokens: 0
- Predicted files: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md, docs/architecture/semantic_state_contract.objectives.md, docs/architecture/semantic_state_contract.todo.md, config/semantic_state_contract_dependencies.seal.json, scripts/validate_semantic_state_contract_dependencies.py, tests/unit/logic/software_contracts/semantic_state/test_dependency_seal.py
- Interfaces: SemanticStateDependencySeal@1
- Conflict policy: Operator-only. Do not launch workers while the final ISI pin is unresolved; do not let a worker edit protected control files, bind the phase-two checkout as `${DSS_ISI_CHECKOUT}`, accept a dirty/origin-mismatched/non-root checkout, or replace an exact producer/consumer manifest or test with a synthetic probe.
- Preconditions: The final ISI repair board is terminal and independently audited; kit `05ba9375923cd5fb52e2c9c18b98b530d57d077f`, MCP++ `dc3164653a48d059ae9812078359daeafb451c07`, and accelerate `bde62375e2eabd1c0f9a50c6672372b1af5616c6` have separate clean checkouts; Python 3.12 is available.
- Effects: Replaces the remaining ISI placeholders; seals exact clean HEAD/tree/origin, fixed blob/test manifests, bounded test timeouts, explicit schema/API signatures, and complete authority fingerprints; records the final semantic-index capsule/source API and verified kit block/root-CAS API; runs every pinned producer test and rechecks checkout integrity afterward.
- Acceptance: The seal validator rejects placeholders, unknown fields, wrong origins, dirty/wrong-HEAD/non-root checkouts, missing commit objects, mismatched trees/blobs/complete fingerprints, substituted or skipped tests, timeouts, post-test mutation, a non-3.12 interpreter, or a local MCP++ envelope/CID authority detected through AST inspection. `exact_clean_head` does not overclaim remote-ref advertisement.

## DSS-001 Define closed semantic-state payload models

- Status: todo
- Completion: auto
- Priority: P0
- Track: contracts
- Depends on: DSS-000
- Goal id: DSS-G010
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/models.py, ipfs_datasets_py/logic/software_contracts/semantic_state/schemas/semantic-state.payload.schema.json, tests/unit/logic/software_contracts/semantic_state/test_models.py, tests/unit/logic/software_contracts/semantic_state/test_payload_schema.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_models.py tests/unit/logic/software_contracts/semantic_state/test_payload_schema.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/contracts
- Parallel lane: dss-models
- Resource class: cpu-small
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 40000
- LLM context budget bytes: 327680
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md sections 3 through 10
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_state/models.py, ipfs_datasets_py/logic/software_contracts/semantic_state/schemas/semantic-state.payload.schema.json, tests/unit/logic/software_contracts/semantic_state/test_models.py, tests/unit/logic/software_contracts/semantic_state/test_payload_schema.py
- Predicted symbols: SemanticStateRoot, SemanticStateProducer, SemanticStateBundle, SymbolFactNode, ArtifactFactNode, SemanticLinkNode, SymbolMerkleNode, SemanticCapsule, EnvironmentBinding, EnvironmentBindingSet, RelevantBindingProjection, SemanticBindingDelta, SemanticInvalidationPlan, CapsuleFreshness, VerifiedSourceEvidence, SelectionPolicy, SelectionRule, TestSelection, TestOutcome, TestRunFacts, TestOracleComparison
- Interfaces: SemanticStatePayloads@1, SemanticStateRoot@1, SemanticStateBundle@1
- Conflict policy: Use only `software_contracts.content` for canonical bytes/CIDv1. Models are recursively immutable and closed; sorted pair indexes reject duplicate keys. Do not copy MCP++ envelope/event/receipt schemas or place operational transition data in the datasets root.
- Preconditions: DSS-000 seals exact final producer field names, enum values, schemas, and extractor version.
- Effects: Exclusively defines every durable value record and enum: facts, links, nodes, capsules, binding sets/projections, freshness/source evidence, invalidation, selection policy/rules/results, normalized node-ID-keyed test outcomes/run facts, oracle results, the root, and a finite CID-to-bytes bundle. Later tasks own algorithms only and import these values.
- Acceptance: Unknown fields/schema versions and forged CIDs fail closed; stable/version/edge IDs are preserved verbatim from ISI; the root excludes histories, selections, receipts, clocks, local paths, leases, generations, model data, and MCP++ envelope identities.

## DSS-002 Build the controlled Python selection fixture

- Status: todo
- Completion: auto
- Priority: P0
- Track: fixtures
- Depends on: DSS-000
- Goal id: DSS-G040
- Outputs: tests/fixtures/software_contracts/semantic_state, tests/unit/logic/software_contracts/semantic_state/test_fixture_contract.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_fixture_contract.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/fixtures
- Parallel lane: dss-fixtures
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 28000
- LLM context budget bytes: 229376
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md sections 9 and 13
- Predicted files: tests/fixtures/software_contracts/semantic_state, tests/unit/logic/software_contracts/semantic_state/test_fixture_contract.py
- Interfaces: SemanticStateControlledFixture@1
- Conflict policy: Fixture data only. Check in no `.git`, state store, generated receipt, hand-built dependency edge, or second benchmark corpus. Tests create a temporary Git repository and scan it through the public ISI API.
- Preconditions: The sealed final scanner/API can consume the small fixture without importing it.
- Effects: Supplies baseline source, ordinary mutation patches, and an authored affected-test/proof oracle for local body/signature/cross-module/schema/exception/fixture/config/plugin/lock/policy/interface/generated/dynamic/monkey/native/format/delete/rename cases.
- Acceptance: All paths and mutation cases are deterministic and independently declared; unrelated-formatting truth is not encoded as a special analyzer bypass; the fixture is runnable under Python 3.12/pytest and contains no hidden external dependency.

## DSS-003 Materialize the acyclic symbol Merkle DAG

- Status: todo
- Completion: auto
- Priority: P0
- Track: merkle
- Depends on: DSS-001
- Goal id: DSS-G020
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/merkle.py, tests/unit/logic/software_contracts/semantic_state/test_merkle.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_merkle.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/materialization
- Parallel lane: dss-merkle
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 40000
- LLM context budget bytes: 327680
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md sections 5 and 6
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_state/merkle.py, tests/unit/logic/software_contracts/semantic_state/test_merkle.py
- Predicted symbols: compile_symbol_facts, compile_artifact_facts, compile_semantic_links, compile_symbol_nodes, build_symbol_merkle_dag
- Interfaces: SymbolMerkleDag@1
- Conflict policy: Consume only the sealed resolved ISI view. Links reference fact CIDs and nodes reference link/capsule CIDs; links and capsules never reference symbol-node/capsule CIDs recursively. Do not rescan, parse, resolve, or manufacture targets.
- Preconditions: Closed models and final ISI view contract exist.
- Effects: Builds deterministic sorted fact/link/node blocks and indexes while preserving producer spans, relation, extraction method, confidence, extractor version, and unresolved targets. Symbol-node assembly accepts the already-compiled capsule index as an input and never compiles capsules itself.
- Acceptance: Recursive calls, mutual imports, and inheritance cycles cannot form CID cycles; shuffled input order has no effect; every emitted fact/link/node/index block and claimed CID reverifies; one semantic symbol mutation changes only its bounded fact/link/node/index cone. Final root-cone behavior is proved in DSS-009/DSS-010.

## DSS-004 Compile deterministic authoritative capsules incrementally

- Status: todo
- Completion: auto
- Priority: P0
- Track: capsules
- Depends on: DSS-001, DSS-005
- Goal id: DSS-G020
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/capsules.py, tests/unit/logic/software_contracts/semantic_state/test_capsules.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_capsules.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/materialization
- Parallel lane: dss-capsules
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 42000
- LLM context budget bytes: 344064
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md sections 5 through 8
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_state/capsules.py, tests/unit/logic/software_contracts/semantic_state/test_capsules.py
- Predicted symbols: compile_semantic_capsule, compile_semantic_capsules, capsule_source_key
- Interfaces: SemanticCapsuleCompiler@1
- Conflict policy: Capsules may include only sealed producer-authoritative facts. Docstrings are hints and LLM summaries are separate heuristic annotations excluded from truth. Never raise confidence, use another capsule/node CID as a dependency, or reimplement the bindings-owned relevant-projection algorithm.
- Preconditions: Closed capsule/binding records and the DSS-005 projection algorithm exist.
- Effects: Compiles capsules keyed by stable ID, version CID, ISI schema, and extractor version and additionally binds capsule compiler/schema, exact source slice, dependency facts/links, and the supplied bindings-owned per-symbol relevant projection CID.
- Acceptance: A verified `previous_bundle` reuses only byte-identical capsule/index blocks whose complete current inputs reverify; cold and incremental capsule/index compilation over identical inputs is byte-identical; unrelated scoped projections do not change a capsule while global/unknown projections conservatively do. Final root equality is proved in DSS-009/DSS-010.

## DSS-005 Extend source invalidation with environment bindings

- Status: todo
- Completion: auto
- Priority: P0
- Track: invalidation
- Depends on: DSS-001
- Goal id: DSS-G030
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/bindings.py, ipfs_datasets_py/logic/software_contracts/semantic_state/invalidation.py, tests/unit/logic/software_contracts/semantic_state/test_bindings.py, tests/unit/logic/software_contracts/semantic_state/test_invalidation.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_bindings.py tests/unit/logic/software_contracts/semantic_state/test_invalidation.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/assurance
- Parallel lane: dss-invalidation
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 42000
- LLM context budget bytes: 344064
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md section 8
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_state/bindings.py, ipfs_datasets_py/logic/software_contracts/semantic_state/invalidation.py, tests/unit/logic/software_contracts/semantic_state/test_bindings.py, tests/unit/logic/software_contracts/semantic_state/test_invalidation.py
- Predicted symbols: build_environment_binding_set, relevant_binding_projection, diff_environment_bindings, extend_semantic_invalidation
- Interfaces: EnvironmentBindingSet@1, SemanticInvalidationPlan@1
- Conflict policy: This module is the sole `relevant_binding_projection` authority. Recompute or verify and preserve every ISI delta/obligation before adding environment obligations. Traverse relation-specific directions; do not invent tests, proofs, adapters, receipts, or arbitrary source rewrites.
- Preconditions: Closed binding/delta/obligation models and the sealed previous/current ISI APIs exist.
- Effects: Adds explicit lock/dependency, pytest/proof config, policy/security, interface, generated-input, Python/toolchain, semantic-schema, and compiler invalidation rules with bounded evidence paths and conservative global fallback.
- Acceptance: Function/signature/effect/exception/schema/fixture facts retain ISI semantics; changed bindings stale every known bound derivative and no known disjoint capsule; dependency/config/policy/interface/generated/toolchain uncertainty remains visible as an obligation/fallback reason.

## DSS-006 Assess freshness and retrieve exact producer-bound source

- Status: todo
- Completion: auto
- Priority: P0
- Track: source-admission
- Depends on: DSS-004, DSS-005
- Goal id: DSS-G020
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/freshness.py, ipfs_datasets_py/logic/software_contracts/semantic_state/source.py, tests/unit/logic/software_contracts/semantic_state/test_freshness.py, tests/unit/logic/software_contracts/semantic_state/test_source.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_freshness.py tests/unit/logic/software_contracts/semantic_state/test_source.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/materialization
- Parallel lane: dss-source
- Resource class: cpu-small
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md sections 7 and 10
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_state/freshness.py, ipfs_datasets_py/logic/software_contracts/semantic_state/source.py, tests/unit/logic/software_contracts/semantic_state/test_freshness.py, tests/unit/logic/software_contracts/semantic_state/test_source.py
- Predicted symbols: assess_capsule_freshness, read_required_source
- Interfaces: CapsuleFreshness@1, ProducerBoundSource@1
- Conflict policy: Read source only through the sealed tree/snapshot-bound ISI capsule view and reverify raw CID. Never use ambient `Path` fallback, private scanner/visitor state, target imports, or heuristic text as exact source.
- Preconditions: Capsules and semantic invalidation plans exist; DSS-000 sealed the actual source-view signatures.
- Effects: Separates freshness from immutable capsules and admits only fresh exact or visibly caveated conservative capsules; target/edit/test and heuristic/opaque/stale/unknown/invalid inputs request exact source.
- Acceptance: Corrupt, missing, wrong-state, TOCTOU-mismatched, or unavailable source yields a typed failure/rescan requirement; exact bytes and spans bind the expected producer state; no unsafe capsule can substitute for raw source.

## DSS-007 Select affected pytest tests and proof obligations

- Status: todo
- Completion: auto
- Priority: P0
- Track: test-selection
- Depends on: DSS-003, DSS-005
- Goal id: DSS-G030
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/test_selection.py, tests/unit/logic/software_contracts/semantic_state/test_test_selection.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_test_selection.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/assurance
- Parallel lane: dss-selection
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 42000
- LLM context budget bytes: 344064
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md section 9
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_state/test_selection.py, tests/unit/logic/software_contracts/semantic_state/test_test_selection.py
- Predicted symbols: select_tests_and_proofs, shortest_reason_paths
- Interfaces: TestSelection@1, ProofSelection@1
- Conflict policy: Pure graph selection only. Do not import/collect/run tests, guess node IDs, re-resolve edges, or reimplement selection in accelerate. Consume both previous and current `SemanticStateView` so deletion/rename evidence survives.
- Preconditions: Acyclic graph views and semantic invalidation exist.
- Effects: Selects authoritative pytest node IDs and proof IDs through direct test, reverse caller/import, fixture, schema, config, binding, generated, proof, and explicit-rule evidence, with sorted shortest edge/link reason paths.
- Acceptance: Output binds previous/current root CIDs, universe CID/count, seeds, covered/unresolved obligations, and `none`/`full_pytest`/`full_proofs`/`both` fallback; dynamic plugins, native/opaque reachability, or unknown universe force visible full fallback.

## DSS-008 Compute honest selected-versus-full oracle metrics

- Status: todo
- Completion: auto
- Priority: P0
- Track: oracle
- Depends on: DSS-002, DSS-007
- Goal id: DSS-G030
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/oracle.py, tests/unit/logic/software_contracts/semantic_state/test_oracle.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_oracle.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/assurance
- Parallel lane: dss-oracle
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 30000
- LLM context budget bytes: 245760
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md sections 9 and 13
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_state/oracle.py, tests/unit/logic/software_contracts/semantic_state/test_oracle.py
- Predicted symbols: compare_test_selection_oracle
- Interfaces: TestSelectionOracle@1
- Conflict policy: This module consumes normalized run facts supplied by accelerate; it never invokes pytest or treats a passing selected run as proof of complete selection. Exclude known baseline failures and report zero denominators as not applicable.
- Preconditions: Controlled authored oracle and `TestSelection` exist.
- Effects: Computes new regression node IDs by comparing each node's normalized failure fingerprint with its baseline fingerprint, then computes missed-regression node IDs, TP/FN/FP strictly in the pytest-node-ID domain, precision/recall when defined, selection/execution reductions, changed outcomes, and fallback rate across explicit pass/fail/error/skip/xfail/timeout states.
- Acceptance: Controlled cases have zero false negatives and missed regressions; full-suite fallback is measured; baseline-known failures are not attributed to a candidate; empty oracles never fabricate 100 percent precision/recall.

## DSS-009 Publish the storage-neutral semantic-state API

- Status: todo
- Completion: auto
- Priority: P0
- Track: public-api
- Depends on: DSS-003, DSS-004, DSS-005, DSS-006, DSS-007, DSS-008
- Goal id: DSS-G040
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_state/api.py, ipfs_datasets_py/logic/software_contracts/semantic_state/__init__.py, tests/unit/logic/software_contracts/semantic_state/test_api.py, tests/unit/logic/software_contracts/semantic_state/test_schema_packaging.py, pyproject.toml, setup.py, MANIFEST.in
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_api.py tests/unit/logic/software_contracts/semantic_state/test_schema_packaging.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/release
- Parallel lane: dss-api
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 44000
- LLM context budget bytes: 360448
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md sections 4 through 11
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_state/api.py, ipfs_datasets_py/logic/software_contracts/semantic_state/__init__.py, tests/unit/logic/software_contracts/semantic_state/test_api.py, tests/unit/logic/software_contracts/semantic_state/test_schema_packaging.py, pyproject.toml, setup.py, MANIFEST.in
- Predicted symbols: SemanticStateBlockReader, SemanticStateView, build_semantic_state, verify_semantic_state_bundle, open_semantic_state
- Interfaces: SemanticStateProducer@1, SemanticStateView@1, SemanticStateBlockReader@1
- Conflict policy: `SemanticStateView/get_block` is read-only and storage-neutral. No put/CAS/WAL/provider/network operation, kit import, scheduler, context pack, receipt, or MCP++ envelope hasher enters this package. Package edits must be narrowly additive.
- Preconditions: All model/materialization/assurance modules pass.
- Effects: Publishes a closed API for cold or verified-incremental `previous_bundle` builds, bundle verification, injected-block-reader views, capsules/freshness/source, invalidation, selection, and oracle comparison; packages the schema.
- Acceptance: A finite in-memory bundle and an injected verified reader yield identical views; every read reverifies CID/schema; missing/corrupt blocks fail typed; the public signature uses `previous_bundle` and previous/current views exactly and has no persistence side effect. Cold and verified-incremental assembly over identical inputs has byte-identical reachable blocks and root CID.

## DSS-010 Prove the public controlled pipeline and wire boundary

- Status: todo
- Completion: auto
- Priority: P0
- Track: acceptance
- Depends on: DSS-002, DSS-009
- Goal id: DSS-G040
- Outputs: tests/unit/logic/software_contracts/semantic_state/test_public_semantic_state_pipeline.py, tests/unit/logic/software_contracts/semantic_state/test_selection_oracle_acceptance.py, tests/unit/logic/software_contracts/semantic_state/test_mcp_payload_boundary.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state/test_public_semantic_state_pipeline.py tests/unit/logic/software_contracts/semantic_state/test_selection_oracle_acceptance.py tests/unit/logic/software_contracts/semantic_state/test_mcp_payload_boundary.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/release
- Parallel lane: dss-acceptance
- Resource class: cpu-medium
- Implementation timeout seconds: 10800
- Provider role: codex-implement
- Context budget tokens: 48000
- LLM context budget bytes: 393216
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md sections 9 through 13
- Predicted files: tests/unit/logic/software_contracts/semantic_state/test_public_semantic_state_pipeline.py, tests/unit/logic/software_contracts/semantic_state/test_selection_oracle_acceptance.py, tests/unit/logic/software_contracts/semantic_state/test_mcp_payload_boundary.py
- Interfaces: SemanticStateControlledAcceptance@1, McpPlusPlusPayloadBoundary@1
- Conflict policy: End-to-end tests use two real public scans and public diff/invalidation/state APIs; they may not hand-construct edges, mutate a returned state, inspect private visitors, or duplicate fixture/unit expectations. MCP++ remains only the pinned generic Profile A/B/F outer-wire authority.
- Preconditions: Public semantic-state API and controlled fixture exist.
- Effects: Proves baseline/current scan to Merkle/capsule/binding/invalidation/selection/oracle behavior, cold versus incremental root/block determinism, bounded root-cone changes, deleted/renamed previous/current evidence, bounded unrelated changes, and generic envelope/payload separation.
- Acceptance: All controlled mutation/fallback cases pass with zero selection false negatives; identical semantic inputs have identical state roots; opaque behavior requests source/full fallback; datasets defines no interface descriptor, execution envelope/receipt, DAG event, request/attempt/provider field, or envelope CID/hasher.

## DSS-011 Close documentation, import safety, and regressions

- Status: todo
- Completion: auto
- Priority: P0
- Track: closeout
- Depends on: DSS-010
- Goal id: DSS-G040
- Outputs: docs/software_contracts/SEMANTIC_STATE_CONTRACT.md, tests/unit/logic/software_contracts/semantic_state/test_import_safety.py, tests/unit/logic/software_contracts/semantic_state/test_regressions.py
- Validation: python3.12 -m pytest -q tests/unit/logic/software_contracts/semantic_state tests/unit/logic/software_contracts/semantic_index tests/unit/logic/software_contracts/test_content_identity.py tests/unit/logic/software_contracts/test_python_frontend.py tests/unit/logic/software_contracts/test_repository_manifest.py tests/unit/logic/software_contracts/test_resolver.py tests/cli/test_semantic_index_cli.py
- Board namespace: datasets-semantic-state-v1
- Bundle: dss/release
- Parallel lane: dss-closeout
- Resource class: cpu-medium
- Implementation timeout seconds: 14400
- Provider role: codex-implement
- Context budget tokens: 44000
- LLM context budget bytes: 360448
- Plan context: docs/architecture/SEMANTIC_STATE_CONTRACT_PLAN.md all sections
- Predicted files: docs/software_contracts/SEMANTIC_STATE_CONTRACT.md, tests/unit/logic/software_contracts/semantic_state/test_import_safety.py, tests/unit/logic/software_contracts/semantic_state/test_regressions.py
- Interfaces: SemanticStateRelease@1
- Conflict policy: Document only proven APIs/results and known Python unsoundness. Do not broaden to a CLI/server/UI, persistence/scheduler/model/worktree implementation, arbitrary languages, ZK, or a datasets benchmark.
- Preconditions: Controlled acceptance passes.
- Effects: Freezes the exact accelerate consumer interface and golden vectors, verifies hermetic imports, adds regression checks for every prior boundary, and runs the full focused semantic-index plus semantic-state suite.
- Acceptance: Ordinary imports install nothing, access no network, start no process/thread, write nothing, and mutate no environment; all focused tests pass; known dynamic/opaque limits and the precise `TestSelectionRef`, `SemanticCapsuleRef`, `SemanticStateView/get_block`, and bundle handoff are documented without overclaim.
