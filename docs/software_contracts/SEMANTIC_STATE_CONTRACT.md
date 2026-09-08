# Semantic-state producer contract

`ipfs_datasets_py.logic.software_contracts.semantic_state` is the datasets-owned
phase-two semantic-state producer.  It turns a sealed final incremental semantic
index (ISI) view into deterministic, content-addressed capsules, Merkle symbol
nodes, environment bindings, additive invalidation, pure pytest/proof selection,
and pure oracle metrics.

This document freezes the accelerate consumer interface as implemented.  It
documents only proven APIs and known Python unsoundness.  It does not define a
CLI, server, UI, persistence layer, scheduler, model router, worktree manager,
ZK system, multi-language framework, or datasets-owned benchmark.

Interface name for this release surface: `SemanticStateRelease@1`.

## Scope

The package owns:

- closed durable payload records under `models.py` and
  `schemas/semantic-state.payload.schema.json`;
- acyclic symbol-level fact, link, and Merkle compilation;
- deterministic semantic capsules and separate freshness/admission assessments;
- environment-binding projection and additive invalidation obligations;
- pure graph-based test/proof selection; and
- pure selected-versus-full oracle comparison.

It does **not** own:

- a second repository scanner, AST frontend, symbol identity, resolver, call
  graph, repository delta, or source-invalidation engine (final ISI is
  authoritative);
- a second canonical serializer, CID profile, block store, WAL, root CAS, or
  recovery protocol (`software_contracts.content` plus sealed kit/accelerate
  storage);
- context packing, token optimization, task scheduling, pytest/prover
  execution, model routing, worktrees, patch validation, or acceptance
  receipts;
- MCP++ `InterfaceDescriptor`, `ExecutionEnvelope`, `ExecutionReceipt`, or
  `DAGEvent` types, envelope CID hashing, or request/attempt/provider fields;
- an LLM summary that can become authoritative semantic truth.

Python 3.12 and pytest are the phase-two language/test targets.  Controlled
acceptance uses a small fixture repository; this package does not claim whole-
portfolio verification.

## Hermetic import promise

Ordinary imports of the package under the standard opt-outs:

```text
IPFS_DATASETS_AUTO_INSTALL=0
IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS=0
IPFS_DATASETS_PY_MINIMAL_IMPORTS=1
IPFS_KIT_AUTO_INSTALL_DEPS=0
PYTHONDONTWRITEBYTECODE=1
```

install nothing, open no network connection, start no process or thread, write
no filesystem path, and mutate no environment variables.  Import only exposes
the closed facade.  It does not create a store, open a kit provider, or start a
scheduler.  Proven by
`tests/unit/logic/software_contracts/semantic_state/test_import_safety.py`.

## Public operations

The storage-neutral interoperability surface is:

```python
from ipfs_datasets_py.logic.software_contracts.semantic_state import (
    SemanticStateBlockReader,
    SemanticStateBundle,
    SemanticStateView,
    assess_capsule_freshness,
    build_semantic_state,
    compare_test_selection_oracle,
    compile_semantic_capsule,
    extend_semantic_invalidation,
    open_semantic_state,
    read_required_source,
    select_tests_and_proofs,
    verify_semantic_state_bundle,
    view_semantic_state_bundle,
)

bundle = build_semantic_state(
    semantic_index,  # sealed final-ISI RepositoryState or duck-typed view
    environment_bindings=(),  # optional explicit EnvironmentBinding values
    previous_bundle=None,  # verified reuse only; never changes cold identity
)
root = verify_semantic_state_bundle(bundle)
view = view_semantic_state_bundle(bundle)
# or open_semantic_state(root_cid, get_block=reader.get_block)
```

| Operation | Role |
| --- | --- |
| `build_semantic_state` | Cold or verified-incremental assembly of a finite bundle |
| `verify_semantic_state_bundle` | Full reverify of root-reachable blocks and indexes |
| `open_semantic_state` | Verified view over an injected read-only `get_block` |
| `view_semantic_state_bundle` | Same view interface over in-memory bundle blocks |
| `compile_semantic_capsule` | One-symbol capsule compilation |
| `assess_capsule_freshness` | Separate freshness/admission assessment |
| `read_required_source` | Producer-bound raw-source materialization |
| `extend_semantic_invalidation` | ISI plan plus additive environment obligations |
| `select_tests_and_proofs` | Pure selection bound to previous/current roots |
| `compare_test_selection_oracle` | Pure TP/FN/FP and missed-regression metrics |

Interface constants:

```text
SemanticStateProducer@1
SemanticStateView@1
IndexedSemanticStateView@1
SemanticStateBlockReader@1
ipfs-datasets.software-contracts.semantic-state-api@1
```

### Schema versions (closed)

| Record | Schema string |
| --- | --- |
| Semantic state domain | `ipfs-datasets.software-contracts.semantic-state@1` |
| Semantic state root | `ipfs-datasets.software-contracts.semantic-state-root@1` |
| Capsule | `ipfs-datasets.software-contracts.semantic-capsule@1` |
| Capsule freshness | `ipfs-datasets.software-contracts.semantic-capsule-freshness@1` |
| Test selection | `ipfs-datasets.software-contracts.semantic-test-selection@1` |
| Merkle compiler version | `1` |
| Capsule compiler version | `1` |

Unknown fields, unsupported schema versions, forged CIDs, missing blocks, or
incompatible confidence values fail closed with typed results.  There is no
private or simulated fallback that raises confidence or invents edges.

## SemanticStateView, IndexedSemanticStateView, and get_block

`SemanticStateView@1` remains the legacy verified read-only protocol.
`IndexedSemanticStateView@1` extends it additively with typed root-index
selectors:

```python
class SemanticStateBlockReader(Protocol):
    def get_block(self, cid: str) -> bytes: ...

class SemanticStateView(Protocol):
    root: SemanticStateRoot
    def get_block(self, cid: str) -> bytes: ...
    def symbol_node(self, stable_symbol_id: str) -> SymbolMerkleNode: ...
    def capsule(self, stable_symbol_id: str) -> SemanticCapsule: ...

class IndexedSemanticStateView(SemanticStateView, Protocol):
    def symbol_fact(self, stable_symbol_id: str) -> SymbolFactNode: ...
    def artifact_fact(self, artifact_id: str) -> ArtifactFactNode: ...
    def semantic_link(self, edge_id: str) -> SemanticLinkNode: ...
    def analysis_limitation(self, limitation_cid: str) -> AnalysisLimitation: ...
    def semantic_links_for_symbol(
        self, stable_symbol_id: str, direction: str = "both"
    ) -> tuple[SemanticLinkNode, ...]: ...
```

Implemented as `VerifiedSemanticStateView`:

- `root` returns the verified `SemanticStateRoot`.
- `get_block(cid)` fetches bytes through the injected reader (or the finite
  bundle map), then rehashes against the claimed CIDv1.  Missing blocks raise
  `MissingBlockError`; corrupt/schema-mismatched blocks raise
  `CorruptBlockError`.
- Fact, link, and limitation selectors resolve only through the corresponding
  root-bound sorted-pair index, reverify each selected block, and reject any
  logical-key or CID mismatch. Link reads also rebind source and resolved target
  fact/version claims to the root fact indexes. `semantic_links_for_symbol`
  additionally checks incoming/outgoing node fact/version agreement and returns
  self-links only once.
- `symbol_node` / `capsule` resolve through root-bound sorted pair indexes and
  reverify each durable record before return.  Unknown stable IDs raise
  `UnknownSymbolError`.

`get_block` is storage-neutral.  It has no put, publication, CAS, WAL,
provider, network, kit, scheduler, context-pack, receipt, or MCP++ envelope
hasher behavior.  Accelerate may inject a reader backed by the sealed durable
coordination store; datasets never instantiates kit or knows a remote provider.

`SemanticStateBundle` is the only persistence handoff object: a verified root
plus a finite mapping from CID to canonical bytes.  It exposes `get_block`,
`verify`, and `root_cid` only.  It has no storage mutation methods.

## Bundle handoff

Datasets emits a pure `SemanticStateBundle`.  The accelerate adapter:

1. receives the verified root and block map;
2. stores blocks through the sealed kit durable-root interface;
3. re-reads and reverifies blocks through an injected `get_block`;
4. publishes only its own accepted `SemanticStateRootManifest` with
   generation-bearing compare-and-swap after verification receipts pass.

The datasets-domain `SemanticStateRoot` describes one repository semantic state.
It is intentionally distinct from accelerate's accepted
`SemanticStateRootManifest`, which may name deltas, selections, commands,
receipts, provider evidence, and a generation token.

Datasets root identity deliberately excludes previous-root history, repository
deltas, invalidation plans, selections, receipts, acceptance claims,
timestamps, process IDs, local paths, leases, fences, CAS generations, model
outputs, prompts/context packs, and MCP++ request/attempt/provider/envelope
fields.

Cold assembly and verified-incremental assembly over identical semantic inputs
return byte-identical reachable blocks and the same root CID.  `previous_bundle`
is a reuse optimization only: blocks are reused after current inputs reverify to
the same content-addressed CID and stored bytes are byte-identical.  Reuse
diagnostics are not root inputs and never write to disk.

## Consumer references for accelerate

Datasets owns the full durable selection and capsule records.  Accelerate holds
**references** and must not recompile a second semantic selection or capsule.

### TestSelectionRef

Accelerate `SCH-001` holds a `TestSelectionRef`, not a second semantic
`TestSelection`.  The precise reference shape bound by the dependency seal is:

```text
TestSelectionRef(
    selection_cid,
    previous_semantic_state_root_cid_or_null,
    current_semantic_state_root_cid,
)
```

| Ref field | Datasets source |
| --- | --- |
| `selection_cid` | `TestSelection.selection_cid` (CID of the closed identity payload) |
| `previous_semantic_state_root_cid_or_null` | `TestSelection.previous_root_cid` |
| `current_semantic_state_root_cid` | `TestSelection.current_root_cid` |

The full datasets record (`schema`
`ipfs-datasets.software-contracts.semantic-test-selection@1`) additionally
binds selected pytest node IDs, selected proof IDs, sorted shortest reason
paths (with producer edge IDs and semantic-link CIDs), covered and unresolved
obligation IDs, known test universe CID/count, and
`none` / `full_pytest` / `full_proofs` / `both` fallback with reasons.

`select_tests_and_proofs` is pure: it never imports or collects target tests and
never guesses pytest node IDs from names.  Accelerate `SCH-008` only maps the
datasets selection into bounded validation/proof commands and fallback; it must
not run a second graph selector.

### SemanticCapsuleRef

Accelerate holds a `SemanticCapsuleRef` that references and admits a datasets
capsule without recompiling it.  The precise reference shape bound by the
dependency seal is:

```text
SemanticCapsuleRef(
    capsule_cid,
    semantic_state_root_cid,
    stable_symbol_id,
    version_cid,
    source_cid,
    confidence,
    validity_bindings,
    raw_source_required,
)
```

| Ref field | Datasets source |
| --- | --- |
| `capsule_cid` | `SemanticCapsule.capsule_cid` |
| `semantic_state_root_cid` | current `SemanticStateRoot.root_cid` (view/root in scope) |
| `stable_symbol_id` | `SemanticCapsule.stable_symbol_id` |
| `version_cid` | `SemanticCapsule.version_cid` |
| `source_cid` | `SemanticCapsule.source_cid` |
| `confidence` | capsule/producer confidence (`exact` / `conservative` / `heuristic` / `opaque`) |
| `validity_bindings` | `relevant_binding_projection_cid` plus applicable obligation IDs from freshness |
| `raw_source_required` | true when `CapsuleFreshness.admission == raw_source_required` |

Capsule freshness is a separate assessment (`CapsuleFreshness`), not a mutable
capsule field.  Admission is one of:

```text
exact_substitute
conservative_substitute_with_caveats
raw_source_required
```

Only a fresh exact capsule or a fresh conservative capsule with visible caveats
may substitute for unchanged dependency source.  A target being edited, exact
surrounding edit context, directly edited tests, or any heuristic, opaque,
stale, invalid, unknown, or insufficient capsule requires raw source via
`read_required_source` against the sealed ISI public view.  Datasets never
reads the live target filesystem, imports target code, or reaches private
scanner visitors.

The normative producer key inherited from ISI is:

```text
(stable_symbol_id, version_cid, semantic_index_schema, extractor_version)
```

## Identities and determinism

- Stable symbol ID and symbol version CID are final-ISI authorities; this
  package uses them unchanged and never recalculates them.
- Canonical bytes and CIDv1 for every new structured/raw block go through
  `software_contracts.content`.
- Index blocks are sorted `[logical_key, cid]` pair lists; duplicate keys are
  invalid.
- Capsules reference dependency stable IDs, versions, fact CIDs, and link IDs —
  never dependency capsule or symbol-node CIDs — so recursive calls, mutual
  imports, and inheritance cannot form content-identity cycles.
- Formatting-only mutations may change source provenance while retaining
  stable/version identity as defined by the final ISI contract.  A semantic
  version change necessarily changes fact, capsule, symbol-node, indexes, and
  root.

## Selection and oracle

Selection needs both previous and current states so deletion evidence is not
lost.  Seeds and relation-specific traversal cover direct tests, reverse
callers/imports, fixture/usefixtures/autouse links, schemas and
serializers/validators, config/lock/policy/interface bindings, generated
inputs, proof edges, deletion/rename evidence, and explicit user rules.  Rename
candidates remain heuristic; they do not preserve identity.

Oracle comparison is pure.  Accelerate supplies normalized baseline,
selected-run, and candidate-full result facts; datasets does not execute
pytest.  Membership and TP/FN/FP are compared only in the pytest node-ID
domain.  Failure fingerprints identify whether the outcome at a selected node
is the same failure, never whether the node was selected.

Metrics include new/missed regressions, fixture TP/FN/FP, recall and precision
only when denominators are nonzero, selection ratio, execution reduction,
fallback rate, and changed-outcome set.  An empty authored oracle is
`not_applicable`, never fabricated as 100 percent.  Controlled acceptance
requires zero fixture false negatives and zero missed regressions; full-suite
fallback is measured, not described as precise.

## MCP++ and wire boundary

Datasets payloads are namespaced application schemas.  They do not define or
copy MCP++ generic wire types and never calculate an envelope CID.  MCP++
Profile A advertises operations/schema CIDs; Profile B carries the datasets
payload or its CID; Profile F links events.  The datasets payload CID and the
outer envelope/event CID are deliberately distinct.

`BindingKind.INTERFACE_DESCRIPTOR` is datasets application data describing an
environment binding.  It is not MCP++ `InterfaceDescriptor` wire authority.

## Known limits (no overclaim)

This contract cannot make dynamic Python exact.  The following remain
conservative, heuristic, or opaque according to producer evidence:

- dynamic dispatch, decorators, descriptors, reflection, import hooks,
  metaclasses, and monkey patches;
- plugin systems and uncontrolled dynamic pytest collection;
- native extensions and opaque native reachability;
- runtime generation and uncontrolled I/O;
- incomplete call graphs (the symbol graph is not a full runtime call graph).

Heuristic edges may inform retrieval or review priority; they never establish
capsule or proof completion.  Unknown reachability must remain visible and may
force raw source or full-suite fallback (`full_pytest`, `full_proofs`, or
`both` with recorded reasons).

Test-selection precision is measurable only against an authored controlled
oracle.  In real repositories, new full-suite regressions measure missed
failures but cannot prove that every passing test was semantically unaffected.
An empty denominator is reported as not applicable.

Docstrings are non-authoritative hints.  Optional LLM summaries are excluded
from capsule/root truth and cannot raise confidence, establish code behavior,
satisfy verification, or discharge an obligation.

## Controlled acceptance

The fixture repository under
`tests/fixtures/software_contracts/semantic_state/` covers local body and
public signature changes, cross-module calls, schema/exception recovery,
fixture/config/plugin/lock/policy/interface/generated inputs, dynamic import,
monkey patch, opaque native dependency, formatting-only, deletion, and rename
cases.  Public end-to-end tests call only the final scanner/view, semantic-state
API, and pure selection/oracle API.  They do not manufacture `DependencyEdge`
values or mutate returned producer state to invent impact.

Focused validation (Python 3.12):

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

## What accelerate owns after handoff

The 40-task benchmark, ContextPack token accounting, isolated patch loop,
provider gates, verification receipts, and final accepted-root publication are
completed and reported by the accelerate harness, not by this package.
Datasets supplies schema/interface fingerprints, the public functions above,
deterministic root/capsule/selection vectors, controlled oracle results,
import-safety evidence, and known opaque cases.
