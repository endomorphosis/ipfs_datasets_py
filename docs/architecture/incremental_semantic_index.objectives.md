# Incremental Semantic Index objective heap

Machine-ingestible goal hierarchy for `ipfs_accelerate_py.agent_supervisor`.
The executable projection is `docs/architecture/incremental_semantic_index.todo.md`
with task prefix `## ISI-`. The reviewed design is
`docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md`.

## Goal tree

```text
ISI-G000  Deterministic IncrementalSemanticIndex release
|-- ISI-G010  Closed models and dual content identities
|-- ISI-G020  Deterministic snapshot and Python/test extraction
|-- ISI-G030  Typed symbol graph and deterministic state/delta
|-- ISI-G040  Bounded explainable invalidation
|-- ISI-G050  Durable state persistence and notification watcher
|-- ISI-G060  Public API and CLI
`-- ISI-G070  Acceptance, documentation, and capsule handoff
```

## ISI-G000 Deterministic IncrementalSemanticIndex release

- Status: active
- Parent:
- Depends on:
- Fib priority: 1
- Priority: P0
- Track: semantic-index
- Bundle: isi/root
- Goal: Produce a deterministic Python symbol graph whose mutations yield bounded, explainable stale obligations and whose states replay from verified content-addressed persistence.
- Evidence: isi/inspection@1, isi/state-root@1, isi/invalidation-plan@1, isi/persistence@1, isi/acceptance@1
- Acceptance criteria: isi/inspection@1; isi/state-root@1; isi/invalidation-plan@1; isi/persistence@1; isi/acceptance@1
- Outputs: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md, docs/architecture/incremental_semantic_index.objectives.md, docs/architecture/incremental_semantic_index.todo.md
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index tests/cli/test_semantic_index_cli.py
- Acceptance: Stable and version identities, graph, deltas, invalidation, persistence, explanations, watcher, API, CLI, and all required mutation fixtures pass without importing target repositories or requiring a daemon.
- Gap task: ISI-000 through ISI-032
- Refinement: Extend `logic/software_contracts`; do not create another analyzer platform or content-identity authority.

## ISI-G010 Closed models and dual content identities

- Status: active
- Parent: ISI-G000
- Depends on:
- Fib priority: 2
- Priority: P0
- Track: contracts
- Bundle: isi/contracts
- Goal: Define closed deterministic repository, symbol, edge, delta, obligation, and explanation records with separate stable logical and semantic version CIDs.
- Evidence: isi/models@1, isi/stable-id@1, isi/version-id@1
- Acceptance criteria: isi/models@1; isi/stable-id@1; isi/version-id@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/models.py, ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_models.py
- Acceptance: Every durable record round-trips deterministically and every CID comes from `software_contracts.content`; no span or line participates in stable logical identity.
- Gap task: ISI-001
- Refinement: Reuse existing strict content identity and schema conventions.

## ISI-G020 Deterministic snapshot and Python/test extraction

- Status: active
- Parent: ISI-G000
- Depends on: ISI-G010
- Fib priority: 3
- Priority: P0
- Track: extraction
- Bundle: isi/extraction
- Goal: Build sorted Git/filesystem snapshots and extract the required Python, pytest, configuration, schema, and dependency facts without executing analyzed code.
- Evidence: isi/snapshot@1, isi/python-analysis@1, isi/pytest-analysis@1
- Acceptance criteria: isi/snapshot@1; isi/python-analysis@1; isi/pytest-analysis@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/snapshot.py, ipfs_datasets_py/logic/software_contracts/semantic_index/python_analysis.py, ipfs_datasets_py/logic/software_contracts/semantic_index/pytest_analysis.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_snapshot.py tests/unit/logic/software_contracts/semantic_index/test_python_analysis.py tests/unit/logic/software_contracts/semantic_index/test_pytest_analysis.py
- Acceptance: All mandatory constructs have source-bound facts or explicit unsupported/opaque evidence; dynamic Python never becomes an exact complete-semantics claim.
- Gap task: ISI-002, ISI-003, ISI-004, ISI-010
- Refinement: Adapt `python_frontend`, `repository`, and `resolver`; add only missing symbol-level projections.

## ISI-G030 Typed symbol graph and deterministic state/delta

- Status: active
- Parent: ISI-G000
- Depends on: ISI-G010, ISI-G020
- Fib priority: 5
- Priority: P0
- Track: graph
- Bundle: isi/graph
- Goal: Resolve bounded typed relations, assemble stable repository states, and compare them by semantic projections rather than source lines.
- Evidence: isi/symbol-graph@1, isi/repository-state@1, isi/state-delta@1
- Acceptance criteria: isi/symbol-graph@1; isi/repository-state@1; isi/state-delta@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, ipfs_datasets_py/logic/software_contracts/semantic_index/symbol_graph.py, ipfs_datasets_py/logic/software_contracts/semantic_index/delta.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_scanner.py tests/unit/logic/software_contracts/semantic_index/test_symbol_graph.py tests/unit/logic/software_contracts/semantic_index/test_delta.py
- Acceptance: Identical input yields an identical state root; all relation edges carry required provenance/confidence; delete/rename and bounded unrelated edits are explicit.
- Gap task: ISI-010, ISI-011, ISI-012
- Refinement: Unresolved and finite-may targets remain typed; no complete call-graph claim.

## ISI-G040 Bounded explainable invalidation

- Status: active
- Parent: ISI-G000
- Depends on: ISI-G030
- Fib priority: 8
- Priority: P0
- Track: invalidation
- Bundle: isi/invalidation
- Goal: Encode the requested body, signature, side-effect, exception, schema, fixture/config, lockfile, deletion, and opaque-behavior invalidation rules with auditable explanations.
- Evidence: isi/invalidation-rules@1, isi/symbol-explanation@1, isi/impact-explanation@1
- Acceptance criteria: isi/invalidation-rules@1; isi/symbol-explanation@1; isi/impact-explanation@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/invalidation.py, ipfs_datasets_py/logic/software_contracts/semantic_index/explain.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_invalidation.py tests/unit/logic/software_contracts/semantic_index/test_explain.py
- Acceptance: Plans are bounded, deterministically ordered, source/edge justified, and do not invalidate unrelated callers for a body-only change with stable contracts/effects.
- Gap task: ISI-020, ISI-021
- Refinement: Emit obligations only; never rewrite dependent code.

## ISI-G050 Durable state persistence and notification watcher

- Status: active
- Parent: ISI-G000
- Depends on: ISI-G010
- Fib priority: 8
- Priority: P0
- Track: persistence
- Bundle: isi/persistence
- Goal: Persist and replay states/deltas in the existing immutable CAS, protect current roots with compare-and-swap, recover interrupted writes, and trigger canonical rescans from debounced notifications.
- Evidence: isi/local-cas@1, isi/root-cas@1, isi/recovery@1, isi/ipfs-kit-adapter@1, isi/watch@1
- Acceptance criteria: isi/local-cas@1; isi/root-cas@1; isi/recovery@1; isi/ipfs-kit-adapter@1; isi/watch@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/persistence.py, ipfs_datasets_py/logic/software_contracts/semantic_index/watch.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_persistence.py tests/unit/logic/software_contracts/semantic_index/test_watch.py
- Acceptance: Corruption fails closed, interrupted writes retain the old root, concurrent writers cannot silently overwrite, local tests require no daemon, and watcher events are never state authority.
- Gap task: ISI-005, ISI-022
- Refinement: Compose `cache.ImmutableCAS`; keep `ipfs_kit_py` lazy and dependency-injected.

## ISI-G060 Public API and CLI

- Status: active
- Parent: ISI-G000
- Depends on: ISI-G030, ISI-G040, ISI-G050
- Fib priority: 13
- Priority: P0
- Track: interface
- Bundle: isi/interface
- Goal: Publish the required Python function surface, an `IncrementalSemanticIndex` facade, and the narrowly scoped `semantic-index` commands.
- Evidence: isi/public-api@1, isi/cli@1
- Acceptance criteria: isi/public-api@1; isi/cli@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/index.py, ipfs_datasets_py/logic/software_contracts/semantic_index/__init__.py, ipfs_datasets_py/cli/semantic_index_cli.py, pyproject.toml, setup.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_api.py tests/cli/test_semantic_index_cli.py
- Acceptance: All requested functions and six CLI commands work with deterministic JSON and stable failures; ordinary feature imports do not load optional backends, install, access the network, or add environment mutation.
- Gap task: ISI-023, ISI-030
- Refinement: Dedicated CLI entry point; do not expand the legacy monolithic CLI.

## ISI-G070 Acceptance, documentation, and capsule handoff

- Status: active
- Parent: ISI-G000
- Depends on: ISI-G060
- Fib priority: 21
- Priority: P0
- Track: acceptance
- Bundle: isi/acceptance
- Goal: Prove every required mutation/persistence fixture, regress the existing software-contract authorities, document honest limitations, and freeze the semantic-capsule consumer interface.
- Evidence: isi/fixture-matrix@1, isi/regression@1, isi/import-safety@1, isi/capsule-interface@1
- Acceptance criteria: isi/fixture-matrix@1; isi/regression@1; isi/import-safety@1; isi/capsule-interface@1
- Outputs: tests/fixtures/software_contracts/incremental_semantic_index, tests/unit/logic/software_contracts/semantic_index/test_acceptance.py, docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md
- Validation: python -m pytest -q tests/unit/logic/software_contracts tests/cli/test_semantic_index_cli.py
- Acceptance: Required fixtures pass; existing content/cache/frontend/repository/resolver tests remain green; limitations and exact capsule inputs are documented from current code.
- Gap task: ISI-031, ISI-032
- Refinement: Report unrelated suite failures separately; do not weaken gates or broaden scope.
