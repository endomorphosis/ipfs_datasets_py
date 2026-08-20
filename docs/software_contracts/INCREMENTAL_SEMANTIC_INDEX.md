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
    IncrementalSemanticIndex,
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
repository bytes.  Cold and incremental scans of identical inputs produce
byte-identical state records and root CIDs.  A prior state is reused only after
repository identity, semantic-index schema, scanner extractor name/version, and
per-member `source_cid` values verify; forged or mismatched previous states are
ignored (treated as a cold scan).  Unchanged Python sources skip re-analysis
while pytest unification and graph resolution always recompute so dependents
stay current.  Reuse diagnostics are exposed on `RepositoryScanner.last_reuse_diagnostics`
(and `ScanReuseDiagnostics.to_dict`) outside durable root identity—they never
enter `RepositoryState` or its CID.

`explain_symbol` and `explain_impact` report only recorded facts and their
confidence limits.  `watch_repository` is notification-only; each notification
is established by a fresh deterministic scan.  The hermetic watcher uses bounded
polling (minimum poll interval, configurable debounce), isolates callback
exceptions so progress continues, joins within a deterministic timeout on
`stop`, and treats OS events as wake-up hints only—missed or coalesced events
are corrected by the next canonical scan.  Concurrent watches each own an
independent fence and converge on the same canonical `state_cid` without
sharing mutable authority.

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
| Function body changes | connected stale-test receipt (and body obligations when recorded) | Rerun only the plan's tests for the changed symbol. |
| Public signature changes | Body obligations plus `caller_signature_mismatch` on recorded incoming `calls` edges | Review each indicated call site; do not assume unrecorded dynamic callers are complete. |
| Dataclass/schema changes | Body obligations plus `obsolete_schema_adapter` for recorded serializer/deserializer/validator edges | Review every named adapter. |
| Opaque behavior (for example reflection or monkey patching) | `raw_source_required` with `opaque` confidence when emitted | Retrieve and review the raw source; do not mark work complete from graph traversal alone. |

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
default store is `<repository>/.semantic-index`, which is a canonical scanner
exclusion (alongside `.semantic_index` and `semantic-index-state`).  Library
imports and facade construction do not create a store.

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
or corrupt inputs have stable nonzero exits without a traceback.

- `scan` scans current repository bytes and CAS-publishes the resulting state
  root under the store (default `<repo>/.semantic-index`).
- `impact` and `explain` always scan current repository bytes.  A published
  root is only a verified `previous_state` optimization; it is never returned
  in place of a fresh scan.
- `watch --once` scans current bytes, CAS-publishes the accepted state, emits
  that state, and exits so `state-root` can observe the published root.
- `state-root` prints the published root.  A missing root is a nonzero exit.

Because the default store path is a scanner exclusion, a clean Git repository
scanned twice with default options does not index `.semantic-index/.roots.lock`
and does not change the second state root for identical repository bytes.

The semantic-index CLI implementation's help/parser path is hermetic when the
normal opt-outs are set: it does not scan, create a store, start a watcher,
contact a network, launch a process, write, or alter environment variables.
This promise is scoped to the feature; the repository's legacy broad
`ipfs_datasets_py.cli` package initialization is outside this API boundary.

## Semantic-capsule handoff

A capsule consumer reads immutable public records only; it must not call
private scanner visitors or depend on a mutable local-store path.  Capsule
generation itself is out of scope for this module.  The implemented public
surface a consumer uses is:

```python
from ipfs_datasets_py.logic.software_contracts.semantic_index import (
    calculate_invalidation,
    diff_repository_states,
    explain_symbol,
    scan_repository,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    DependencyEdge,
    RepositoryState,
    SymbolRecord,
)

state: RepositoryState = scan_repository("/work/repository")
# or LocalSemanticIndexStore(...).load_state(published_state_cid)

symbol: SymbolRecord = next(item for item in state.symbols if item.stable_id == stable_symbol_id)
outgoing: tuple[DependencyEdge, ...] = tuple(
    edge for edge in state.edges if edge.source_id == stable_symbol_id
)
incoming: tuple[DependencyEdge, ...] = tuple(
    edge for edge in state.edges if edge.target_id == stable_symbol_id
)
# Equivalent edge views are also available from:
explanation = explain_symbol(state, stable_symbol_id)
# explanation.symbol, explanation.outgoing_edges, explanation.incoming_edges
```

Raw source retrieval keys are the fields already present on `SymbolRecord`:

- `module_path` — repository-relative path
- `source_cid` — content CID of the source artifact
- `span` — optional `SourceSpan` (`path`, `start_line`, `start_column`, `end_line`, `end_column`) when available

The exact capsule cache key is the tuple of publicly retrievable symbol fields:

```text
(stable_id, version_cid, semantic_index_schema, extractor_version)
```

The exact invalidation inputs are the public functions:

```python
plan = calculate_invalidation(
    previous_state,  # RepositoryState
    current_state,   # RepositoryState
    diff_repository_states(previous_state, current_state),  # RepositoryStateDelta
)
# plan is an InvalidationPlan of InvalidationObligation records
```

The consumer retains the state roots (`RepositoryState.state_cid`), the symbol
record, relevant edges (including their confidence and metadata), and plan
obligations as evidence.  For an `opaque` symbol or edge it retrieves raw
source using `module_path`, `source_cid`, and `span` when available.  Heuristic
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
