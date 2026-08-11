# Python semantic-state producer contract plan

Status: prepared, deliberately unsealed, and not authorized for implementation.

This plan defines the datasets-owned phase-two semantic-state producer consumed
by the Python-first semantic-compression coding-agent harness.  The supervisor
task prefix is `DSS-`, the objective prefix is `DSS-G`, and the board namespace
is `datasets-semantic-state-v1`.

The dependency gate is intentionally open:

```text
FINAL_INCREMENTAL_SEMANTIC_INDEX_COMMIT = UNRESOLVED_FINAL_ISI_COMMIT
FINAL_KIT_STATE_ROOT_COMMIT             = UNRESOLVED_FINAL_KSR_COMMIT
```

`DSS-000` remains `todo` with `Completion: manual`.  No implementation task may
start until an operator replaces both placeholders with the exact final commits,
fills every required fingerprint, runs the producer tests through the seal
validator, commits the sealed control plane, and manually completes `DSS-000`.
The prepared seal and its test are expected to fail closed until that happens.

## 1. Scope and non-goals

The implementation is narrowly owned by a new sibling package:

```text
ipfs_datasets_py/logic/software_contracts/semantic_state/
```

It will own only:

- closed deterministic semantic-state payload records;
- a symbol-level, acyclic content-addressed graph derived from the final
  incremental semantic index;
- deterministic semantic capsules and their freshness/admission decisions;
- explicit environment-binding deltas and additive invalidation obligations;
- pure graph-based pytest/proof selection; and
- pure selected-versus-full oracle metrics.

It will not own or implement:

- a second repository scanner, AST frontend, symbol identity, resolver, call
  graph, repository delta, or source invalidation engine;
- a second canonical serializer, CID profile, block store, WAL, root CAS, or
  recovery protocol;
- context packing, token optimization, task scheduling, test/prover execution,
  model routing/invocation, worktrees, patch validation, or receipts;
- an MCP server, generic MCP++ envelope/event/receipt schema, network service,
  user interface, dashboard, ZK system, theorem prover, or arbitrary
  multi-language framework; or
- an LLM summary that can become authoritative semantic truth.

Python 3.12 and pytest are the only phase-two language/test targets.  The
controlled target is a small runnable fixture repository; this package does not
attempt to verify the whole portfolio.

## 2. Reviewed revisions and existing authorities

The preparation branch is based exactly on datasets commit
`5d517253577da9b0e77d80e88a2cdcf5a76db0da` (tree
`e18ee0bb6c777323c235e3cd17ea430b2a124557`).  The ISI-033 through ISI-040
repair contract was reviewed in:

- `docs/architecture/INCREMENTAL_SEMANTIC_INDEX_PLAN.md`
- `docs/architecture/incremental_semantic_index.objectives.md`
- `docs/architecture/incremental_semantic_index.todo.md`
- `docs/software_contracts/INCREMENTAL_SEMANTIC_INDEX.md`

Relevant datasets modules inspected before this plan were:

- `logic/software_contracts/content.py` -- sole strict DAG-JSON and real CIDv1
  authority;
- `repository.py`, `python_frontend.py`, `resolver.py`, and `cache.py` -- Git
  inventory, Python IR, resolution, and immutable local CAS authorities;
- `semantic_index/models.py` and `identity.py` -- durable stable/version
  identities and typed records;
- `snapshot.py`, `scanner.py`, `python_analysis.py`, and `pytest_analysis.py` --
  canonical source and extraction path;
- `symbol_graph.py` and `index.py` -- resolved public graph/view;
- `delta.py`, `invalidation.py`, and `explain.py` -- source mutation truth;
- `persistence.py` -- phase-one state persistence; and
- `watch.py` -- notification-only incremental scan trigger.

The final repaired ISI commit is not yet known.  Its exact public schemas,
extractor versions, capsule-consumer view, source-blob/span readers, and producer
tests are therefore launch-time sealed inputs rather than guessed contracts.

The following external revisions were also reviewed as contract inputs:

- MCP++ Profile A/B/F wire authority:
  `dc3164653a48d059ae9812078359daeafb451c07`;
- hardened accelerate harness board:
  `ba260d06572aff62f6ceee444f1b0d5aeb100e87`; and
- kit durable-root repair work at the preparation-time review point
  `7b4785abba1b727fd8bdce1444122672520e4fc0`.

The last kit revision is not a release pin.  KSR closeout remains unresolved and
must expose the final closed `DurableCoordinationStore` block interface plus
generation-bearing, verified expected-token root CAS before `DSS-000` closes.

## 3. One owner per authority

| Concern | Sole authority | Datasets semantic-state role |
|---|---|---|
| Git/filesystem snapshot and tracked bytes | final repaired `semantic_index` | consume verified public records and references |
| Python/pytest extraction and confidence | final repaired `semantic_index` | preserve facts and confidence, never raise them |
| stable symbol ID and symbol version CID | final repaired `semantic_index` | use unchanged, never translate or recalculate |
| typed dependency edges and source invalidation | final repaired `semantic_index` | wrap edge evidence and preserve all obligations |
| canonical bytes and CIDv1 | `software_contracts.content` | call it for every new structured/raw verification |
| semantic payload/Merkle/capsule/selection | this package | define and compile deterministic domain records |
| blocks, WAL, root CAS, recovery | final KSR contract through accelerate | emit a pure bundle/read-only view only |
| accepted transition root and verification receipts | accelerate harness | expose CIDs consumed by its manifest |
| context packs | accelerate `ContextCompiler` and `ProductionContextSlice` | provide capsules/source/freshness only |
| pytest/prover/model execution and scheduling | accelerate adapters | provide selection/obligations only |
| generic wire envelopes/events/receipts | MCP++ Profile A/B/F | provide application payloads or payload CIDs only |

The datasets-domain `SemanticStateRoot` is intentionally distinct from
accelerate's accepted `SemanticStateRootManifest`.  The former describes one
repository semantic state.  The latter describes an accepted transition and may
name deltas, selections, commands, receipts, provider evidence, and a generation
token.

## 4. Package and output layout

Planned implementation files are disjoint by task:

```text
ipfs_datasets_py/logic/software_contracts/semantic_state/
  __init__.py                  DSS-009
  api.py                       DSS-009
  models.py                    DSS-001
  merkle.py                    DSS-003
  capsules.py                  DSS-004
  bindings.py                  DSS-005
  invalidation.py              DSS-005
  freshness.py                 DSS-006
  source.py                    DSS-006
  test_selection.py            DSS-007
  oracle.py                    DSS-008
  schemas/
    semantic-state.payload.schema.json  DSS-001
```

Tests live under
`tests/unit/logic/software_contracts/semantic_state/`.  Controlled source data
lives under `tests/fixtures/software_contracts/semantic_state/`.  No worker may
edit the three control documents or the dependency seal; those are owned only by
the operator through `DSS-000`.

## 5. Closed payload and authoritative state root

Every durable record is recursively immutable, closed to unknown fields, sorted
and duplicate-free where it contains a collection, round-trip verified, and
restricted to the strict DAG-JSON types accepted by
`software_contracts.content`.  Raw bytes are content-addressed with the existing
raw CID function and are never inserted directly into structured DAG-JSON.

The exact `SemanticStateRoot` identity payload is equivalent to:

```json
{
  "schema": "ipfs-datasets.software-contracts.semantic-state-root@1",
  "repository_id": "<final-ISI repository identity>",
  "producer": {
    "repository_state_cid": "<final-ISI state CID>",
    "repository_snapshot_cid": "<final-ISI snapshot CID>",
    "git_commit_oid": "<OID or null>",
    "git_tree_oid": "<OID or null>",
    "source_manifest_cid": "<final-ISI manifest CID>",
    "semantic_index_schema": "<sealed schema>",
    "extractor_name": "<sealed extractor>",
    "extractor_version": "<sealed version>"
  },
  "semantic_state_schema": "ipfs-datasets.software-contracts.semantic-state@1",
  "merkle_compiler_version": "1",
  "capsule_schema": "ipfs-datasets.software-contracts.semantic-capsule@1",
  "capsule_compiler_version": "1",
  "symbol_fact_index_cid": "<CID>",
  "artifact_fact_index_cid": "<CID>",
  "semantic_link_index_cid": "<CID>",
  "symbol_node_index_cid": "<CID>",
  "capsule_index_cid": "<CID>",
  "environment_binding_set_cid": "<CID>",
  "analysis_limitation_index_cid": "<CID>"
}
```

All producer values are copied from and verified against the final public ISI
view.  They are never inferred from an ambient worktree.  Index blocks are
sorted lists of `[logical_key, cid]` pairs; duplicate keys are invalid.

The root deliberately excludes:

- a previous root, transition history, repository delta, or invalidation plan;
- task text, prompts, ContextPacks, selections, model/provider outputs;
- tests/proofs/commands/results/receipts or acceptance claims;
- timestamps, process IDs, wall-clock measurements, local checkout/store paths;
  and
- WAL positions, leases, fences, or CAS generations.

Those operational and transition values belong to the accelerate acceptance
manifest.  Excluding them makes the datasets root a deterministic function of
one semantic state.

`SemanticStateBundle` contains the verified root and a finite mapping from CID
to canonical bytes.  It has no storage mutation methods.  A block may be reused
from `previous_bundle` only after rehashing and verifying all of its current
inputs.  Reuse diagnostics are not root inputs.  A cold build and an incremental
build over identical semantic inputs must return byte-identical blocks and root.

## 6. Acyclic symbol-level Merkle model

The domain graph uses four record types:

1. `SymbolFactNode` binds the exact final-ISI `SymbolRecord`, its stable ID,
   version CID, repository, source reference, span, and confidence.
2. `ArtifactFactNode` binds the exact final-ISI artifact record and source
   identity.
3. `SemanticLinkNode` wraps, but never replaces, the authoritative
   `DependencyEdge.edge_id`.  It records source stable/version/fact CID; target
   kind (`symbol`, `artifact`, or `unresolved`); resolved target identity/fact
   CID where available; relation; source span; extraction method; confidence;
   extractor version; and the original edge ID.
4. `SymbolMerkleNode` binds stable/version identity, symbol-fact CID,
   capsule CID, sorted incoming/outgoing semantic-link CIDs, confidence, and
   raw-source-required reasons.

Links reference fact CIDs, not `SymbolMerkleNode` CIDs.  Symbol nodes reference
link CIDs.  Capsules reference dependency stable IDs, versions, fact CIDs, and
link IDs, never dependency capsule or symbol-node CIDs.  Recursive calls,
mutual imports, and inheritance cycles therefore cannot create content-identity
cycles.

No line number participates in stable identity.  A formatting-only mutation
may alter source provenance while retaining a stable/version symbol identity as
defined by the final ISI contract.  A semantic version change necessarily
changes its fact, capsule, symbol-node, indexes, and root.

## 7. Deterministic capsules and raw-source admission

The normative producer key inherited from ISI is exactly:

```text
(stable_symbol_id, version_cid, semantic_index_schema, extractor_version)
```

The capsule artifact additionally binds:

- capsule schema and compiler version;
- the exact source-slice reference and source CID;
- authoritative signature, annotations, defaults, ordered decorators,
  contracts, effects, exception behavior, schema/serialization relations,
  tests, fixtures, and proof-obligation references exposed by ISI;
- dependency fact/link references and confidence evidence; and
- a per-symbol `relevant_binding_projection_cid`.

The root binds the complete environment-binding set, but a capsule binds only
the deterministic projection relevant to that symbol plus genuinely global
compiler/toolchain contracts.  A known disjoint policy, interface, or lock
change therefore changes the state root without changing unrelated capsule
CIDs.  Unknown or global scope deliberately projects to all possibly affected
capsules.

All capsules are compiled in stable-symbol order for the controlled state, so
the root never depends on retrieval history.  `previous_bundle` may accelerate
unchanged capsule materialization only after the producer key, compiler/schema,
relevant binding projection, dependency links, and stored CID all verify.

Docstrings are stored only as non-authoritative hints.  An optional LLM summary
is a separate heuristic annotation excluded from capsule/root truth.  It cannot
raise confidence, establish code behavior, satisfy verification, or discharge
an obligation.

`CapsuleFreshness` is a separate assessment rather than a mutable capsule field.
It binds the capsule CID, current state/view, compiler/schema, producer
identity, relevant binding projection, and applicable invalidation obligations:

```text
freshness = fresh | stale | unknown
admission = exact_substitute
          | conservative_substitute_with_caveats
          | raw_source_required
```

Only a fresh exact capsule or a fresh conservative capsule with visible caveats
may substitute for unchanged dependency source.  A target being edited, exact
surrounding edit context, directly edited tests, or any heuristic, opaque,
stale, invalid, unknown, or insufficient capsule requires raw source.

The raw-source boundary is the final ISI-039 public capsule view.  `DSS-000`
must seal its exact implemented signatures, expected to provide the equivalent
of `state_root_cid`, `symbol`, `incoming_edges`, `outgoing_edges`,
`source_slice`, `read_source_blob`, and `read_source_span`.  The semantic-state
adapter may call only that public snapshot/tree-bound API and must reverify
returned bytes against the producer raw CID with `software_contracts.content`.
It must never call `Path.read_*`, inspect the current target filesystem, import
target code, or reach into a private visitor/store.  Missing, corrupt, or
TOCTOU-mismatched bytes produce a typed source-unavailable/binding-mismatch
result and require a rescan.

## 8. Environment bindings and additive invalidation

Repository-local lock, test configuration, generated-file, and schema inputs
come only from final-ISI artifact records and typed edges.  External policies,
toolchains, and interface descriptors are injected as validated content
references.  This package never performs a second filesystem discovery pass.

Each `EnvironmentBinding` has a stable binding identity, kind, version CID,
scope, extraction authority, and confidence.  Required kinds include:

- dependency manifest or lockfile;
- pytest configuration/plugin and proof configuration;
- policy/security rules;
- interface descriptor;
- generated input;
- Python/toolchain; and
- semantic schema/compiler.

`SemanticBindingDelta` compares stable binding identities and old/new version
CIDs.  The semantic invalidation layer first recomputes or verifies the supplied
ISI delta/plan through the final public API, preserves every ISI obligation and
supporting edge, and then appends only environment obligations:

| Binding change | Additional bounded obligation |
|---|---|
| dependency or lock | dependent capsules/summaries and bound verification receipts stale; unknown mapping is conservative/global |
| pytest/proof config or uncontrolled plugin | connected receipts stale; unknown scope requests full fallback |
| policy | policy/security decisions and bound receipts stale |
| interface descriptor | descriptors, client adapters, API-schema obligations/tests stale |
| generated input | generated artifacts/capsules and connected tests/proofs stale |
| toolchain/schema/compiler | all derived artifacts bound to that version stale |
| opaque/insufficient behavior | raw source required |

The engine follows relation-specific directions and shortest evidence paths; it
does not flood every relation both ways.  It never invents a test, proof,
adapter, or receipt ID absent an authoritative edge or explicit binding, and it
emits obligations rather than rewriting dependent source.

## 9. Pure test/proof selection and oracle metrics

Test/proof selection is datasets semantic authority.  Accelerate consumes the
returned `TestSelection` and only projects it into bounded validation/proof
commands.  It must not run a second graph selector such as
`run_impact_selected`.

Selection needs both states so deletion evidence is not lost:

```text
select_tests_and_proofs(
    previous_state: SemanticStateView | None,
    current_state: SemanticStateView,
    invalidation: SemanticInvalidationPlan,
    *,
    policy: SelectionPolicy,
    explicit_rules: Sequence[SelectionRule] = (),
) -> TestSelection
```

The result binds both root CIDs and contains selected pytest node IDs, selected
proof IDs, sorted shortest reason paths with producer edge IDs and semantic-link
CIDs, covered seed obligations, unresolved obligations, the known test universe
CID/count, and `none`, `full_pytest`, `full_proofs`, or `both` fallback with
reasons.

Seeds and relation-specific traversal cover direct tests, reverse callers and
imports, fixture/usefixtures/autouse dependencies, schemas and
serializers/validators, config/lock/policy/interface bindings, generated inputs,
proof edges, deletion/rename evidence, and explicit user rules.  Rename
candidates remain heuristic; they do not preserve identity.  The selector never
imports or collects target tests and never guesses pytest node IDs from names.
Dynamic pytest/plugins, native/opaque reachability, an unknown universe, or
insufficient graph evidence intersecting the cone forces visible full fallback.

Oracle comparison is also pure.  Accelerate supplies normalized baseline,
selected-run, and candidate-full result facts; datasets does not execute pytest.
The controlled fixtures additionally declare an authored affected-test oracle.

The metrics are:

- `new_regressions`: candidate full-suite fail/error/timeout fingerprints not
  identically present in the baseline;
- `missed_regressions`: new regressions absent from selection;
- fixture `TP = selected intersection authored_oracle`;
- fixture `FN = authored_oracle minus selected`;
- fixture `FP = selected minus authored_oracle`;
- fixture recall and precision only when their denominator is nonzero;
- selected/full counts, selection ratio, execution reduction, fallback rate,
  changed-outcome set, and regression recall.

An empty oracle is `not_applicable`, never fabricated as 100 percent.  Known
baseline failures are not attributed to a patch.  Skip, xfail, error, and
timeout are explicit normalized outcomes.  Controlled acceptance requires zero
fixture false negatives and zero missed regressions; full-suite fallback must
work and is measured rather than described as precise.

The harness's 40-task benchmark remains accelerate-owned.  Datasets supplies a
controlled repository and authored selection cases that the benchmark may
consume, but it does not define a second benchmark, run models, or claim
accepted/rejected repairs.

## 10. Exactly closed public API

The planned public surface is storage-neutral and equivalent to:

```python
class SemanticStateBlockReader(Protocol):
    def get_block(self, cid: str) -> bytes: ...

class SemanticStateView(Protocol):
    root: SemanticStateRoot
    def get_block(self, cid: str) -> bytes: ...
    def symbol_node(self, stable_symbol_id: str) -> SymbolMerkleNode: ...
    def capsule(self, stable_symbol_id: str) -> SemanticCapsule: ...

def build_semantic_state(
    semantic_index: SemanticIndexForCapsules,
    *,
    environment_bindings: Sequence[EnvironmentBinding] = (),
    previous_bundle: SemanticStateBundle | None = None,
) -> SemanticStateBundle: ...

def verify_semantic_state_bundle(
    bundle: SemanticStateBundle,
) -> SemanticStateRoot: ...

def open_semantic_state(
    root_cid: str,
    get_block: Callable[[str], bytes],
) -> SemanticStateView: ...

def compile_semantic_capsule(
    semantic_index: SemanticIndexForCapsules,
    stable_symbol_id: str,
    *,
    relevant_bindings: EnvironmentBindingSet,
) -> SemanticCapsule: ...

def assess_capsule_freshness(
    capsule: SemanticCapsule,
    *,
    current_state: SemanticStateView,
    invalidation: SemanticInvalidationPlan | None = None,
) -> CapsuleFreshness: ...

def read_required_source(
    semantic_index: SemanticIndexForCapsules,
    stable_symbol_id: str,
    *,
    expected_producer_state_cid: str,
) -> VerifiedSourceMaterialization: ...

def extend_semantic_invalidation(
    previous_index: SemanticIndexForCapsules,
    current_index: SemanticIndexForCapsules,
    delta: RepositoryStateDelta,
    plan: InvalidationPlan,
    previous_state: SemanticStateView,
    current_state: SemanticStateView,
) -> SemanticInvalidationPlan: ...

def select_tests_and_proofs(
    previous_state: SemanticStateView | None,
    current_state: SemanticStateView,
    invalidation: SemanticInvalidationPlan,
    *,
    policy: SelectionPolicy,
    explicit_rules: Sequence[SelectionRule] = (),
) -> TestSelection: ...

def compare_test_selection_oracle(
    selection: TestSelection,
    *,
    baseline_full: TestRunFacts,
    selected_run: TestRunFacts,
    candidate_full: TestRunFacts,
    authored_oracle: Sequence[str] | None = None,
) -> TestOracleComparison: ...
```

`SemanticStateView` exposes only verified reads.  Its injected `get_block`
function has no put, publication, CAS, WAL, provider, or network behavior.
`SemanticStateBundle.view()` may provide the same interface over in-memory
blocks.  Accelerate may supply a read function backed by the sealed KSR adapter.

`VerifiedSourceMaterialization` is intentionally not one structured
content-identity object because it contains bytes.  Its evidence record is
serializable; the byte payload retains the already-authoritative raw CID.

Unknown fields, unsupported schema versions, unavailable public producer
capabilities, forged CIDs, missing blocks, or incompatible confidence values
fail closed with typed results.  No private or simulated fallback exists.

## 11. Persistence and MCP++ boundary

The bundle is the only persistence handoff.  Datasets neither instantiates kit
nor knows a remote provider.  Accelerate's narrow adapter gives bundle blocks to
the final KSR store, verifies them on read, and publishes only its accepted
`SemanticStateRootManifest` with generation-bearing compare-and-swap after
verification receipts pass.

Datasets payloads are namespaced application schemas.  They do not define or
copy MCP++ `InterfaceDescriptor`, `ExecutionEnvelope`, `ExecutionReceipt`, or
`DAGEvent`, and they never calculate an envelope CID.  MCP++ Profile A advertises
operations/schema CIDs; Profile B carries the datasets payload or its CID;
Profile F links events.  The datasets payload CID and outer envelope/event CID
are deliberately distinct.

Request IDs, attempts, provider attribution, availability/simulation status,
timestamps, signatures, receipt claims, and CAS generations are forbidden from
the datasets root.  The dependency seal verifies the pinned MCP++ authority; no
miniature envelope hasher or copied conformance implementation is permitted in
this repository.

Production simulation policy is enforced by accelerate.  Datasets records must
not include a flag that lets simulated output masquerade as semantic or
verification truth.  A development simulation can never create an accepted
root or verification receipt.

## 12. Supervisor DAG and conflict control

```text
D0  DSS-000
D1  DSS-001 | DSS-002
D2  DSS-003 | DSS-004 | DSS-005
D3  DSS-006 | DSS-007
D4  DSS-008
D5  DSS-009
D6  DSS-010
D7  DSS-011
```

Dependencies are:

```text
DSS-000: -
DSS-001: DSS-000
DSS-002: DSS-000
DSS-003: DSS-001
DSS-004: DSS-001
DSS-005: DSS-001
DSS-006: DSS-004, DSS-005
DSS-007: DSS-003, DSS-005
DSS-008: DSS-002, DSS-007
DSS-009: DSS-003, DSS-004, DSS-005, DSS-006, DSS-007, DSS-008
DSS-010: DSS-002, DSS-009
DSS-011: DSS-010
```

Every task owns a disjoint file set.  `DSS-009` alone owns the package exports
and the narrow package-data edits.  `DSS-010` and `DSS-011` own only new
acceptance/closeout tests and documentation.  Workers may read but not edit
semantic-index authorities or protected DSS control files.

## 13. Controlled acceptance matrix

The fixture repository contains a baseline and ordinary files/patches for:

- local function body and public signature changes;
- cross-module call changes;
- dataclass/schema and exception/recovery changes;
- fixture, pytest configuration/plugin, lock, policy, and interface changes;
- generated input/file changes;
- dynamic import, monkey patch, and opaque native dependency;
- unrelated formatting, deletion, and rename.

Tests create a temporary Git repository; no `.git` directory is checked into
the fixture.  Public end-to-end tests may call only the final scanner/view,
semantic-state API, and pure selection/oracle API.  They may not construct a
`DependencyEdge` or mutate a returned producer state to manufacture impact.

All implementation validation uses Python 3.12 with:

```text
IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS=0
IPFS_DATASETS_PY_MINIMAL_IMPORTS=1
IPFS_DATASETS_AUTO_INSTALL=0
IPFS_KIT_AUTO_INSTALL_DEPS=0
```

The final focused gate is:

```bash
python3.12 -m pytest -q \
  tests/unit/logic/software_contracts/semantic_state \
  tests/unit/logic/software_contracts/semantic_index \
  tests/unit/logic/software_contracts/test_content_identity.py \
  tests/unit/logic/software_contracts/test_python_frontend.py \
  tests/unit/logic/software_contracts/test_repository_manifest.py \
  tests/unit/logic/software_contracts/test_resolver.py \
  tests/cli/test_semantic_index_cli.py
```

Acceptance requires deterministic cold/incremental roots, bounded unrelated
changes, raw-source fallback for unsafe capsules, policy/interface/lock
freshness, all known test/proof dependents selected, zero controlled false
negatives, and ordinary imports with no install/network/process/thread/write or
environment mutation.

## 14. Known limits

This contract cannot make dynamic Python exact.  Dispatch, decorators,
descriptors, reflection, import hooks, metaclasses, monkey patches, plugin
systems, native extensions, runtime generation, uncontrolled I/O, and dynamic
pytest behavior remain conservative, heuristic, or opaque according to producer
evidence.  The symbol graph is not a complete call graph.  Heuristic edges are
useful for retrieval/ranking only.  Unknown reachability must remain visible and
may force raw source or full-suite fallback.

Test-selection precision is measurable only against an authored controlled
oracle.  In real repositories, new full-suite regressions measure missed
failures but cannot prove that every passing test was semantically unaffected.
An empty denominator is reported as not applicable.

## 15. Release handoff

Datasets closeout supplies accelerate with exact schema/interface fingerprints,
the public functions in section 10, deterministic root/capsule/selection golden
vectors, controlled oracle results, import-safety evidence, and known opaque
cases.  Accelerate's `SCH-001` must hold a `TestSelectionRef`, not a second
semantic `TestSelection`; `SCH-008` only maps the datasets selection to execution
commands and fallback.  `SemanticCapsuleRef` likewise references and admits the
datasets capsule without recompiling it.

The 40-task benchmark, ContextPack token accounting, isolated patch loop,
provider gates, verification receipts, and final accepted-root publication are
completed and reported by the accelerate harness, not by this package.
