# Incremental Semantic Index supervisor taskboard

Consumable by `ipfs_accelerate_py.agent_supervisor` with task prefix `ISI-`.

Protected companion artifacts:

- `docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md`
- `docs/architecture/incremental_semantic_index.objectives.md`
- `docs/architecture/incremental_semantic_index.todo.md`

All implementation stays inside `endomorphosis/ipfs_datasets_py`. The owner is
`ipfs_datasets_py.logic.software_contracts.semantic_index`. Workers must reuse
`logic/software_contracts/content.py` as the sole software-contract CID and
canonicalization authority, `cache.ImmutableCAS` for local immutable storage,
and the existing non-executing frontend/resolver/repository facts. Workers must
not import or execute analyzed repositories, claim a complete Python call
graph, auto-rewrite dependents, install dependencies, or broaden the requested
feature.

## Parallel waves

```text
W0  ISI-000 (completed inspection/control seal)
W1  ISI-001
W2  ISI-002 | ISI-003 | ISI-004 | ISI-005
W3  ISI-010 | ISI-011
W4  ISI-012 | ISI-021 | ISI-022
W5  ISI-020
W6  ISI-023
W7  ISI-030 | ISI-031
W8  ISI-032
```

## ISI-000 Inspect and seal semantic-index authorities

- Status: completed
- Completion: manual
- Priority: P0
- Track: control
- Depends on:
- Goal id: ISI-G000
- Outputs: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md, docs/architecture/incremental_semantic_index.objectives.md, docs/architecture/incremental_semantic_index.todo.md
- Validation: git rev-parse HEAD
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/control
- Parallel lane: isi-control
- Resource class: cpu-small
- Implementation timeout seconds: 1800
- Provider role: operator-only
- Context budget tokens: 0
- Predicted files: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md, docs/architecture/incremental_semantic_index.objectives.md, docs/architecture/incremental_semantic_index.todo.md
- Interfaces: IncrementalSemanticIndexPlan@1
- Conflict policy: These reviewed control files are immutable to implementation workers.
- Preconditions: Target repository is readable at `a2f5400b7cb89c8481819379a1b7b9959fe81d45`.
- Effects: Records exact inspected commit/tree, existing AST/resolution/repository/CID/CAS authorities, package ownership, non-goals, task DAG, validation, limitations, and capsule boundary.
- Acceptance: Plan records the exact revision and inspected modules; `software_contracts.content` is the sole CID authority; the feature is owned by `logic/software_contracts/semantic_index`.

## ISI-001 Define closed models and dual identities

- Status: completed
- Completion: auto
- Priority: P0
- Track: contracts
- Depends on: ISI-000
- Goal id: ISI-G010
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/models.py, ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_models.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/contracts
- Parallel lane: isi-models
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 32000
- LLM context budget bytes: 262144
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 4 through 9
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/models.py, ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py
- Predicted symbols: AnalysisConfidence, SymbolKind, RelationType, SourceSpan, ArtifactRecord, SymbolRecord, DependencyEdge, RepositoryState, RepositoryStateDelta, InvalidationObligation, InvalidationPlan, SymbolExplanation, ImpactExplanation, stable_symbol_id, symbol_version_cid
- Interfaces: IncrementalSemanticIndexModels@1, StableSymbolIdentity@1, SymbolVersionIdentity@1
- Conflict policy: Do not edit `content.py`, copy CID code, or use span-derived frontend IDs as logical identity. Closed enums must contain exactly the required confidence and relation vocabulary.
- Preconditions: Existing `software_contracts.content`, AST IR, and schema conventions pass their tests.
- Effects: Supplies deterministic strict-DAG-JSON records and separate stable/version CIDs for all later tasks.
- Acceptance: Stable ID binds repository/language/module/qualified name/kind/namespace and excludes spans/body; version CID additionally binds normalized AST/signature/decorators/annotations/schema/extractor; formatting stability and semantic mutation vectors pass; every durable collection is deterministically ordered and round-trips.

## ISI-002 Build deterministic working-tree and artifact snapshots

- Status: completed
- Completion: auto
- Priority: P0
- Track: snapshot
- Depends on: ISI-001
- Goal id: ISI-G020
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/snapshot.py, tests/unit/logic/software_contracts/semantic_index/test_snapshot.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_snapshot.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/extraction
- Parallel lane: isi-snapshot
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 28000
- LLM context budget bytes: 229376
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 2, 6, and 10
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/snapshot.py, tests/unit/logic/software_contracts/semantic_index/test_snapshot.py
- Predicted symbols: RepositorySnapshot, SnapshotEntry, snapshot_repository, repository_identity
- Interfaces: SemanticRepositorySnapshot@1
- Conflict policy: Reuse `repository.py` conventions and `content.cid_for_bytes`; do not make watcher events or ambient traversal order authoritative. Do not follow symlink escapes or scan `.git`, caches, build outputs, virtualenvs, vendored trees, or semantic-index state stores.
- Preconditions: ISI model and identity records exist.
- Effects: Produces a sorted, race-aware input manifest for tracked plus non-ignored working files, Python files, pytest configuration, schemas, and dependency/lock artifacts.
- Acceptance: Git clean-tree and working-mutation modes are deterministic; non-Git fallback is sorted and bounded; unchanged scans have equal snapshot CIDs; missing/raced/oversized/undecodable inputs are explicit opaque artifacts; no target code is imported or executed.

## ISI-003 Extract Python symbols, contracts, effects, and confidence

- Status: completed
- Completion: auto
- Priority: P0
- Track: python-analysis
- Depends on: ISI-001
- Goal id: ISI-G020
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/python_analysis.py, tests/unit/logic/software_contracts/semantic_index/test_python_analysis.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_python_analysis.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/extraction
- Parallel lane: isi-python
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 40000
- LLM context budget bytes: 327680
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 5 through 8
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/python_analysis.py, tests/unit/logic/software_contracts/semantic_index/test_python_analysis.py
- Predicted symbols: PythonSemanticAnalyzer, PythonSymbolFacts, ConfidenceClassifier, analyze_python_source
- Interfaces: PythonSemanticAnalysis@1, AnalysisConfidence@1
- Conflict policy: Adapt `python_frontend.py` facts and parse only for missing symbol-local projections. Never import, eval, compile, or execute target code; never describe lexical calls as a complete call graph. Unknown decorators lower confidence.
- Preconditions: ISI models and dual identity adapters exist.
- Effects: Extracts modules, functions, async functions, classes, methods, properties, decorators, signatures, annotations/defaults, imports/direct lexical calls, inheritance/composition, global and instance state reads/writes, raises/catches, context managers, dataclasses, TypedDict, Enum, detectable Pydantic models, and explicit serialize/deserialize/validate operations.
- Acceptance: Normalized per-symbol AST excludes positions but preserves semantics; `eval`/`exec`, dynamic imports, reflection, metaclass mutation, runtime code generation, plugin discovery, native boundaries, constructed attributes, monkey patching, unknown decorators, and uncontrolled effects degrade affected confidence honestly; monkey-patched affected behavior is opaque; every symbol has exactly one confidence.

## ISI-004 Discover pytest tests, fixtures, markers, and configuration

- Status: completed
- Completion: auto
- Priority: P0
- Track: pytest-analysis
- Depends on: ISI-001
- Goal id: ISI-G020
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/pytest_analysis.py, tests/unit/logic/software_contracts/semantic_index/test_pytest_analysis.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_pytest_analysis.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/extraction
- Parallel lane: isi-pytest
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 28000
- LLM context budget bytes: 229376
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 6 through 9
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/pytest_analysis.py, tests/unit/logic/software_contracts/semantic_index/test_pytest_analysis.py
- Predicted symbols: PytestAnalyzer, PytestTestFacts, PytestFixtureFacts, PytestConfigurationFacts
- Interfaces: PytestSemanticAnalysis@1
- Conflict policy: Perform static syntax/config analysis only. Do not invoke pytest collection, import conftest modules, load plugins, or execute parametrization. Uncontrolled plugin discovery is conservative or opaque.
- Preconditions: ISI models exist.
- Effects: Identifies tests, fixtures, fixture dependencies, `usefixtures`, markers, parametrization declarations, pytest.ini/pyproject/setup.cfg/tox.ini/conftest influences, and test configuration artifacts.
- Acceptance: Fixture parameters and explicit markers/config edges are source-bound; fixture/config changes can later select exactly affected receipts; dynamic fixture/plugin construction is retained with reduced confidence rather than omitted or guessed exact.

## ISI-005 Implement verified local persistence and optional ipfs_kit adapter

- Status: completed
- Completion: auto
- Priority: P0
- Track: persistence
- Depends on: ISI-001
- Goal id: ISI-G050
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/persistence.py, tests/unit/logic/software_contracts/semantic_index/test_persistence.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_persistence.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/persistence
- Parallel lane: isi-persistence
- Resource class: cpu-small
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md section 10
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/persistence.py, tests/unit/logic/software_contracts/semantic_index/test_persistence.py
- Predicted symbols: SemanticIndexStore, LocalSemanticIndexStore, IpfsKitSemanticIndexStore, RootConflictError, compare_and_swap_root, recover
- Interfaces: SemanticIndexStore@1, StateRootCAS@1
- Conflict policy: Compose `cache.ImmutableCAS`; do not duplicate immutable publication, canonicalization, or CID logic. `ipfs_kit_py` is lazy, injected, optional, capability-checked, and never required by tests; backend CIDs must equal the sole software-contract identity.
- Preconditions: Durable ISI models can serialize to strict structured values.
- Effects: Persists/restores states, deltas, and plans by verified CID; maintains per-repository current root with locked expected-old compare-and-swap; performs deterministic replay and bounded orphan-temp recovery.
- Acceptance: Corruption is detected by decode/recompute; interrupted writes preserve the prior root and recover; two processes/threads racing with one expected root yield at most one successful distinct successor; identical writers are benign; no IPFS daemon/network/install is needed.

## ISI-010 Assemble deterministic repository states

- Status: completed
- Completion: auto
- Priority: P0
- Track: scanner
- Depends on: ISI-002, ISI-003, ISI-004
- Goal id: ISI-G020, ISI-G030
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, tests/unit/logic/software_contracts/semantic_index/test_scanner.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_scanner.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/graph
- Parallel lane: isi-scanner
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 4 through 8
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, tests/unit/logic/software_contracts/semantic_index/test_scanner.py
- Predicted symbols: RepositoryScanner, scan_repository_state
- Interfaces: RepositoryScanner@1, RepositoryState@1
- Conflict policy: `previous_state` may only reuse records whose input/source and extractor identities verify; it cannot change canonical output. Keep snapshot source of truth and no execution.
- Preconditions: Snapshot, Python analysis, and pytest analysis are complete.
- Effects: Maps frontend-local facts to stable/version identities, includes modules and typed artifacts, and emits a sorted deterministic pre-resolution `RepositoryState` with provenance and confidence.
- Acceptance: Cold and incremental scans of identical bytes have the same state-root CID; unrelated formatting preserves symbol identities; unrelated function edits do not version or stale every symbol; syntax/analysis failures remain explicit opaque records.

## ISI-011 Build and traverse the typed symbol graph

- Status: completed
- Completion: auto
- Priority: P0
- Track: symbol-graph
- Depends on: ISI-003, ISI-004
- Goal id: ISI-G030
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/symbol_graph.py, tests/unit/logic/software_contracts/semantic_index/test_symbol_graph.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_symbol_graph.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/graph
- Parallel lane: isi-graph
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 7 and 8
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/symbol_graph.py, tests/unit/logic/software_contracts/semantic_index/test_symbol_graph.py
- Predicted symbols: SymbolGraph, build_symbol_graph, resolve_edge_targets
- Interfaces: TypedSymbolGraph@1
- Conflict policy: Reuse bounded resolver statuses; unresolved and finite-may targets remain explicit. No guessed dynamic dispatch and no complete-call-graph claim. Traversal must be deterministic, bounded, and cycle-safe.
- Preconditions: Symbol and pytest facts exist.
- Effects: Emits `imports`, `calls`, `inherits`, `implements`, `reads_state`, `writes_state`, `raises`, `catches`, `serializes`, `deserializes`, `validates`, `tested_by`, `uses_fixture`, `configured_by`, `generated_from`, and `proof_depends_on` edges with all required metadata.
- Acceptance: Every edge includes source, typed target, relation, optional span, method, confidence, and extractor version; tests/fixtures/config/schema relations resolve when statically visible; ambiguity lowers confidence without silent omission.

## ISI-012 Diff repository states by semantic projection

- Status: completed
- Completion: auto
- Priority: P0
- Track: delta
- Depends on: ISI-010
- Goal id: ISI-G030
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/delta.py, tests/unit/logic/software_contracts/semantic_index/test_delta.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_delta.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/graph
- Parallel lane: isi-delta
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 28000
- LLM context budget bytes: 229376
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 5 and 9
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/delta.py, tests/unit/logic/software_contracts/semantic_index/test_delta.py
- Predicted symbols: diff_repository_states, classify_symbol_change
- Interfaces: RepositoryStateDelta@1
- Conflict policy: Compare stable IDs and closed semantic projections, not line positions or raw diff hunks. Rename correlation is heuristic metadata only and cannot forge stable identity continuity.
- Preconditions: Deterministic RepositoryState records exist.
- Effects: Classifies added/deleted/modified/unchanged symbols, artifacts and edges, plus body/signature/effects/exceptions/schema/decorator/confidence change facets.
- Acceptance: Formatting-only changes do not report semantic symbol modification; body-only edits stay local; signature/effect/exception/schema facets are distinguishable; deleted and heuristic rename candidates are deterministic; identical states yield an empty delta with stable CID.

## ISI-020 Implement explicit invalidation obligations

- Status: completed
- Completion: auto
- Priority: P0
- Track: invalidation
- Depends on: ISI-011, ISI-012
- Goal id: ISI-G040
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/invalidation.py, tests/unit/logic/software_contracts/semantic_index/test_invalidation.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_invalidation.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/invalidation
- Parallel lane: isi-invalidation
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 40000
- LLM context budget bytes: 327680
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md section 9
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/invalidation.py, tests/unit/logic/software_contracts/semantic_index/test_invalidation.py
- Predicted symbols: calculate_invalidation, InvalidationRule, InvalidationReason
- Interfaces: InvalidationEngine@1, InvalidationPlan@1
- Conflict policy: Emit obligations, never patches. Do not invalidate callers merely because a callee body changed when its public signature/effect/exception/schema contract is unchanged. Opaque evidence requires raw source.
- Preconditions: Typed graph and semantic delta exist.
- Effects: Implements all required body, signature, side-effect, exception, schema, fixture/config, dependency-lock, deletion, proof, test, adapter, security/purity, and opaque-source rules.
- Acceptance: Required examples produce precise reason-coded obligations such as new capsule, caller-signature mismatch, stale test receipt, obsolete schema adapter, proof rerun, or raw-source requirement; outputs are bounded, deduplicated, deterministic, and edge/source justified.

## ISI-021 Explain symbols and transitive impact honestly

- Status: completed
- Completion: auto
- Priority: P1
- Track: explanations
- Depends on: ISI-011
- Goal id: ISI-G040
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/explain.py, tests/unit/logic/software_contracts/semantic_index/test_explain.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_explain.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/invalidation
- Parallel lane: isi-explain
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 26000
- LLM context budget bytes: 212992
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 7 through 9
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/explain.py, tests/unit/logic/software_contracts/semantic_index/test_explain.py
- Predicted symbols: explain_symbol, explain_impact
- Interfaces: SymbolExplanation@1, ImpactExplanation@1
- Conflict policy: Explanations cite stored source/edge facts and confidence. Bound depth/node count and report truncation/unresolved paths; never promote heuristic evidence to source truth.
- Preconditions: Typed symbol graph is available.
- Effects: Produces deterministic direct facts, incoming/outgoing relationships, confidence degraders, source requirements, and bounded impact paths for symbols or changed sets.
- Acceptance: Unknown symbol errors are typed; cycles terminate; ordering is stable; opaque paths say raw source is required; file-to-symbol impact lookup is supported by stable artifact membership.

## ISI-022 Add debounced notification-only repository watching

- Status: completed
- Completion: auto
- Priority: P1
- Track: watcher
- Depends on: ISI-010
- Goal id: ISI-G050
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/watch.py, tests/unit/logic/software_contracts/semantic_index/test_watch.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_watch.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/persistence
- Parallel lane: isi-watch
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 24000
- LLM context budget bytes: 196608
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 6 and 11
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/watch.py, tests/unit/logic/software_contracts/semantic_index/test_watch.py
- Predicted symbols: watch_repository, RepositoryWatch, WatchNotification
- Interfaces: RepositoryWatch@1
- Conflict policy: Watcher events are hints only. Every emitted update must arise from a fresh canonical scanner result. Keep optional watcher libraries lazy; provide a hermetic polling path and clean shutdown.
- Preconditions: Canonical repository scanner exists.
- Effects: Debounces bursts, survives atomic replace/rename, suppresses unchanged state roots, invokes callback with new state/delta/plan or a documented equivalent, and exposes stop/context-manager lifecycle.
- Acceptance: Event order does not affect results; missed/coalesced events are corrected by snapshot scan; callback exceptions and shutdown do not leak threads; no network/daemon/install is used.

## ISI-023 Publish the required Python API and facade

- Status: todo
- Completion: auto
- Priority: P0
- Track: public-api
- Depends on: ISI-005, ISI-010, ISI-011, ISI-012, ISI-020, ISI-021, ISI-022
- Goal id: ISI-G060
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/index.py, ipfs_datasets_py/logic/software_contracts/semantic_index/__init__.py, tests/unit/logic/software_contracts/semantic_index/test_api.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_api.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/interface
- Parallel lane: isi-api
- Resource class: cpu-small
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 4 and 15
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/index.py, ipfs_datasets_py/logic/software_contracts/semantic_index/__init__.py, tests/unit/logic/software_contracts/semantic_index/test_api.py
- Predicted symbols: IncrementalSemanticIndex, scan_repository, diff_repository_states, calculate_invalidation, explain_symbol, explain_impact, watch_repository
- Interfaces: IncrementalSemanticIndex@1
- Conflict policy: Keep `__init__` exports thin and side-effect free. Do not import optional kit/watcher backends eagerly, mutate environment, invoke a model, or add service/global-singleton behavior.
- Preconditions: All component modules and tests are green.
- Effects: Composes canonical scan/diff/invalidation/explanation/watch/persistence into the exact requested function signatures and a small stateful facade.
- Acceptance: API accepts paths/state objects as documented, preserves pure deterministic functions, supports persistence by explicit injection, and ordinary feature import performs no install/network/process/thread/filesystem write or additional environment mutation.

## ISI-030 Add the dedicated semantic-index CLI

- Status: todo
- Completion: auto
- Priority: P0
- Track: cli
- Depends on: ISI-023
- Goal id: ISI-G060
- Outputs: ipfs_datasets_py/cli/semantic_index_cli.py, pyproject.toml, setup.py, tests/cli/test_semantic_index_cli.py
- Validation: python -m pytest -q tests/cli/test_semantic_index_cli.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/interface
- Parallel lane: isi-cli
- Resource class: cpu-small
- Implementation timeout seconds: 5400
- Provider role: codex-implement
- Context budget tokens: 28000
- LLM context budget bytes: 229376
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md section 11
- Predicted files: ipfs_datasets_py/cli/semantic_index_cli.py, pyproject.toml, setup.py, tests/cli/test_semantic_index_cli.py
- Predicted symbols: create_parser, main
- Interfaces: semantic-index CLI@1
- Conflict policy: Add the dedicated PEP 621 console entry and mirror legacy setup metadata; do not edit either monolithic `ipfs_datasets_cli.py`, add a service, or make optional storage mandatory.
- Preconditions: Public semantic-index API exists.
- Effects: Implements `scan`, `diff`, `impact`, `explain`, `watch`, and `state-root` commands with deterministic JSON, explicit store location/options, and stable error handling.
- Acceptance: Help and all six commands work in subprocess tests; old/new state references accept CIDs or documented files; symbol-or-file impact works; local default requires no daemon; malformed/missing/corrupt inputs return stable nonzero exits without traceback leakage.

## ISI-031 Prove the full mutation and persistence fixture matrix

- Status: todo
- Completion: auto
- Priority: P0
- Track: acceptance
- Depends on: ISI-023
- Goal id: ISI-G070
- Outputs: tests/fixtures/software_contracts/incremental_semantic_index, tests/unit/logic/software_contracts/semantic_index/test_acceptance.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_acceptance.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/acceptance
- Parallel lane: isi-fixtures
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 9, 10, and 13
- Predicted files: tests/fixtures/software_contracts/incremental_semantic_index, tests/unit/logic/software_contracts/semantic_index/test_acceptance.py
- Predicted symbols: required acceptance fixture matrix
- Interfaces: IncrementalSemanticIndexAcceptance@1
- Conflict policy: Test public APIs with compact copied fixture repositories. Do not duplicate implementation logic in test helpers, weaken confidence/invalidation assertions, require network/IPFS, or touch unrelated suites.
- Preconditions: Public API and local persistence exist.
- Effects: Covers formatting identity, unrelated edits, body/test impact, signature/callers, dataclass serializers, exceptions/recovery, fixture/config, lockfile/environment receipts, dynamic import, monkey patch, deletion/rename, identical roots, interrupted recovery, and concurrent root writers.
- Acceptance: Every fixture named in the user requirements has a direct assertion on stable/version identity, delta facet, confidence, typed edge, or exact invalidation obligation; concurrent and interrupted tests are deterministic and hermetic.

## ISI-032 Document capsule handoff, import safety, and run regressions

- Status: todo
- Completion: auto
- Priority: P0
- Track: closeout
- Depends on: ISI-030, ISI-031
- Goal id: ISI-G070
- Outputs: docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md, tests/unit/logic/software_contracts/semantic_index/test_import_safety.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts tests/cli/test_semantic_index_cli.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/acceptance
- Parallel lane: isi-closeout
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 32000
- LLM context budget bytes: 262144
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 13 through 15
- Predicted files: docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md, tests/unit/logic/software_contracts/semantic_index/test_import_safety.py
- Predicted symbols: SemanticIndexForCapsules
- Interfaces: SemanticCapsuleIndexConsumer@1, IncrementalSemanticIndexOperations@1
- Conflict policy: Documentation must describe current tested behavior and honest Python-analysis limits. Do not repair unrelated root import behavior, hide regressions, alter auto-install defaults, or expand into capsule generation/proving.
- Preconditions: CLI and acceptance matrix pass.
- Effects: Documents APIs, identities, confidence, edge schema, invalidation examples, persistence/recovery, CLI, known limitations, and the exact immutable interface a semantic-capsule consumer should read; verifies import subprocess has no feature-originated install/network/process/write/environment side effect under hermetic opt-outs.
- Acceptance: Focused and existing software-contract regressions pass; CLI help is hermetic; docs include example plans for body/signature/schema/opaque changes and exact capsule key/inputs; any unrelated failures are reported rather than suppressed.
