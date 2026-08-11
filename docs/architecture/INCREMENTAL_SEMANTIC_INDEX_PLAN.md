# Incremental Semantic Index implementation plan

Status: active implementation and contract-repair plan
Reviewed repository: `endomorphosis/ipfs_datasets_py`  
Reviewed commit: `a2f5400b7cb89c8481819379a1b7b9959fe81d45`  
Reviewed tree: `7dde1f0a86e64576ac316c674c1b4a0995da909c`  
Post-implementation audit baseline: `dd23a2197e900c2916aab1c4c60077f2bcfdd6e9`
Identity false-green audit baseline: `2f96cc5a02aa1a7d37aae3a2ee93105870bebc55`
Plan date: 2026-08-11  
Supervisor task prefix: `ISI-`

## 1. Outcome and scope

Implement one focused `IncrementalSemanticIndex` owned by
`ipfs_datasets_py.logic.software_contracts.semantic_index`. It scans a Python
repository without importing or executing it, assigns separate stable logical
and version identities to symbols, builds a typed dependency graph, compares
repository states, and emits bounded, explainable invalidation obligations.

The implementation includes a hermetic content-addressed state store, an
optional narrow `ipfs_kit_py` persistence adapter, a notification-only watcher,
and the `semantic-index` CLI. It does not add an agent framework, service, UI,
MCP server, theorem prover, code generator, context packer, or multi-language
frontend. It does not automatically rewrite dependent source.

## 2. Repository inspection and authority decisions

The following production modules were inspected before planning:

- `logic/software_contracts/content.py` and
  `docs/software_contracts/CID_PROFILE_V1.md`: the explicit sole authority for
  strict software-contract canonical DAG-JSON and real CIDv1 identifiers.
- `logic/software_contracts/ast_ir.py`: closed module, scope, signature,
  symbol, import, reference, call, effect, diagnostic, span, and provenance
  records. Its existing frontend-local symbol IDs contain spans and are not
  suitable as stable semantic IDs.
- `logic/software_contracts/python_frontend.py`: versioned, non-executing
  CPython-AST extraction for Python modules, callables, classes, signatures,
  decorators, annotations, defaults, imports, lexical references/calls,
  object/global effects, raises, awaits, context managers, and unsupported
  dynamic behavior.
- `logic/software_contracts/resolver.py`: pinned, non-executing resolution with
  definite, finite-may, unresolved, optional, missing, and revision-mismatch
  outcomes. This is useful for bounded call/import edges but is not a complete
  Python call graph.
- `logic/software_contracts/repository.py`: deterministic Git-object inventory
  and parser disposition. It remains the clean-tree authority; mutation scans
  need an additional sorted filesystem-snapshot adapter that observes working
  bytes.
- `logic/software_contracts/cache.py`: `ImmutableCAS`, fsync/no-replace
  publication, verified reads, corruption detection, locks, and atomic-index
  patterns.
- `logic/software_contracts/contracts.py`, `registry.py`, `coverage.py`,
  `schema_versions.py`, and `__init__.py`: downstream contract, evidence,
  schema, and provenance conventions.
- `knowledge_graphs/storage/ipfs_kit.py`: optional injected-client capability
  and verification pattern only; it is not a new content-identity authority.
- `knowledge_graphs/adapters/code_evidence.py`: compatibility shape for graph
  and impact exports, not an identity authority.
- `logic/software_verification/source_adapters.py`, `program.py`, `ir.py`,
  `receipts.py`, and `tactician/proof_graph.py`: downstream verification and
  proof consumers.
- Relevant tests under `tests/unit/logic/software_contracts/`, especially
  `test_content_identity.py`, `test_ast_ir.py`, `test_python_frontend.py`,
  `test_resolver.py`, `test_repository_manifest.py`, and `test_cache.py`.

No existing repository-level `IncrementalSemanticIndex`, production pytest
relationship discovery, or complete Python call graph was found. The smallest
owner is therefore a subpackage of `logic/software_contracts`, not a new
top-level `code_semantics` package.

Authority rules:

1. All source and structured CIDs use only
   `logic.software_contracts.content` (`cid_for_bytes`,
   `canonical_dag_json_bytes`, `cid_for_structured`, `validate_cid`, and
   decode/recompute verification).
2. `cache.ImmutableCAS` remains the local immutable object store; the feature
   adds only state serialization, an expected-old-root compare-and-swap ref,
   and recovery around it.
3. Existing AST facts and resolver outcomes are adapted; span-derived IDs are
   never exposed as stable logical identities.
4. Watch events never establish state. Every callback follows a deterministic
   Git-tree or sorted filesystem snapshot scan.
5. The audit at `dd23a2197e900c2916aab1c4c60077f2bcfdd6e9` found that
   tasks ISI-001 through ISI-032 provide a useful scaffold but do not yet
   satisfy these authority rules end to end. In particular, the public scan
   returns pre-resolution edges, the new extractor bypasses stronger
   `python_frontend` facts, and clean Git blobs are reread from the worktree.
   ISI-033 through ISI-040 below are therefore release gates, not optional
   enhancements.
6. ISI-033 merged at completion marker
   `2f96cc5a02aa1a7d37aae3a2ee93105870bebc55`, but independent audit found
   that its focused tests false-greened an optional normalized projection,
   mutable signature/annotation inputs, non-finite legal literal rejection,
   and unchanged v1 schema constants. ISI-041 preserves the completed evidence
   and closes those recorded v2 identity defects at completion marker
   `5d517253577da9b0e77d80e88a2cdcf5a76db0da`. A subsequent independent
   acceptance audit proved that its float projection still admits NaN even
   though NaN cannot arise from a Python source literal. ISI-042 preserves the
   truthful completed ISI-041 evidence and is the final mandatory literal
   admission gate before snapshot, extraction, or persistence repair may
   proceed.
7. ISI-035 and ISI-037 are truthfully recorded as completed at marker
   `a090afad2`, but a post-merge source/probe audit of their implementations
   `bf827c9bb` and `aa1e64aba` found two further release blockers. Python
   extraction still maintains a weaker inventory beside the canonical
   frontend, loses required version/edge/confidence facts, and can cause
   nonfatal frontend notices to erase a file from a public scan. Persistence
   recovery recognizes current transition temporaries but not the legacy
   `.root-*` form in the transition directory. ISI-043 and ISI-044 close the
   extractor defects sequentially after the canonical-byte gate; disjoint
   ISI-045 closes both temporary-prefix recovery forms in parallel.
8. ISI-034 completed at marker `92b7cdbd6`, but its live-candidate audit
   proved that no-origin repository identity incorporates current `HEAD`, so
   even a same-tree commit changes every stable symbol ID. Its merged snapshot
   also omits commit/per-entry blob identity and rereads clean content in the
   scanner after hashing it. ISI-046 preserves ISI-034's truthful completed
   evidence and was introduced to close stable repository identity, exact captured-byte
   handoff, malformed-path/unreadable-traversal retention, exclusion-before-
   mode selection, and Git failure/warning disposition before Python inventory
   repair may start.
9. Two ISI-046 provider proposals were correctly rejected by the proposal
   gate because they renamed and weakened the existing post-snapshot mutation
   test. The repair must keep that assertion: acquisition may read content
   exactly once and carry those bytes, while a non-content acquisition witness
   permits the scanner to detect a later working-file replacement and emit an
   opaque raced input without reopening the file for content. Rejected
   candidates also proved that host device/inode identity is not a durable
   committed-Git identity, dirty snapshots must not discard commit/tree/blob
   evidence, and malformed/reserved raw names need collision-free domains.
10. ISI-046 later completed at marker `44876f4b4`, but immutable audit of its
    merged implementation `bebe7752a` proved another focused-test false green.
    Structural content addressing authenticates bytes supplied to the CID
    function; it does not authenticate an attacker-selected replacement
    manifest. ISI-047 therefore closes atomic commit-to-tree selection,
    portable born identity, mode/disposition/exclusion identity, metadata-only
    generation fencing, and raw-path/source/artifact domain separation. A
    restored manifest without captured or independently retrieved source bytes
    remains a claim and cannot authorize parsing by itself.
11. ISI-047 completed at marker `c63c57b9e` after implementation
    `e90a13cd7` merged as `595d4dd93`, but its 22 declared tests again
    false-greened a wider prose contract. An independently protected 33-item
    public adversarial module produces exactly 13 failures and 20 passes: it
    proves unrelated unborn identity collision, imprecise unborn disposition,
    same-HEAD status/index race acceptance, nested configured-exclusion
    failures, corrupt-marker filesystem downgrade, quiet born-HEAD downgrade,
    accepted empty/non-ASCII HEAD identity output, leaked symbolic-HEAD decode
    failure, and accepted successful HEAD warnings. ISI-048 is therefore the
    final snapshot authority gate. It may repair only snapshot/scanner
    production code and cannot own or edit the protected adversarial test.
12. ISI-048 completed at marker `3a11ef85f` after implementation
    `ee0bc3b54` merged as `a9d4096fd`; its protected 33 cases and 22 retained
    focused cases all pass, and the broader semantic-index suite retains the
    exact known 19 downstream failures. Two additional independent probes
    expose a remaining generation contract gap: the automatically generated
    unborn identity is derived from the resolved Git path and therefore
    changes when the repository is moved before its first commit, and
    `snapshot_repository` can combine an unborn identity with a born snapshot
    mode when the first commit appears between its identity and HEAD probes.
    ISI-049 is the narrow final snapshot-generation closure. It may repair only
    snapshot/scanner production code and cannot own or edit the now-35-case
    protected adversarial test.

## 3. Proposed package and files

```text
ipfs_datasets_py/logic/software_contracts/semantic_index/
  __init__.py          public exports only
  models.py            closed schemas/enums/value objects
  identity.py          stable and version identity adapters
  snapshot.py          deterministic Git/filesystem inputs and artifacts
  python_analysis.py   symbol-level Python semantic extraction
  pytest_analysis.py   tests, fixtures, markers, dependencies, config
  scanner.py           RepositoryState construction and incremental reuse
  symbol_graph.py      typed target resolution and graph traversal
  delta.py             deterministic state comparison
  invalidation.py      explicit stale-obligation rules
  explain.py           symbol and impact explanations
  persistence.py       ImmutableCAS state store, root CAS, optional kit adapter
  watch.py             debounced notification adapter
  index.py             IncrementalSemanticIndex facade and required functions

ipfs_datasets_py/cli/semantic_index_cli.py
tests/unit/logic/software_contracts/semantic_index/
tests/fixtures/software_contracts/incremental_semantic_index/
tests/cli/test_semantic_index_cli.py
docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md
```

The exact file split may be collapsed where implementation evidence shows a
smaller cohesive surface, but ownership and public behavior must not move
outside `logic/software_contracts`.

## 4. Public API

The package must export equivalent typed functions:

```python
scan_repository(repo_path, previous_state=None) -> RepositoryState

diff_repository_states(
    previous_state: RepositoryState,
    current_state: RepositoryState,
) -> RepositoryStateDelta

calculate_invalidation(
    previous_state: RepositoryState,
    current_state: RepositoryState,
    delta: RepositoryStateDelta,
) -> InvalidationPlan

explain_symbol(
    repository_state: RepositoryState,
    symbol_id: str,
) -> SymbolExplanation

explain_impact(
    repository_state: RepositoryState,
    changed_symbol_ids: Iterable[str],
) -> ImpactExplanation

watch_repository(
    repo_path,
    callback,
    *,
    debounce_ms: int = 250,
)
```

`IncrementalSemanticIndex` may provide stateful convenience methods around the
same pure functions, but those functions are the interoperability boundary.
All durable models have deterministic `to_dict`/`from_dict` forms, closed
schema names, and stable ordering.

## 5. Identity contract

Every symbol carries two distinct CIDv1 values.

### Stable logical identity

The canonical payload contains only:

- stable-ID schema version;
- repository identity;
- language (`python`);
- normalized repository-relative module path;
- qualified symbol name;
- normalized symbol kind;
- interface namespace or package name.

It excludes line/column/byte spans, source CID, body, formatting, comments,
and definition ordinal. The ID is computed with `content.cid_for_structured`.
Renames and deletions are represented explicitly; rename detection may be a
heuristic delta annotation but never preserves a logically changed ID by
guessing.

### Version identity

The version payload contains:

- version-ID schema and semantic-index schema versions;
- extractor name and version;
- the stable logical symbol ID;
- normalized AST for exactly that symbol (location attributes removed);
- public signature, parameter kinds, normalized defaults;
- decorators and property role;
- declared parameter, return, base, class-variable, and field annotations.

A semantic mutation changes the CID. Formatting outside the symbol and
format-only changes inside the symbol do not. Raw source CID remains separate
provenance and may change when the version CID does not.

Repository-state and delta roots are CIDs over sorted closed records. Wall
clock time, absolute host paths, watcher event order, and dictionary insertion
order are excluded.

## 6. Snapshot and extraction pipeline

```text
watch/Git/filesystem notification
        |
        v
sorted canonical snapshot (source of truth)
        |
        +-- Python bytes -> existing python_frontend ASTRecord
        |                 -> semantic-index enrichment
        |
        +-- pytest/config/lock/schema artifacts
        |
        v
stable-ID symbol table -> bounded resolver -> typed edges
        |
        v
deterministic RepositoryState CID
```

For a clean pinned tree, reuse the Git-object inventory patterns in
`repository.py`. For a working mutation, enumerate deterministic inputs with
`git ls-files --cached --others --exclude-standard` when Git is present, or a
sorted filesystem walk with a closed ignore policy otherwise, then read each
selected file once. Symlink escapes, undecodable/oversized files, parse errors,
and races become typed opaque artifacts rather than silent omissions.

The scanner supports modules, functions, async functions, classes, methods,
properties, decorators, signatures, annotations, defaults, imports, direct
lexical calls, inheritance, static class composition, global and instance
state reads/writes, raised/caught exceptions, context managers, dataclasses,
TypedDicts, Enums, statically detectable Pydantic-style models, pytest tests,
fixtures, markers and fixture dependencies, test configuration, explicit
serialization/deserialization/validation relationships, and dependency or
lock files. It never imports, evaluates, compiles to bytecode, or invokes code
from the target repository.

`previous_state` is an optimization only. Unchanged source/artifact CIDs may
reuse verified prior records. The same canonical snapshot must produce the
same state whether scanned cold or incrementally.

## 7. Confidence model

Every symbol has exactly one of `exact`, `conservative`, `heuristic`, or
`opaque`. Every edge separately records its own confidence. Confidence only
degrades as facts are combined.

- `exact`: closed declarations such as a literal dataclass field list,
  function signature, direct `raise`, or explicit pytest fixture parameter.
- `conservative`: a finite may-set or lexical behavior that can overapproximate
  but must not knowingly omit analyzer-visible behavior.
- `heuristic`: retrieval/ranking evidence such as a rename candidate or a
  naming-based serializer relation; never substitutes for source.
- `opaque`: analysis is insufficient and raw source is required.

Dynamic imports, unknown decorators, plugin discovery, uncontrolled I/O, and
reflection reduce confidence. `eval`, `exec`, runtime code generation,
monkey-patching of analyzed objects, metaclass mutation, native extension
boundaries, or dynamically constructed attribute names make the affected
behavior opaque unless a narrower closed declaration remains independently
exact. The module never claims a complete Python call graph.

## 8. Dependency graph

The closed relation vocabulary is:

`imports`, `calls`, `inherits`, `implements`, `reads_state`, `writes_state`,
`raises`, `catches`, `serializes`, `deserializes`, `validates`, `tested_by`,
`uses_fixture`, `configured_by`, `generated_from`, and `proof_depends_on`.

Every `DependencyEdge` includes source stable symbol ID, target symbol ID or
typed artifact ID, relation, optional source span, extraction method,
confidence, and extractor version. Targets unresolved by the bounded resolver
remain explicit artifact/unknown targets. Graph collections and traversal
results are sorted and cycle-safe.

## 9. Delta and invalidation rules

The delta distinguishes added, deleted, stable-ID-preserving modified,
unchanged, and heuristic rename-candidate symbols; added/removed/modified
artifacts; and edge changes. A symbol change is classified into body,
signature, effect-set, exception-contract, schema, metadata/decorator, or
confidence changes by comparing canonical projections rather than source
lines.

The invalidation engine emits ordered `InvalidationObligation` records with a
reason code, triggering old/new identities, affected subject/artifact,
supporting edge IDs, confidence, and remediation kind. Rules are explicit:

| Change | Required bounded invalidation |
|---|---|
| Function body | New capsule and direct proof obligations; relevant tests; callers remain valid when signature/effects/exceptions are unchanged |
| Public signature | Callers, adapters/interface descriptions, and relevant tests |
| Side-effect set | Purity/security claims and callers whose recorded assumptions relied on the old set |
| Exception contract | Recovery assumptions and tests covering raised/caught behavior |
| Dataclass/TypedDict/Enum/Pydantic schema | serializers, deserializers, validators, storage/API adapters, and tests |
| Fixture or test config | receipts of tests using the fixture/configuration |
| Dependency/lock version | environment-bound semantic and verification receipts |
| Deleted symbol | its capsule/proofs plus resolved dependents; unresolved dynamic reachability stays explicit |
| Opaque behavior | raw source retrieval obligation; no exact safety claim |

The plan never requests automatic source rewriting.

## 10. Persistence protocol

`LocalSemanticIndexStore` composes `cache.ImmutableCAS` for state/delta/plan
objects. Reads always decode and recompute the authoritative software-contract
CID. A per-repository current-root ref uses a process/thread lock, rereads the
current valid value under the lock, compares it with `expected_old_cid`, and
publishes an atomic/fsynced replacement. A mismatch raises a typed conflict;
two writers cannot silently overwrite each other.

Interrupted publication leaves the last valid root authoritative. Startup
removes or ignores only recognized orphan temporary files after validating the
root and referenced objects. Replay loads immutable states/deltas by CID and
recomputes results deterministically.

The optional `IpfsKitSemanticIndexStore` is dependency-injected and lazy. It
stores canonical DAG-JSON bytes, verifies that the backend-returned CID equals
`content.cid_for_structured`, verifies every fetched block, and delegates root
CAS to an explicitly capable backend or refuses it. Importability alone is not
a capability grant; no daemon, network, install, or environment mutation is
required for local use or tests.

## 11. CLI and watcher

Add the dedicated console entry point
`semantic-index = ipfs_datasets_py.cli.semantic_index_cli:main` in
`pyproject.toml`, mirrored in legacy `setup.py`. It exposes:

```text
semantic-index scan <repo>
semantic-index diff <old-state> <new-state>
semantic-index impact <repo> <symbol-or-file>
semantic-index explain <repo> <symbol>
semantic-index watch <repo>
semantic-index state-root <repo>
```

Machine-readable JSON is deterministic. User errors, missing objects,
integrity failures, and root conflicts have stable nonzero exit behavior. The
CLI imports no optional storage or watcher dependency until selected.

The watcher may use an optional installed backend or a polling fallback. It
coalesces notifications by `debounce_ms`, then invokes the canonical scan.
Event ordering or missed notifications cannot change semantic truth.

## 12. Parallel implementation DAG

The machine taskboard is `incremental_semantic_index.todo.md`; goal hierarchy
is `incremental_semantic_index.objectives.md`.

```text
W0  ISI-000 (inspection/control seal, already completed)
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
W10a ISI-045
W11 ISI-046
W12 ISI-047
W13 ISI-048
W14 ISI-049
W15 ISI-043
W16 ISI-044
W17 ISI-036
W18 ISI-038
W19 ISI-039
W20 ISI-040
```

Tasks in each parallel wave own disjoint modules and tests. Integration tasks
depend on their inputs. Supervisor workers must honor `Outputs`, `Predicted
files`, and `Conflict policy`; plan/objective/taskboard files are read-only
protected control inputs. Phase-two capsule or coding-agent work must not treat
the semantic state as authoritative until ISI-042, ISI-034 through ISI-039,
and post-merge closure tasks ISI-043 through ISI-049 pass in their declared
dependency order. ISI-040 is the
final incremental-performance and watcher hardening wave.

## 13. Validation and acceptance

Required fixture evidence covers:

1. formatting stability of logical and version identities;
2. bounded unrelated-function edits;
3. body-change test invalidation;
4. signature-change caller invalidation;
5. dataclass schema serializer/deserializer invalidation;
6. exception recovery invalidation;
7. fixture and test-config receipt invalidation;
8. lockfile/environment receipt invalidation;
9. dynamic-import conservative/opaque classification;
10. monkey-patch opacity;
11. delete and rename behavior;
12. identical state-root CIDs;
13. interrupted-write recovery;
14. concurrent root-CAS conflict;
15. CLI parity and import hermeticity.

Focused gates run with auto-install disabled:

```bash
IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS=0 \
IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 \
IPFS_DATASETS_AUTO_INSTALL=0 \
IPFS_KIT_AUTO_INSTALL_DEPS=0 \
python -m pytest -q \
  tests/unit/logic/software_contracts/semantic_index \
  tests/cli/test_semantic_index_cli.py

IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS=0 \
IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 \
IPFS_DATASETS_AUTO_INSTALL=0 \
IPFS_KIT_AUTO_INSTALL_DEPS=0 \
python -m pytest -q tests/unit/logic/software_contracts
```

Then run syntax/CLI smoke checks and the repository's proportionate packaging
check. Full-suite failures outside touched paths are reported separately and
must not be hidden by exclusions or weakened assertions.

The 245-passed/3-skipped regression at the audit baseline proves compatibility
with its tests, not the original semantic contract: several acceptance tests
construct dependency edges by hand and therefore bypass the public scanner.
Release qualification requires public `scan_repository ->
diff_repository_states -> calculate_invalidation` reproductions with no
hand-authored `DependencyEdge` fixtures.

## 14. Known analysis limits

Python name binding, descriptors, dispatch, import hooks, metaclasses,
decorators, monkey patches, plugin systems, native extensions, and reflection
can make runtime behavior unknowable statically. Lexical direct calls and
finite resolver targets are useful but not a complete call graph. Config
semantics are limited to reviewed pytest/package/lock formats. Serialization
relations are exact only for explicit calls or closed declarations; naming
patterns remain heuristic. These limits must appear in symbol/impact
explanations and can only lower confidence.

## 15. Semantic-capsule consumer boundary

The future semantic-capsule module consumes only immutable semantic-index
records; it does not call private scanner visitors:

```python
class SemanticIndexForCapsules(Protocol):
    state_root_cid: str

    def symbol(self, stable_symbol_id: str) -> SymbolRecord: ...
    def outgoing_edges(self, stable_symbol_id: str) -> tuple[DependencyEdge, ...]: ...
    def incoming_edges(self, stable_symbol_id: str) -> tuple[DependencyEdge, ...]: ...
    def source_slice(self, stable_symbol_id: str) -> SourceSliceRef: ...

def capsule_invalidation_inputs(
    previous_state: RepositoryState,
    current_state: RepositoryState,
    delta: RepositoryStateDelta,
) -> InvalidationPlan: ...
```

The capsule key is `(stable_symbol_id, version_cid, semantic_index_schema,
extractor_version)`. Capsule consumers rerun only obligations emitted by the
plan, retrieve raw source whenever confidence is `opaque`, and never infer
completion from a heuristic edge.

At the audit baseline this protocol is documentation-only: `SourceSliceRef`
and the protocol methods are not a concrete exported adapter, and the stored
state does not contain a resolved graph. ISI-039 must either implement this
exact public immutable view or replace the documentation with the exact
implemented API. A phase-two consumer must not call private visitors or infer
this view from unresolved `lexical:*` targets.

## 16. Post-implementation contract audit and repair program

### 16.1 Audit verdict

The implementation at
`dd23a2197e900c2916aab1c4c60077f2bcfdd6e9` is not yet an accepted
`IncrementalSemanticIndex`. The sole CIDv1/canonical DAG-JSON authority is
correctly reused, imports are hermetic under the documented opt-outs, and the
local immutable-object path has useful integrity checks. The remaining gaps
are functional and soundness gaps rather than cosmetic cleanup:

- legal Python literals (`float`, `bytes`, `complex`, and `Ellipsis`), repeated
  decorators, overloads, and full property accessor sets can fail a scan;
- durable symbol records validate CID syntax but cannot recompute their stable
  and version identities, and nested metadata remains mutable;
- clean Git snapshot bytes are discarded and reread from the worktree, while
  commit/tree identity and snapshot membership are absent from state roots;
- the direct AST walk omits or misclassifies required constructs and can report
  native/dynamic behavior as `exact`;
- Python and pytest create different identities for the same test or fixture,
  so real test calls do not produce `tested_by` edges and fixture body changes
  do not change the pytest symbol version;
- the public state contains unresolved lexical targets; resolution performed
  only by explanation code is not committed by the state root;
- persistence roots are keyed by a repository label but do not verify that the
  loaded state belongs to that repository;
- delta/invalidation/explanation rules can over-invalidate, under-invalidate,
  accept a fabricated delta, invent proof obligations, or traverse relation
  directions incorrectly; and
- the CLI can index its own default store, reuse a stale current root for
  impact/explain/watch, leave watch results unpublished, and report a missing
  state root as success.

The later audit at completion marker `a090afad2` retains the valid completed
evidence for ISI-035 and ISI-037 but does not treat their focused green tests
as full acceptance. In `bf827c9bb`, semantic extraction invokes the shared
frontend and then rediscovers inventory through a second AST walk; recursive
child isolation, overload interfaces, aliases/model kinds, typed relation
targets, scope effects, and dynamic/plugin/native confidence remain incomplete.
In `aa1e64aba`, repository binding and process-safe CAS pass independent probes,
but recovery does not remove the legacy `.root-*` transition temporary form.
The bounded follow-up gates below repair those findings without rewriting the
truthful completion records.

The snapshot repair subsequently merged as implementation `10482c1c1`, merge
`0348908d4`, and completion marker `92b7cdbd6`. Its 12 focused tests are useful
but false-green the stable repository boundary: a no-origin repository hashes
current `HEAD`, so committing an unchanged tree changes repository identity
and all stable symbol identities. It also records only a tree OID, not the
selected commit and per-entry blob OIDs, and hashes then rereads clean content
instead of carrying the selected bytes into parsing. ISI-046 is the mandatory
post-034 authority closure for these exact findings. Rejected ISI-046
candidates `febc4e096` and `607d6f09c` supplied useful partial evidence but
were not merged: both weakened an existing race assertion, and audit still
found non-portable committed-repository identity, non-atomic commit/tree
selection, incomplete dirty-snapshot evidence, and raw/artifact namespace
collisions. The replacement implementation `bebe7752a7c8412e02b3691ba17437aa41c45012`
then merged as `97be11c7845d2e4b1c2444c0c187e1a58499ca94`
and completed at marker `44876f4b40d82ed97c7b7ce95ac89853cd1e854c`.
Its 14 focused tests and useful one-read, size-bound, built-in-exclusion,
linked-worktree, unreadable-input, and state-evidence improvements are retained,
but immutable probes still produced clone identity divergence, mode-CID
forgery, a commit-A/tree-B snapshot, empty unborn and staged-deletion
inventories, a restored-mtime race miss, raw/synthetic artifact collision, and
unbound raw-path/source claims. Further probes found missing conflict/deletion
dispositions, ASCII-ignore exclusion of an invalid lookalike, corrupt/quiet
Git failures misclassified as filesystem or unborn, and untyped execution or
decode failures. ISI-047 retained useful repairs, but its completed
implementation `e90a13cd7`, merge `595d4dd93`, and marker `c63c57b9e` were
independently re-audited against a protected 33-item public test module. The
result was exactly 13 failures and 20 passes: unrelated unborn repositories
collide; unborn untracked inputs are mislabeled; same-HEAD status/index
mutations escape the fence; nested configured roots fail mode/bound/scanner
exclusion; corrupt Git markers and quiet born-HEAD failures downgrade; empty or
non-ASCII successful HEAD output is accepted; symbolic-HEAD decode leaks; and
successful HEAD warnings are accepted. ISI-048 implementation
`ee0bc3b542a46b1d5ab52d3a3a9c1209dbbfec28` then merged as
`a9d4096fdb561b7ecdf42af910c13fe84475ac86` and completed at marker
`3a11ef85f03e4a934b97412e3c348d98877c58ad`. Its 33 protected cases plus
22 retained focused cases pass and the broader suite keeps exactly 19 known
downstream failures, but two new protected probes fail: moving an automatically
identified unborn repository changes its identity, and creating its first
commit between the identity and snapshot HEAD decisions returns a mixed unborn
identity/born mode instead of a typed race. ISI-049 is therefore the final
sequential snapshot-generation gate, and the extractor repair may not consume
ISI-048 as authoritative by itself.

### 16.2 Repair matrix

| Task | Priority | Production boundary | Required proof | Depends on |
| --- | --- | --- | --- | --- |
| ISI-033 | P0 | `models.py`, `identity.py` | Initial tagged literals, stable-ID checks, ordered decorators, and aggregate scaffolding; completed evidence is retained but not sufficient for release | ISI-032 |
| ISI-041 | P0 | `models.py`, `identity.py` | V2 mandatory recomputable projection, every persisted/frozen version input, explicit legacy boundary, and injective signed finite/infinite literal components | ISI-033 |
| ISI-042 | P0 | `identity.py`, identity/model tests | Reject source-impossible NaN float and complex components before content hashing while preserving legal infinities and signed zero | ISI-041 |
| ISI-034 | P0 | `snapshot.py`, `scanner.py` | Git-object bytes remain canonical for clean inputs; tree/commit/snapshot identity is state-rooted; races and unreadable inputs are explicit | ISI-042 |
| ISI-035 | P0 | `python_analysis.py` | Adapt the existing frontend authority; cover required declarations/effects/relationships and fail closed on dynamic/native behavior | ISI-042 |
| ISI-037 | P0 | `persistence.py` | Repository-bound verified roots, process-safe CAS, interruption recovery, and the same checks in the optional kit adapter | ISI-042 |
| ISI-046 | P0 | `snapshot.py`, `scanner.py`, snapshot/scanner tests/fixture | Portable committed-Git identity across commits/clones/linked worktrees, atomic commit/tree/blob evidence including dirty forms, one-read captured-byte parsing with metadata-only race rejection, collision-free malformed-name retention, and typed Git failure closure without weakening tests | ISI-034 |
| ISI-047 | P0 | `snapshot.py`, `scanner.py`, snapshot/scanner adversarial tests/fixture | Commit-derived tree, portable clone identity, mode/disposition/exclusion-rooted state, ctime-strength generation fence, collision-free raw/source/artifact keys, and explicit restored-manifest trust boundary | ISI-046 |
| ISI-048 | P0 | `snapshot.py`, `scanner.py`, optional fixture; protected adversarial test is external authority | Make all 33 protected public probes pass: local unborn identity, precise unborn disposition, same-HEAD status/index fencing, nested raw exclusion roots, and typed corrupt/quiet/warning/decode failures while retaining all 20 green contracts | ISI-047 |
| ISI-049 | P0 | `snapshot.py`, `scanner.py` only as needed; protected adversarial test is external authority | Keep automatic unborn identity stable across a pre-commit repository move and reject an unborn-to-born transition between identity and snapshot decisions without regressing the prior 55 focused passes | ISI-048 |
| ISI-043 | P0 | `python_analysis.py`, existing analyzer tests/fixture; protected seven-case authority is validation-only | Make the protected 7-case public gate pass while establishing canonical frontend inventory/disposition, recursive child isolation, overload interface evidence, scoped aliases, and alias-aware model kinds | ISI-035, ISI-049 |
| ISI-044 | P0 | `python_analysis.py`, distinct relation-closure tests/fixture | Exact retained inheritance/composition/schema targets, scope/state effects, bounded calls, and source-bound dynamic/plugin/native confidence | ISI-043 |
| ISI-045 | P0 | `persistence.py`, persistence tests | Idempotent bounded cleanup of legacy and current root/transition temporary prefixes without disturbing authoritative data | ISI-037 |
| ISI-036 | P0 | `pytest_analysis.py`, `scanner.py`, `symbol_graph.py`, `index.py` | One Python/pytest identity and version, a resolved public state, and real test/fixture/config edges | ISI-034, ISI-044 |
| ISI-038 | P0 | `delta.py`, `invalidation.py`, `explain.py` | Recomputed deltas, edge-aware facets and rule direction, bounded real invalidation, retrievable raw-source evidence | ISI-036, ISI-037 |
| ISI-039 | P0 | CLI, acceptance fixtures/tests, public contract documentation | All original cases through public APIs; no hand-made graph; fresh and non-self-indexing CLI; exact capsule consumer surface | ISI-038, ISI-045 |
| ISI-040 | P1 | `watch.py`, `scanner.py` | Verified symbol-level reuse plus cancellable, bounded polling whose notifications never become authority | ISI-039 |

The exact outputs, validation commands, task-sized effects, and acceptance
reproductions are authoritative in
`docs/architecture/incremental_semantic_index.todo.md`. The associated goal and
subgoal hierarchy is in
`docs/architecture/incremental_semantic_index.objectives.md`.

### 16.3 Non-negotiable reproductions

The repair program must keep the strict DAG-JSON authority unchanged and encode
otherwise-illegal AST literal values through a tagged canonical projection
(for example hexadecimal finite/infinite float components and byte hex), not by
teaching the CID authority to accept non-DAG-JSON values. V2 durable records
must persist and freeze every version-CID input, require the normalized
projection on deserialize/recompute, and expose any v1 compatibility only as a
typed migration/rejection boundary. It must prove at least:

1. scanning legal float/bytes/complex/Ellipsis literals, repeated decorators,
   overload declarations, and property getter/setter/deleter sets never fails,
   including overflow literals whose AST values contain positive/negative
   infinity;
2. two signatures whose string defaults differ only by internal whitespace do
   not collapse to the same signature projection;
3. a clean Git repository with a smudge filter is scanned from exactly the
   once-captured indexed Git blob; commit/tree/per-entry blob OIDs enter state
   evidence; the tree derives from the captured commit; mode and explicit
   clean/dirty/unborn/tracked/untracked/deleted dispositions enter snapshot
   identity; a read race, including same-size content with restored mtime,
   becomes opaque through metadata-only validation instead of mixed truth; and
   a no-origin repository keeps its repository/stable symbol identities across
   commits, clones, and linked worktrees while unrelated same-basename Git,
   unborn Git, and filesystem repositories remain distinct; built-in and
   configured excluded state cannot change mode, bytes, bounds, or roots;
   raw-path/source/artifact keys cannot collide with valid synthetic-looking
   names; and a restored manifest cannot authorize parsing until supplied
   bytes verify its claimed source CID;
4. a direct or conditionally nested method/function body edit changes that
   child without changing its parent or unrelated symbols, while an
   overload-only interface edit does change the logical binding version;
5. direct and aliased native/dynamic/plugin behavior cannot remain `exact`;
   aliased model kinds remain detectable; and exact-target assertions prove
   inheritance, composition, schema serialization/validation, nonlocal/global,
   augmented state, self/nested call, catch, and context facts rather than
   merely checking that a relation name exists;
6. the state returned by the public scan contains resolved call targets and a
   production function's signature change reaches its caller and real pytest
   tests without hand-authored edges;
7. fixture body changes, autouse/usefixtures/scoped fixtures, and parametrized
   argument names have correct identity, version, and dependency behavior;
8. loading repository B's valid state CID through repository A's root is
   rejected, two separate writer processes cannot both replace one expected
   root, and recovery removes both legacy/current root/transition temporary
   prefixes without touching a valid root, journal, CAS block, or unrelated
   path;
9. combined body/signature changes retain both facets, edge-only changes
   invalidate their affected subjects, non-schema annotations do not trigger
   schema invalidation, and proofs are rerun only through recorded proof edges;
10. identical-content files cannot contaminate file impact merely by sharing a
    source CID, and every opaque obligation names retrievable raw source;
11. the default CLI store cannot dirty or index the target repository; after a
    stored scan, an edit is visible to `impact`, `explain`, and `watch --once`;
    watch publication and missing-root exit semantics are deterministic; and
12. the final fixture matrix contains no manually constructed dependency edge
    in a public end-to-end acceptance case.
