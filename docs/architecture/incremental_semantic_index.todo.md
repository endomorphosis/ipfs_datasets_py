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
W9  ISI-033 -> ISI-041 -> ISI-042
W10 ISI-034 | ISI-035 | ISI-037
W11 ISI-036
W12 ISI-038
W13 ISI-039
W14 ISI-040
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

## ISI-033 Make durable symbol identity total and self-verifying

- Status: completed
- Completion: auto
- Priority: P0
- Track: identity-repair
- Depends on: ISI-032
- Goal id: ISI-G080, ISI-G081
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/models.py, ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py, tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_models.py tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/identity-repair
- Parallel lane: isi-identity-repair
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 40000
- LLM context budget bytes: 327680
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 5 and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/models.py, ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py, tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Predicted symbols: SymbolRecord, RepositoryState, stable_symbol_id, symbol_version_cid, normalize_ast, canonical_literal
- Interfaces: StableSymbolIdentity@2, SymbolVersionIdentity@2, RepositoryState@2
- Conflict policy: Keep `logic/software_contracts/content.py` and strict DAG-JSON unchanged as the sole CID authority. Encode float/bytes/complex/Ellipsis AST constants with an injective tagged DAG-JSON projection; never permit raw floats or create a second canonical serializer. Preserve decorator order and duplicates because order is semantic. Do not add spans or definition ordinals to stable IDs.
- Preconditions: ISI-032 is merged and the audit baseline is pinned at `dd23a2197e900c2916aab1c4c60077f2bcfdd6e9`.
- Effects: Bumps the semantic-index schema; stores the normalized version projection needed to recompute every symbol version after restore; recomputes stable/version IDs during construction and deserialization; recursively freezes nested metadata; validates every symbol belongs to the state repository; supplies deterministic aggregate definition/accessor facets so overloads, repeated bindings, and property getter/setter/deleter sets do not collide.
- Acceptance: Identity/model round trips accept tagged float, bytes, complex, and Ellipsis constants plus repeated ordered decorators; changing any literal or decorator order changes the version CID. Forged kind/repository/version fields with old CIDs fail. Nested metadata mutation is impossible. Symbols whose repository ID differs from their containing state are rejected. Constructed overload/rebinding/property aggregate facets round-trip deterministically without a span-derived identity; formatting and unrelated fields still preserve stable logical IDs.

## ISI-041 Harden durable identity closure after audit false-green

- Status: completed
- Completion: auto
- Priority: P0
- Track: identity-closure
- Depends on: ISI-033
- Goal id: ISI-G080, ISI-G081
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/models.py, ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py, tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_models.py tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/identity-closure
- Parallel lane: isi-identity-closure
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 5 and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/models.py, ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py, tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Predicted symbols: SEMANTIC_INDEX_SCHEMA, SYMBOL_SCHEMA, SYMBOL_VERSION_ID_SCHEMA, SymbolRecord, normalize_ast, symbol_version_identity_payload, symbol_version_cid
- Interfaces: StableSymbolIdentity@2, SymbolVersionIdentity@2, RepositoryState@2
- Conflict policy: Repair the audited closure gaps in merged baseline `2f96cc5a02aa1a7d37aae3a2ee93105870bebc55` without rewriting completed ISI-033 evidence. Keep `logic/software_contracts/content.py` strict and authoritative. Do not silently interpret an unverifiable v1 record as v2, weaken CID recomputation, or edit scanner/extractor/persistence consumers in this task.
- Preconditions: ISI-033 is merged at implementation `0e73f9b9c` and completion marker `2f96cc5a0`; its focused tests passed but independent audit demonstrated that the durable identity contract remained open.
- Effects: Publishes an explicit v2 durable symbol/version schema; makes the normalized semantic projection mandatory for every v2 record construction/deserialization and version recomputation, with an explicit typed v1 migration adapter or typed legacy rejection if compatibility is retained; persists every version-CID input including extractor name/version, semantic-index schema, property role, signature, ordered decorators, annotations, and normalized AST; recursively freezes every stable/version identity input; canonically and injectively represents finite values, signed zero, and positive/negative infinity in float and complex components while continuing to reject values that cannot arise from a Python literal unless they have an explicit tag.
- Acceptance: Omitting `normalized_ast` from a v2 record or replacing it with a different projection fails with a typed model error. Forging extractor name/version, semantic-index schema, property role, signature, decorator order, annotation, or AST while retaining the old version CID fails restore. Mutating top-level or nested signature, annotations, metadata, normalized AST, or aggregate facets is impossible and cannot alter serialized/state identity. `ast.parse("x = 1e400")` and complex literals with positive/negative infinite components round-trip through distinct tagged projections and CIDs; positive/negative zero remain distinct. A v1 payload is accepted only through the named typed migration boundary and emerges as a fully verifiable v2 record, or is rejected explicitly. Tests exercise omitted/forged projections and attempted signature/annotation mutation rather than only metadata mutation.

## ISI-042 Reject source-impossible NaN identity inputs

- Status: completed
- Completion: auto
- Priority: P0
- Track: identity-closure
- Depends on: ISI-041
- Goal id: ISI-G080, ISI-G081
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py, tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_models.py tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/literal-admission
- Parallel lane: isi-identity-closure
- Resource class: cpu-small
- Implementation timeout seconds: 3600
- Provider role: codex-implement
- Context budget tokens: 16000
- LLM context budget bytes: 131072
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 5 and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py, tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Predicted symbols: normalize_ast, _float_projection, symbol_version_identity_payload, symbol_version_cid
- Interfaces: SymbolVersionIdentity@2
- Conflict policy: Repair only the audited literal-admission gap in merged baseline `5d517253577da9b0e77d80e88a2cdcf5a76db0da`. Preserve the completed ISI-041 record and its v2 schema, keep `logic/software_contracts/content.py` unchanged as the sole canonicalization/CID authority, and do not edit models, scanners, extractors, persistence, or control documents.
- Preconditions: ISI-041 is merged at implementation `520029a0f` and completion marker `5d5172535`; its 18 focused tests pass, but independent acceptance audit proved that `normalize_ast(float("nan"))` and complex values with a NaN component are admitted as the string projection `"nan"` even though no Python source literal can produce NaN.
- Effects: Rejects NaN float constants and either NaN component of a complex constant with `SemanticIndexModelError` before canonical DAG-JSON validation or CID construction. It retains the distinct tagged projections already established for positive/negative infinity and positive/negative zero.
- Acceptance: Direct normalization and `symbol_version_cid` reject `float("nan")`, `complex(float("nan"), 0.0)`, and `complex(0.0, float("nan"))` with the typed model error before the content hasher is invoked. The committed test proves the hasher was not called on each rejected input. Existing tests still prove distinct CIDs and round trips for positive/negative infinity, complex infinite components, and positive/negative zero.

## ISI-034 Root scans in exact Git blobs and snapshot identity

- Status: todo
- Completion: auto
- Priority: P0
- Track: snapshot-repair
- Depends on: ISI-042
- Goal id: ISI-G080, ISI-G082
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/snapshot.py, ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, tests/unit/logic/software_contracts/semantic_index/test_snapshot.py, tests/unit/logic/software_contracts/semantic_index/test_scanner.py, tests/fixtures/software_contracts/incremental_semantic_index/git_snapshot_truth
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_snapshot.py tests/unit/logic/software_contracts/semantic_index/test_scanner.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/snapshot-authority
- Parallel lane: isi-snapshot-repair
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 38000
- LLM context budget bytes: 311296
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 2, 6, and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/snapshot.py, ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, tests/unit/logic/software_contracts/semantic_index/test_snapshot.py, tests/unit/logic/software_contracts/semantic_index/test_scanner.py, tests/fixtures/software_contracts/incremental_semantic_index/git_snapshot_truth
- Predicted symbols: RepositorySnapshot, SnapshotFile, GitSnapshotProvider, RepositoryScanner, scan_repository_state
- Interfaces: RepositorySnapshot@2, RepositoryState@2
- Conflict policy: Adapt the bounded Git object inventory and cat-file patterns in `logic/software_contracts/repository.py`; do not reread a clean snapshot path after its Git blob was selected. Keep dirty filesystem bytes and clean Git bytes as explicit mutually exclusive sources, and keep watcher events non-authoritative. `scanner.py` is owned only by this task in W10.
- Preconditions: ISI-042 has closed and tested the v2 durable state and literal-admission schema.
- Effects: Carries selected bytes (or a verified immutable byte reference) from snapshot through parsing exactly once; records Git repository identity, commit OID, tree OID, tracked blob OIDs, snapshot CID, input disposition, and closed exclusions in the state root; bounds Git subprocesses; turns undecodable paths, unreadable files/directories, symlink escapes, oversize inputs, and read races into typed opaque artifacts; excludes semantic-index store/control files in both Git-dirty and filesystem modes.
- Acceptance: A clean fixture with a Git smudge filter produces symbols/source CIDs from the indexed blob rather than transformed worktree bytes. Mutating a file between snapshot selection and parse cannot mix bytes and becomes an explicit race/opaque artifact. Two identical clean scans retain identical commit/tree/snapshot/state roots, while two unrelated same-basename repositories without a shared Git identity do not silently share repository identity. Dirty tracked and untracked bytes are deterministic. `.semantic-index` and configured store files never enter the target state. Malformed names and unreadable inputs are represented, not silently omitted; Git commands time out with typed failure.

## ISI-035 Rebase Python extraction on the established frontend authority

- Status: todo
- Completion: auto
- Priority: P0
- Track: extraction-repair
- Depends on: ISI-042
- Goal id: ISI-G080, ISI-G082
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/python_analysis.py, tests/unit/logic/software_contracts/semantic_index/test_python_analysis.py, tests/fixtures/software_contracts/incremental_semantic_index/python_constructs
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_python_analysis.py tests/unit/logic/software_contracts/test_python_frontend.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/extraction-authority
- Parallel lane: isi-python-repair
- Resource class: cpu-large
- Implementation timeout seconds: 10800
- Provider role: codex-implement
- Context budget tokens: 50000
- LLM context budget bytes: 409600
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 2, 6, 7, and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/python_analysis.py, tests/unit/logic/software_contracts/semantic_index/test_python_analysis.py, tests/fixtures/software_contracts/incremental_semantic_index/python_constructs
- Predicted symbols: PythonSemanticAnalyzer, PythonAnalysisResult, analyze_python_source, aggregate_logical_bindings, classify_confidence
- Interfaces: PythonSemanticAnalysis@2
- Conflict policy: Consume/adapt `python_frontend.py` AST records, diagnostics, effects, and duplicate-definition facts instead of maintaining a weaker second frontend. Extend only missing semantic-index projections. Never import target code, infer a complete call graph, flatten whitespace inside literal values, or label unknown native/dynamic behavior exact.
- Preconditions: ISI-042 supplies closed v2 aggregate binding/version projections with source-impossible NaN rejected; this task does not edit scanner or graph files.
- Effects: Collects module, conditional and nested definitions; aggregates overload/rebinding/property roles; excludes independently addressed child bodies from parent body projections while preserving interfaces; renders signatures/defaults without changing string literal content; fixes generator scoping; emits alias-aware imports/calls/inheritance/composition; captures ordinary global reads/writes, destructuring/augmented/subscript instance-state access, raised/caught exception sets, context managers, dataclasses, class/functional TypedDict, Enum/IntEnum/StrEnum/Flag families, statically detectable Pydantic models, and explicit serializer/deserializer/validator targets. Confidence degrades for eval/exec, native imports, dynamic imports/attributes, decorators, metaclasses, monkey patching, reflection, plugins, code generation, and uncontrolled I/O with source-bound reasons.
- Acceptance: Editing one method body versions that method but not unrelated methods or the module merely because it contains the method. Analyzer output aggregates overload declarations and property getter/setter/deleter sets without duplicate stable IDs, retains repeated decorator order, and gives each facet version evidence. Defaults `"a  b"` and `"a b"` have distinct signature projections. `from ctypes import CDLL` and native calls are conservative/opaque, never exact. Conditional/nested definitions are present or explicit opaque records. Fixtures prove Pydantic fields, functional TypedDict, IntEnum/StrEnum/Flag, class composition, ordinary global reads, tuple catches, context managers, state reads/writes, decorator opacity, dynamic attribute opacity, and schema-target serialization without executing code.

## ISI-037 Bind persisted roots to repositories and process-safe CAS

- Status: completed
- Completion: auto
- Priority: P0
- Track: persistence-repair
- Depends on: ISI-042
- Goal id: ISI-G080, ISI-G082
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/persistence.py, tests/unit/logic/software_contracts/semantic_index/test_persistence.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_persistence.py tests/unit/logic/software_contracts/test_cache.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/root-binding
- Parallel lane: isi-persistence-repair
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 10 and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/persistence.py, tests/unit/logic/software_contracts/semantic_index/test_persistence.py
- Predicted symbols: SemanticIndexStore, LocalSemanticIndexStore, IpfsKitSemanticIndexStore, compare_and_swap_root, load_current_state, recover
- Interfaces: SemanticIndexStore@2, StateRootCAS@2
- Conflict policy: Compose `cache.ImmutableCAS` and authoritative CID recomputation; do not duplicate block identity/publication. The optional kit adapter remains lazy, injected, and capability checked. A platform without a reliable interprocess lock must fail closed rather than silently downgrade to thread-only CAS.
- Preconditions: ISI-042 v2 identity admission rejects omitted, forged, and source-impossible projections before persistence consumes them.
- Effects: Makes the store protocol concrete for state/delta/plan put/get and root operations; validates root-record CID, referenced state CID, and `state.repository_id` against the requested repository on every local and kit read/CAS; adds process-safe locked expected-old publication, explicit interruption points/WAL or equivalent recoverable transition records, atomic visibility, deterministic replay, and corruption/orphan recovery.
- Acceptance: A valid repository-B state installed under repository A is rejected on current-root read and CAS. A root record whose canonical bytes or referenced state mismatch is rejected. Two separate subprocess writers using one expected root yield exactly one distinct successor and one typed conflict. Injected interruption before/after object write, transition write, and root replace recovers to the last fully visible root. Corrupt blocks/transitions fail closed; local tests require no daemon/network/install, and the kit adapter enforces the same binding.

## ISI-036 Unify pytest identity and commit resolution into public state

- Status: todo
- Completion: auto
- Priority: P0
- Track: public-graph-repair
- Depends on: ISI-034, ISI-035
- Goal id: ISI-G080, ISI-G083
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/pytest_analysis.py, ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, ipfs_datasets_py/logic/software_contracts/semantic_index/symbol_graph.py, ipfs_datasets_py/logic/software_contracts/semantic_index/index.py, tests/unit/logic/software_contracts/semantic_index/test_pytest_analysis.py, tests/unit/logic/software_contracts/semantic_index/test_scanner.py, tests/unit/logic/software_contracts/semantic_index/test_symbol_graph.py, tests/unit/logic/software_contracts/semantic_index/test_api.py, tests/fixtures/software_contracts/incremental_semantic_index/pytest_identity
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_pytest_analysis.py tests/unit/logic/software_contracts/semantic_index/test_scanner.py tests/unit/logic/software_contracts/semantic_index/test_symbol_graph.py tests/unit/logic/software_contracts/semantic_index/test_api.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/public-semantic-truth
- Parallel lane: isi-public-graph-repair
- Resource class: cpu-large
- Implementation timeout seconds: 10800
- Provider role: codex-implement
- Context budget tokens: 50000
- LLM context budget bytes: 409600
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 6, 8, and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/pytest_analysis.py, ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, ipfs_datasets_py/logic/software_contracts/semantic_index/symbol_graph.py, ipfs_datasets_py/logic/software_contracts/semantic_index/index.py, tests/unit/logic/software_contracts/semantic_index/test_pytest_analysis.py, tests/unit/logic/software_contracts/semantic_index/test_scanner.py, tests/unit/logic/software_contracts/semantic_index/test_symbol_graph.py, tests/unit/logic/software_contracts/semantic_index/test_api.py, tests/fixtures/software_contracts/incremental_semantic_index/pytest_identity
- Predicted symbols: PytestAnalyzer, RepositoryScanner, SymbolGraph, resolve_edge_targets, scan_repository, IncrementalSemanticIndex
- Interfaces: PytestSemanticAnalysis@2, TypedSymbolGraph@2, RepositoryState@2, IncrementalSemanticIndex@2
- Conflict policy: Classify a test/fixture before final identity construction or deterministically merge its pytest facts into the one Python logical binding; never clone a second TEST/FIXTURE identity. Reuse bounded statuses/revision checks from `resolver.py`; resolution must occur before state-root computation, not only inside explanation helpers. Preserve unresolved/finite-may evidence and confidence.
- Preconditions: ISI-034 provides byte-rooted scanner inputs and ISI-035 provides complete analyzer bindings.
- Effects: Includes full AST/body/signature/decorators/annotations plus fixture scope/autouse/params/marker values in test/fixture versions; resolves/remaps call sources to unified IDs; models lexical fixture scope, conftest visibility, autouse, `usefixtures`, module/class/function `pytestmark`, marker arguments, and parametrization without treating parametrized value names as fixtures; stores resolved imports/calls/inheritance/schema/test/config/generated/proof relations in the returned public state; creates dependency/lock configuration edges to affected semantic/test/receipt artifacts where statically explicit.
- Acceptance: `scan_repository` alone returns a state whose resolvable calls target stable symbol CIDs, never a parallel `lexical:target`; a production signature change reaches real callers and pytest tests. A fixture body edit changes its one version CID and invalidates dependent tests. Autouse/usefixtures and same-named scoped fixtures resolve correctly. Parametrized argument names are not fixture dependencies unless independently supplied. Module/class marks and marker values affect versions. Real `tested_by`, `uses_fixture`, `configured_by`, serialization/schema, generated, and proof edges are source-rooted and survive round trip.

## ISI-038 Make delta, invalidation, and impact evidence-sound end to end

- Status: todo
- Completion: auto
- Priority: P0
- Track: invalidation-repair
- Depends on: ISI-036, ISI-037
- Goal id: ISI-G080, ISI-G083
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/delta.py, ipfs_datasets_py/logic/software_contracts/semantic_index/invalidation.py, ipfs_datasets_py/logic/software_contracts/semantic_index/explain.py, tests/unit/logic/software_contracts/semantic_index/test_delta.py, tests/unit/logic/software_contracts/semantic_index/test_invalidation.py, tests/unit/logic/software_contracts/semantic_index/test_explain.py, tests/unit/logic/software_contracts/semantic_index/test_public_pipeline_acceptance.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_delta.py tests/unit/logic/software_contracts/semantic_index/test_invalidation.py tests/unit/logic/software_contracts/semantic_index/test_explain.py tests/unit/logic/software_contracts/semantic_index/test_public_pipeline_acceptance.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/invalidation-e2e
- Parallel lane: isi-invalidation-repair
- Resource class: cpu-large
- Implementation timeout seconds: 10800
- Provider role: codex-implement
- Context budget tokens: 52000
- LLM context budget bytes: 425984
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 9 and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/delta.py, ipfs_datasets_py/logic/software_contracts/semantic_index/invalidation.py, ipfs_datasets_py/logic/software_contracts/semantic_index/explain.py, tests/unit/logic/software_contracts/semantic_index/test_delta.py, tests/unit/logic/software_contracts/semantic_index/test_invalidation.py, tests/unit/logic/software_contracts/semantic_index/test_explain.py, tests/unit/logic/software_contracts/semantic_index/test_public_pipeline_acceptance.py
- Predicted symbols: diff_repository_states, classify_symbol_change, calculate_invalidation, explain_symbol, explain_impact
- Interfaces: RepositoryStateDelta@2, InvalidationEngine@2, SymbolExplanation@2, ImpactExplanation@2
- Conflict policy: Recompute/verify any supplied delta from the two states and use only stored typed edges and durable projections. Never invent proof IDs, infer lockfiles by substring, treat every annotation as a schema, use a shared source CID as file membership, or traverse all relation types in one direction. Emit obligations only, never source rewrites.
- Preconditions: ISI-036 returns one resolved public graph and ISI-037 enforces state/root binding.
- Effects: Represents independent body/signature/effects/exceptions/schema/decorator/confidence facets so combined changes retain all facts; gives edge-only changes affected subjects; scopes schema rules to actual schema facets; follows incoming calls/inheritance and outgoing tested-by/config/schema/proof relations correctly; reruns only recorded proof obligations; propagates fixture/config/lock changes to linked tests and receipts; makes raw-source obligations resolve to exact repository path/source CID/span; bounds/deduplicates traversal by edge and path identity.
- Acceptance: A public scan/diff/invalidate pipeline, with no hand-authored edge, proves body-only relevant-test invalidation without unrelated callers, signature caller invalidation, exception recovery invalidation, dataclass field adapter invalidation, fixture/config test-receipt invalidation, and lock-dependent receipt invalidation. Body+signature retains both facets; a dataclass method or ordinary function annotation does not become a schema change; an edge-only change is actionable. A fabricated delta with matching state CIDs is rejected. No proof rerun exists without a `proof_depends_on` edge. Identical-byte files do not cross-contaminate impact, relation direction is correct, and opaque obligations identify retrievable raw source.

## ISI-039 Requalify public fixtures, CLI truth, and capsule handoff

- Status: todo
- Completion: auto
- Priority: P0
- Track: release-repair
- Depends on: ISI-038
- Goal id: ISI-G080, ISI-G084
- Outputs: ipfs_datasets_py/cli/semantic_index_cli.py, tests/fixtures/software_contracts/incremental_semantic_index, tests/unit/logic/software_contracts/semantic_index/test_acceptance.py, tests/unit/logic/software_contracts/semantic_index/test_import_safety.py, tests/cli/test_semantic_index_cli.py, docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md
- Validation: python -m pytest -q tests/unit/logic/software_contracts tests/cli/test_semantic_index_cli.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/release-requalification
- Parallel lane: isi-release-repair
- Resource class: cpu-large
- Implementation timeout seconds: 14400
- Provider role: codex-implement
- Context budget tokens: 52000
- LLM context budget bytes: 425984
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 11, 13, 15, and 16
- Predicted files: ipfs_datasets_py/cli/semantic_index_cli.py, tests/fixtures/software_contracts/incremental_semantic_index, tests/unit/logic/software_contracts/semantic_index/test_acceptance.py, tests/unit/logic/software_contracts/semantic_index/test_import_safety.py, tests/cli/test_semantic_index_cli.py, docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md
- Predicted symbols: semantic-index CLI commands, public acceptance fixture matrix, SemanticCapsuleIndexConsumer
- Interfaces: semantic-index CLI@2, IncrementalSemanticIndexAcceptance@2, SemanticCapsuleIndexConsumer@2
- Conflict policy: Acceptance tests must copy fixture repositories and exercise `scan_repository`, `diff_repository_states`, `calculate_invalidation`, and public explanations; they may not manufacture `DependencyEdge` or mutate returned states to create the expected result. Keep the CLI local/hermetic and do not hide failures, add a service, or implement capsule generation.
- Preconditions: ISI-038 proves the public resolved pipeline and persistence is repository-bound.
- Effects: Rebuilds every original fixture assertion on real scanner output; separates fixture-body changes from test/config changes; adds missing required Python/dynamic/persistence cases; makes the CLI's default store external to or canonically excluded from the indexed repository; makes impact/explain/watch scan current truth rather than silently returning a stored root; CAS-publishes accepted watch states consistently; gives missing/corrupt/root-conflict cases stable nonzero exits; replaces documentation-only capsule types with the exact implemented immutable fields/functions or documents the exact existing public adapter without fictional symbols.
- Acceptance: No public end-to-end acceptance test constructs a `DependencyEdge`. Unrelated formatting/function edits remain bounded; all requested body/signature/schema/exception/fixture/config/lock/dynamic/monkey-patch/delete/rename/determinism/recovery/concurrency cases pass through public APIs. In a clean Git fixture, `semantic-index scan` with default options does not create an indexed `.semantic-index/.roots.lock` or change the second root. After storing a root and editing source, `impact`, `explain`, and `watch --once` observe the edit; an accepted watch root is visible through `state-root`. Missing `state-root` is nonzero. CLI JSON/errors are deterministic, imports remain hermetic, documentation states only tested behavior, and every capsule key/input/type it names is publicly retrievable.

## ISI-040 Prove verified incremental reuse and bounded watcher operation

- Status: todo
- Completion: auto
- Priority: P1
- Track: incremental-repair
- Depends on: ISI-039
- Goal id: ISI-G080, ISI-G084
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, ipfs_datasets_py/logic/software_contracts/semantic_index/watch.py, tests/unit/logic/software_contracts/semantic_index/test_scanner.py, tests/unit/logic/software_contracts/semantic_index/test_watch.py, docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_scanner.py tests/unit/logic/software_contracts/semantic_index/test_watch.py tests/unit/logic/software_contracts/semantic_index/test_acceptance.py
- Board namespace: incremental-semantic-index-v1
- Bundle: isi/incremental-reuse
- Parallel lane: isi-incremental-repair
- Resource class: cpu-medium
- Implementation timeout seconds: 7200
- Provider role: codex-implement
- Context budget tokens: 36000
- LLM context budget bytes: 294912
- Plan context: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md sections 6, 11, and 16
- Predicted files: ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, ipfs_datasets_py/logic/software_contracts/semantic_index/watch.py, tests/unit/logic/software_contracts/semantic_index/test_scanner.py, tests/unit/logic/software_contracts/semantic_index/test_watch.py, docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md
- Predicted symbols: RepositoryScanner, scan_repository_state, RepositoryWatch, watch_repository
- Interfaces: IncrementalRepositoryScanner@1, RepositoryWatch@2
- Conflict policy: `previous_state` is only an optimization. Reuse a record only after repository, snapshot member/source CID, extractor, schema, and dependency inputs verify; rebuild the resolved graph deterministically. A watch event remains a hint and cannot replace a scan. Do not add optional watcher requirements or busy-wait.
- Preconditions: ISI-039 has a truthful public acceptance and CLI surface.
- Effects: Implements measured symbol/artifact reuse for unchanged verified inputs with cold/incremental root equivalence; exposes reuse diagnostics outside durable root identity; uses bounded configurable polling/debounce, subprocess timeouts inherited from snapshot, cancellation, finite join, context-manager cleanup, callback error isolation, and concurrent watcher fencing while suppressing unchanged roots.
- Acceptance: Instrumented fixtures prove unchanged source files reuse verified analysis while changed files and dependent resolution are recomputed; cold and incremental scans of the same bytes have byte-identical state records/root CIDs. Forged or schema/extractor/repository-mismatched previous states are never reused. Concurrent watchers converge on canonical state without duplicate authority, callback exceptions do not kill progress, stop/join finishes within a deterministic bound, polling does not busy-spin, and missed/coalesced events are corrected by the next canonical scan without network/daemon/install.
