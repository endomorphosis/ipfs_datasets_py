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
|-- ISI-G070  Acceptance, documentation, and capsule handoff
`-- ISI-G080  Audited semantic-contract repair and release qualification
    |-- ISI-G081  Durable identity contract
    |-- ISI-G082  Snapshot, extraction, and persistence authority
    |-- ISI-G083  Public graph, delta, and invalidation truth
    `-- ISI-G084  End-to-end release and incremental operation
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
- Evidence: isi/inspection@1, isi/state-root@1, isi/invalidation-plan@1, isi/persistence@1, isi/acceptance@1, isi/audited-release@1
- Acceptance criteria: isi/inspection@1; isi/state-root@1; isi/invalidation-plan@1; isi/persistence@1; isi/acceptance@1; isi/audited-release@1
- Outputs: docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md, docs/architecture/incremental_semantic_index.objectives.md, docs/architecture/incremental_semantic_index.todo.md
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index tests/cli/test_semantic_index_cli.py
- Acceptance: Stable and version identities, graph, deltas, invalidation, persistence, explanations, watcher, API, CLI, and all required mutation fixtures pass without importing target repositories or requiring a daemon.
- Gap task: ISI-000 through ISI-050
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

## ISI-G080 Audited semantic-contract repair and release qualification

- Status: active
- Parent: ISI-G000
- Depends on: ISI-G070
- Fib priority: 34
- Priority: P0
- Track: contract-repair
- Bundle: isi/audited-release
- Goal: Close the concrete functional, identity, graph, persistence, invalidation, and CLI gaps found by the read-only audit of `dd23a2197e900c2916aab1c4c60077f2bcfdd6e9` before any capsule or coding-agent consumer treats the state as authoritative.
- Evidence: isi/identity-repair@1, isi/identity-closure@2, isi/literal-admission@1, isi/snapshot-authority@1, isi/snapshot-authority-closure@1, isi/snapshot-authority-closure@2, isi/snapshot-authority-protected-gate@1, isi/snapshot-authority-generation-closure@1, isi/snapshot-bootstrap-publication-closure@1, isi/extraction-authority@1, isi/python-inventory-closure@1, isi/python-relation-closure@1, isi/public-graph@1, isi/root-binding@1, isi/root-recovery-closure@1, isi/invalidation-e2e@1, isi/release-requalification@1
- Acceptance criteria: isi/identity-repair@1; isi/identity-closure@2; isi/literal-admission@1; isi/snapshot-authority@1; isi/snapshot-authority-closure@1; isi/snapshot-authority-closure@2; isi/snapshot-authority-protected-gate@1; isi/snapshot-authority-generation-closure@1; isi/snapshot-bootstrap-publication-closure@1; isi/extraction-authority@1; isi/python-inventory-closure@1; isi/python-relation-closure@1; isi/public-graph@1; isi/root-binding@1; isi/root-recovery-closure@1; isi/invalidation-e2e@1; isi/release-requalification@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index, ipfs_datasets_py/cli/semantic_index_cli.py, tests/unit/logic/software_contracts/semantic_index, tests/fixtures/software_contracts/incremental_semantic_index, tests/cli/test_semantic_index_cli.py, docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md
- Validation: python -m pytest -q tests/unit/logic/software_contracts tests/cli/test_semantic_index_cli.py
- Acceptance: Public scans are Git/filesystem-snapshot rooted, identity records are self-verifying, real resolved edges drive bounded invalidation, repository roots cannot cross-bind, dynamic behavior is never falsely exact, the CLI observes current truth, and every original mutation case passes without hand-authored dependency edges.
- Gap task: ISI-033 through ISI-050
- Refinement: Keep `software_contracts.content`, `repository`, `python_frontend`, `resolver`, and `cache.ImmutableCAS` authoritative; do not broaden into phase-two capsule compilation or an agent harness. After all four v11 Codex dispatches returned the authenticated hard capacity limit with retry at `2026-08-18T00:00:00Z`, exactly the unfinished ISI-050, ISI-043, ISI-044, ISI-036, ISI-038, ISI-039, and ISI-040 tasks route through `grok-implement`: authenticated Grok 4.5 is primary, and Codex is available only through the supervisor's typed quota-only fallback, never as a mock, simulation, anonymous provider, or silent fallback.

## ISI-G081 Durable identity contract

- Status: active
- Parent: ISI-G080
- Depends on: ISI-G070
- Fib priority: 2
- Priority: P0
- Track: contract-repair
- Bundle: isi/identity-repair
- Goal: Make stable/version identities total over legal Python syntax, recomputable from durable records, deeply immutable, repository-bound, and able to represent repeated decorators and legal aggregate bindings without span-derived identity.
- Evidence: isi/literal-projection@1, isi/id-recompute@1, isi/binding-aggregation@1, isi/identity-closure@2, isi/literal-admission@1
- Acceptance criteria: isi/literal-projection@1; isi/id-recompute@1; isi/binding-aggregation@1; isi/identity-closure@2; isi/literal-admission@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/models.py, ipfs_datasets_py/logic/software_contracts/semantic_index/identity.py, tests/unit/logic/software_contracts/semantic_index/test_models.py, tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_models.py tests/unit/logic/software_contracts/semantic_index/test_identity_contract.py
- Acceptance: V2 records persist and freeze every stable/version identity input, require a recomputable normalized projection, distinguish all legal finite/infinite literal components through strict tagged DAG-JSON, reject forged or unverifiable identity inputs, enforce repository membership, and retain deterministic aggregate facets. Legacy v1 data crosses only an explicit typed migration/rejection boundary.
- Gap task: ISI-033, ISI-041, ISI-042
- Refinement: Do not relax `content.py` or create a second CID/canonicalization authority.

## ISI-G082 Snapshot, extraction, and persistence authority

- Status: active
- Parent: ISI-G080
- Depends on: ISI-G081
- Fib priority: 3
- Priority: P0
- Track: authority-repair
- Bundle: isi/authority-repair
- Goal: Root state construction in exact Git/filesystem bytes, reuse the established non-executing Python frontend, and bind durable current roots to the repository under process-safe recovery.
- Evidence: isi/git-blob-truth@1, isi/snapshot-authority-closure@1, isi/snapshot-authority-closure@2, isi/snapshot-authority-protected-gate@1, isi/snapshot-authority-generation-closure@1, isi/snapshot-bootstrap-publication-closure@1, isi/python-authority@1, isi/python-inventory-closure@1, isi/python-relation-closure@1, isi/root-binding@1, isi/root-recovery-closure@1
- Acceptance criteria: isi/git-blob-truth@1; isi/snapshot-authority-closure@1; isi/snapshot-authority-closure@2; isi/snapshot-authority-protected-gate@1; isi/snapshot-authority-generation-closure@1; isi/snapshot-bootstrap-publication-closure@1; isi/python-authority@1; isi/python-inventory-closure@1; isi/python-relation-closure@1; isi/root-binding@1; isi/root-recovery-closure@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/snapshot.py, ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, ipfs_datasets_py/logic/software_contracts/semantic_index/python_analysis.py, ipfs_datasets_py/logic/software_contracts/semantic_index/persistence.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_snapshot_authority_adversarial.py tests/unit/logic/software_contracts/semantic_index/test_snapshot.py tests/unit/logic/software_contracts/semantic_index/test_scanner.py tests/unit/logic/software_contracts/semantic_index/test_python_analysis_authority_adversarial.py tests/unit/logic/software_contracts/semantic_index/test_python_relation_authority_adversarial.py tests/unit/logic/software_contracts/semantic_index/test_python_analysis.py tests/unit/logic/software_contracts/semantic_index/test_persistence.py
- Acceptance: Clean Git scans consume each selected indexed blob exactly once and retain portable stable repository plus commit-derived tree/blob/mode/disposition identity across commits, clones, and linked worktrees; an automatically identified unborn repository keeps its local identity when moved before its first commit, its private bootstrap marker is atomically and durably published under Git metadata, and identity plus snapshot mode derive from one captured HEAD generation or fail typed; caller-supplied identity avoids bootstrap metadata writes and is the only promised identity continuity through the first commit; a ctime-strength metadata-only acquisition witness preserves post-snapshot mutation-to-opaque behavior without a second content read; dirty, deleted, untracked, and unborn inputs remain explicit; raw paths, source lookup, ordinary artifacts, and synthetic snapshot evidence occupy collision-free domains; structural manifest CIDs recompute but parsing still requires independently supplied bytes that verify `source_cid`; Git failures or incomplete-traversal warnings fail closed; built-in/configured exclusions are filtered before bounds and cannot alter scan mode; canonical frontend facts drive inventory and exact-target typed relations; dynamic behavior is visibly conservative/opaque without erasing analyzable files; roots reject cross-repository states, process races fail closed, and legacy/current publication orphans recover without disturbing authoritative data.
- Gap task: ISI-034, ISI-035, ISI-037, ISI-043, ISI-044, ISI-045, ISI-046, ISI-047, ISI-048, ISI-049, ISI-050
- Refinement: ISI-034 and completed ISI-035/ISI-037 own disjoint primary files in the original authority wave. Completed ISI-046 follows ISI-034 on snapshot/scanner, completed ISI-047 retains its useful closure evidence, ISI-048 satisfies the original protected 33-case authority, ISI-049 closes the two protected durable-unborn/single-generation defects, and ISI-050 alone closes atomic bootstrap publication on the same production files. The first v12 ISI-050 candidate greened the original 41 protected cases but was stopped before merge because its PID/process-local-counter temporary did not proactively discover stale crash candidates, an exact reuse collision aborted rather than completed recovery, noncolliding residue could accumulate, and cleanup errors were swallowed; the protected authority is therefore 43 cases and requires cross-process stale-candidate recovery plus typed post-publication cleanup failure without discarding the durable winner. ISI-043 then follows ISI-050 and completed ISI-035 under a separate protected seven-case validation-only authority; ISI-044 alone follows ISI-043 on the shared extractor file with a distinct protected seven-case relation authority plus editable relation fixture. Disjoint completed ISI-045 follows ISI-037. `scanner.py` remains owned by the sequential ISI-034 -> ISI-046 -> ISI-047 -> ISI-048 -> ISI-049 -> ISI-050 chain until ISI-036.

## ISI-G083 Public graph, delta, and invalidation truth

- Status: active
- Parent: ISI-G080
- Depends on: ISI-G082
- Fib priority: 5
- Priority: P0
- Track: semantic-repair
- Bundle: isi/public-semantic-truth
- Goal: Unify Python and pytest symbol identity, commit bounded resolution into the public state root, and make deltas, impact, and invalidation operate only on recomputed stored evidence with correct relation direction.
- Evidence: isi/pytest-identity@1, isi/resolved-public-state@1, isi/invalidation-e2e@1
- Acceptance criteria: isi/pytest-identity@1; isi/resolved-public-state@1; isi/invalidation-e2e@1
- Outputs: ipfs_datasets_py/logic/software_contracts/semantic_index/pytest_analysis.py, ipfs_datasets_py/logic/software_contracts/semantic_index/scanner.py, ipfs_datasets_py/logic/software_contracts/semantic_index/symbol_graph.py, ipfs_datasets_py/logic/software_contracts/semantic_index/index.py, ipfs_datasets_py/logic/software_contracts/semantic_index/delta.py, ipfs_datasets_py/logic/software_contracts/semantic_index/invalidation.py, ipfs_datasets_py/logic/software_contracts/semantic_index/explain.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts/semantic_index/test_pytest_analysis.py tests/unit/logic/software_contracts/semantic_index/test_symbol_graph.py tests/unit/logic/software_contracts/semantic_index/test_delta.py tests/unit/logic/software_contracts/semantic_index/test_invalidation.py tests/unit/logic/software_contracts/semantic_index/test_explain.py tests/unit/logic/software_contracts/semantic_index/test_public_pipeline_acceptance.py
- Acceptance: The public state has no resolvable `lexical:*` call targets, real tests and fixtures share analyzer identities, edge-only and combined changes are retained, fabricated deltas fail, and tests/callers/adapters/proofs become stale only through typed stored evidence.
- Gap task: ISI-036, ISI-038
- Refinement: ISI-038 follows ISI-036; neither may use manually fabricated graph edges as end-to-end proof.

## ISI-G084 End-to-end release and incremental operation

- Status: active
- Parent: ISI-G080
- Depends on: ISI-G083
- Fib priority: 8
- Priority: P0
- Track: release-repair
- Bundle: isi/release-requalification
- Goal: Rebuild the fixture/CLI/documentation acceptance surface around current public truth, then prove verified symbol-level reuse and bounded watcher operation.
- Evidence: isi/public-fixtures@2, isi/cli-current-truth@1, isi/capsule-interface@2, isi/incremental-reuse@1
- Acceptance criteria: isi/public-fixtures@2; isi/cli-current-truth@1; isi/capsule-interface@2; isi/incremental-reuse@1
- Outputs: tests/fixtures/software_contracts/incremental_semantic_index, tests/unit/logic/software_contracts/semantic_index/test_acceptance.py, tests/cli/test_semantic_index_cli.py, ipfs_datasets_py/cli/semantic_index_cli.py, docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md, ipfs_datasets_py/logic/software_contracts/semantic_index/watch.py
- Validation: python -m pytest -q tests/unit/logic/software_contracts tests/cli/test_semantic_index_cli.py
- Acceptance: Original requirements pass through public APIs without hand-made edges; the default CLI store cannot alter indexed truth, impact/explain/watch see edits, documented capsule inputs exist exactly as stated, prior-state reuse is verified, and watcher cancellation/polling remains bounded.
- Gap task: ISI-039, ISI-040
- Refinement: ISI-039 is the phase-two authority gate; ISI-040 may optimize only after identical cold/incremental roots are proven.
