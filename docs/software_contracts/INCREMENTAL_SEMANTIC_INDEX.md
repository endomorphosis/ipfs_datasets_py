# Incremental semantic index

`ipfs_datasets_py.logic.software_contracts.semantic_index` statically scans a
Python repository into immutable, deterministic semantic-index records.  It
does not import, execute, compile, or otherwise run code from the repository
being scanned.  The index is an evidence and invalidation boundary: it is not a
complete Python call graph, a capsule generator, or a proof engine.

## Public operations

The interoperability API is:

```python
from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    calculate_invalidation,
    diff_repository_states,
    explain_impact,
    explain_symbol,
    scan_repository,
    watch_repository,
)

before = scan_repository("/work/repository")
after = scan_repository("/work/repository", previous_state=before)
delta = diff_repository_states(before, after)
plan = calculate_invalidation(before, after, delta)
```

`scan_repository` returns a sorted `RepositoryState`.  `previous_state` is a
verified reuse optimization only: it cannot change the result for the same
repository bytes.  `explain_symbol` and `explain_impact` report only recorded
facts and their confidence limits.  `watch_repository` is notification-only;
each notification is established by a fresh deterministic scan.

Every durable record has a closed `to_dict`/`from_dict` schema and a CIDv1
identity computed through the software-contract content authority.  State,
delta, edge, symbol, artifact, invalidation-plan, and explanation records are
sorted and exclude wall-clock time, absolute host paths, and watcher order.

## Identities, confidence, and edges

A `SymbolRecord` deliberately has two identities.

- `stable_id` identifies the logical declaration.  It contains the stable-ID
  schema, repository identity, language, normalized repository-relative module
  path, qualified name, kind, and namespace.  It excludes source bytes, spans,
  comments, formatting, and definition ordinal.
- `version_cid` identifies the extracted semantic version: the stable ID,
  semantic-index schema, extractor name/version, normalized AST, signature,
  decorators/property role, and declared annotations.  Raw `source_cid` is
  separate provenance; it can change while `version_cid` remains stable.

Confidence is never promoted by combining evidence: `exact`, `conservative`,
`heuristic`, and `opaque` are reported separately on symbols and edges.
`DependencyEdge` supplies its source and target IDs, relation, extraction
method, extractor version, confidence, optional source span, and metadata.
Relations include imports, calls, inheritance, state reads/writes, raises and
catches, serializer/deserializer/validator links, test and fixture links,
configuration, generation, and proof dependencies.

## Invalidation examples

Always calculate a plan from the old state, current state, and their exact
delta.  A consumer must execute only the emitted obligations; it must not
invent dependency facts from names or rankings.

| Change | Typical plan evidence | Required consumer response |
| --- | --- | --- |
| Function body changes | `new_capsule`, `proof_rerun`, and connected stale-test receipt | Build the changed capsule, rerun the proof, and rerun only the plan's tests. |
| Public signature changes | Body obligations plus `caller_signature_mismatch` on recorded incoming `calls` edges | Review each indicated call site; do not assume unrecorded dynamic callers are complete. |
| Dataclass/schema changes | Body obligations plus `obsolete_schema_adapter` for recorded serializer/deserializer/validator edges | Rebuild the capsule and review every named adapter. |
| Opaque behavior (for example reflection or monkey patching) | `raw_source_required` with `opaque` confidence | Retrieve and review the raw source; do not mark work complete from graph traversal alone. |

Deletions emit retirement/dependent-review obligations.  Rename candidates are
heuristic annotations, not identity preservation.  Lock, pytest configuration,
and fixture changes can invalidate test or environment receipts independently
of a source-symbol change.

## Persistence and recovery

`LocalSemanticIndexStore` is an explicit local immutable store.  It stores
verified state objects and publishes a repository root with an expected-old
compare-and-swap.  Concurrent writers therefore get a `RootConflictError`
rather than silently replacing a newer root.  Interrupted root publications
are reported by `recover()` and do not become the current root.  The CLI's
default store is `<repository>/.semantic-index`; library imports and facade
construction do not create one.

## CLI

The dedicated module is usable without an IPFS daemon:

```bash
python -m ipfs_datasets_py.cli.semantic_index_cli --help
python -m ipfs_datasets_py.cli.semantic_index_cli scan /work/repository
python -m ipfs_datasets_py.cli.semantic_index_cli diff before.json after.json
python -m ipfs_datasets_py.cli.semantic_index_cli impact /work/repository pkg/module.py
python -m ipfs_datasets_py.cli.semantic_index_cli explain /work/repository <stable-symbol-cid>
python -m ipfs_datasets_py.cli.semantic_index_cli watch /work/repository --once
python -m ipfs_datasets_py.cli.semantic_index_cli state-root /work/repository
```

`diff` accepts state JSON files, one-line CID files, or stored CIDs with an
explicit `--store`.  Commands emit canonical sorted JSON.  Invalid, missing,
or corrupt inputs have stable nonzero exits without a traceback.  The
semantic-index CLI implementation's help/parser path is hermetic when the
normal opt-outs are set: it does not scan, create a store, start a watcher,
contact a network, launch a process, write, or alter environment variables.
This promise is scoped to the feature; the repository's legacy broad
`ipfs_datasets_py.cli` package initialization is outside this API boundary.

## Semantic-capsule handoff

A capsule consumer reads immutable public records only; it must not call
private scanner visitors or depend on a mutable local-store path.  Its minimal
view is equivalent to:

```python
class SemanticIndexForCapsules(Protocol):
    state_root_cid: str

    def symbol(self, stable_symbol_id: str) -> SymbolRecord: ...
    def outgoing_edges(self, stable_symbol_id: str) -> tuple[DependencyEdge, ...]: ...
    def incoming_edges(self, stable_symbol_id: str) -> tuple[DependencyEdge, ...]: ...
    def source_slice(self, stable_symbol_id: str) -> SourceSliceRef: ...
```

The exact capsule cache key is:

```text
(stable_symbol_id, version_cid, semantic_index_schema, extractor_version)
```

The exact invalidation inputs are:

```python
capsule_invalidation_inputs(
    previous_state: RepositoryState,
    current_state: RepositoryState,
    delta: RepositoryStateDelta,
) -> InvalidationPlan
```

The consumer retains the state roots, symbol record, relevant edges (including
their confidence and metadata), and plan obligations as evidence.  For an
`opaque` symbol or edge it retrieves raw source using the record's
repository-relative path, source CID, and span when available.  Heuristic
edges can inform retrieval or review priority, but never establish capsule or
proof completion.

## Analysis limits

Python name binding, descriptors, dispatch, import hooks, metaclasses,
decorators, monkey patches, plugin discovery, native extensions, reflection,
and dynamically constructed attributes can be unknowable statically.  Direct
lexical calls and finite resolver targets are useful but are not a complete
runtime call graph.  Reviewed pytest/package/lock formats have bounded config
semantics; serialization is exact only for explicit calls or closed
declarations, while naming patterns are heuristic.  These limitations lower
confidence and appear in explanations; they are never silently discarded.
