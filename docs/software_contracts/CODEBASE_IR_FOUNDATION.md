# Structural codebase IR foundation

The first repository proof-index slice captures the repository's exact admitted
source bytes, projects them into the existing semantic and AST indexes, and
returns an immutable `codebase-ir-structural-manifest@1`. Preparation uses the
shared resource scheduler by default. This profile supplies structural evidence;
it does not train a model, formalize behavior, check a theorem, or discharge an
IntentIR requirement.

The implementation is in
[codebase_ir.py](../../ipfs_datasets_py/logic/software_contracts/codebase_ir.py),
with admission in
[codebase_resources.py](../../ipfs_datasets_py/logic/software_contracts/codebase_resources.py).
It advances the source/storage foundation of the
[repository proof-index plan](../../../ipfs_accelerate/docs/architecture/REPOSITORY_PROOF_INDEX_AND_CODEBASE_IR_PLAN.md).

## Prepare and retrieve a snapshot

Keep the cache outside the repository under examination. Use one owner process
and a dedicated DuckDB connection; store operations own their transactions.
DuckDB remains an optional dependency until the caller opens a connection.

```python
from pathlib import Path
import duckdb

from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor

cache = Path("codebase-cache")
cache.mkdir(exist_ok=True)
with duckdb.connect(str(cache / "ast.duckdb"), config={
    "threads": 1, "memory_limit": "64MB", "max_temp_directory_size": "128MB",
}) as connection:
    index = RepositoryCodebaseIndex(
        ingestor=DuckDBASTIngestor(store=DuckDBASTStore(connection=connection)),
        artifacts=ImmutableCAS(cache / "artifacts"),
    )
    manifest = index.prepare("repository-under-test")
    print(manifest.cid, manifest.coverage)

    restored = index.load(manifest.cid)
    active_ast = index.lookup(restored, "counter.py")
    historical_ast = index.load_ast_artifact(restored, "counter.py")
```

The example path `counter.py` must exist in the captured inventory. `lookup`
returns `None` for a captured opaque/unindexed entry and raises when an expected
AST is missing, invalidated or bound to another source. `load_ast_artifact` reads
immutable history without asserting that the SQL projection remains active.
`load` and both lookup methods perform no live scan, inference or training.
The database settings above match the bounded eight-file benchmark; larger
workloads need a separately measured profile within the shared reservation.

## Publish and observe a current structural head

For owner-managed use, inject a
[`CodebaseCatalog`](../../ipfs_datasets_py/duckdb_control/codebase_catalog.py)
sharing the exact AST store and CAS. Its dedicated `codebase_control` SQL domain
owns structural heads; it does not replace a semantic-index root, model registry
or supervisor state owner. Keep the database connection dedicated to this owner.
The following replaces the index construction inside the connection block above.

```python
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog

store = DuckDBASTStore(connection=connection)
artifacts = ImmutableCAS(cache / "artifacts")
catalog = CodebaseCatalog(store, artifacts)
index = RepositoryCodebaseIndex(
    ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts, catalog=catalog,
)
view_id = "project:main-worktree"
expected = index.current(view_id)
receipt = index.prepare_current(
    "repository-under-test", repository_id=view_id,
    operation_id="index-command-0001", expected_head=expected,
)
observation = index.observe_current(
    "repository-under-test", expected_head=receipt.head,
)
```

The view ID is explicit: assign different IDs to independent worktrees. A head
binds a monotonic generation, manifest, snapshot, AST revision and operation
receipt. Publication seals immutable artifacts, reobserves the source, then
atomically commits the head, operation receipt, AST batch and prior-revision
invalidation. The durable prior head determines invalidation after restart.
An index with a catalog requires `prepare_current`; its ordinary `prepare` route
is rejected so it cannot silently skip head publication.

For a lost response, retry with the same operation ID and original expected head.
Changed operation payloads and stale expected generations fail. An exact retry
returns its original receipt, even after a successor exists, without restoring
old AST rows. Receipt availability therefore does not imply current eligibility.
The catalog's operation lookup can recover historical receipts independently of
the live checkout. Returning to earlier source can reuse the same manifest while
advancing the head generation, preventing an old generation from passing as new.
The default catalog bounds are 128 view heads and 4,096 operations; reaching a
bound rejects new publication while preserving existing replay history. Native
concurrent connections can return a transaction conflict; resolve the exact
operation before retrying. Forked owner connections and drifted catalog schemas
are rejected.

`current` reads catalog metadata only. `observe_current` verifies manifest/source/
AST artifacts and active projections, captures the live admitted source using
the manifest's exact bounds and exclusions, and checks the head again. It performs
no semantic extraction, inference or training. Resource admission, pressure
backoff and cancellation apply to observation as well as preparation.

This is a point-in-time observation, not a checkout lock. Consumers must reobserve
at completion and admission. Opaque entries remain unknown, and exclusions stay
outside the scope. The optional accelerate
[structural planning context](../../../ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/planning/structural_codebase_context.py)
checks on entry and successful exit, freezes a body-free structural observation
in existing planning materials, and supplies no behavioral facts. It does not
activate the supervisor service or authorize worker dispatch.

## Check an explicit conditional Int/Bool contract

[codebase_verification.py](../../ipfs_datasets_py/logic/software_contracts/codebase_verification.py)
adds an immutable `codebase-conditional-verification@1` sidecar to an existing
current head. It reads the exact captured source and AST from CAS, binds the
head generation and snapshot revision, and accepts explicit native `ContractSpec`
values. It does not publish a new head or change the structural manifest.
The profile `current-python-int-bool-native-smt@1` uses the pipeline's
`typed-straight-line-int-bool-linear@1` mathematical model: admitted functions
have explicit Int/Bool inputs, straight-line assignments and linear expressions.
Unsupported types, division, nonlinear multiplication and unsupported control
flow reject translation.

Inside the connection block above, suppose captured `counter.py` contains
`def increment(n: int) -> int: return n + 1`. Both real `z3` and `cvc5`
executables must be available for a supported check:

```python
from ipfs_datasets_py.logic.software_verification.pipeline import ContractSpec
from ipfs_datasets_py.logic.software_contracts.codebase_verification import (
    load_codebase_verification, verify_current_codebase_unit,
)

record = verify_current_codebase_unit(
    index, "repository-under-test", expected_head=receipt.head,
    path="counter.py",
    contracts=[ContractSpec(
        "increment", postconditions=("result == n + 1",),
    )],
)
print(record.artifact_cid, record.conditional_proved)
historical = load_codebase_verification(index, record.artifact_cid)
assert historical.observed_live is False
```

The entire selected translation is preflighted, including VC/script and
representation limits, before any solver process starts. Representable unsupported
translations return a source-bound rejection sidecar; malformed, oversized or
nonrepresentable requests fail. For example, native metadata with floating-point
literals lies outside the existing CAS scalar profile and is rejected. Supported checks use the native solver
pair, with no caller-supplied checker or result callback. The sidecar retains
the full post-contract ProgramIR, VCs, SMT scripts, translation receipts,
canonical proof keys, implementation/executable fingerprints and raw process
observations, including stdout, stderr, exit status, timing and declared bounds.
The snapshot profile disables optional supervisor AST metadata, so replay uses
its recorded native datasets implementation. These keys identify conditional evidence; this API does not publish an
authoritative proof-cache entry.

The call uses one shared datasets lease, including its current-source
observations, or a child of an injected `parent_lease`. Optional `scheduler`,
`cancel_event`, `bounds`, `limits`, `memory_mb` and deadline arguments bound
admission and retained evidence. Solver subprocesses have native wall-time
timeouts; memory and output declarations are not hard RSS/output enforcement.
The head and live admitted source are reobserved before checking, after checking
and after CAS publication. An intervening edit or head change prevents a current
completion, although an immutable historical artifact can remain. This fence
is a point-in-time check; callers must reobserve at their later admission boundary.

`load_codebase_verification` replays captured historical source and contracts
without launching solvers or version probes. It requires the same native
implementation generation, recompiles ProgramIR/VCs/scripts/receipts, reparses
recorded raw observations and recomputes classifications, keys and coverage.
An implementation mismatch requires explicit migration. Historical loading
works after checkout changes and supplies no current-freshness claim:
`observed_live` stays false. Integrity and deterministic replay do not attest
that a trusted checker produced the recorded process bytes.

Both fresh and historical records remain conditional model evidence.
`kernel_checked`, `source_runtime_semantics_verified`, `behavioral_satisfaction`,
`authoritative_cache_eligible`, `admission_authority` and `completion_authority`
are all false. A conditional proof is not evidence that the Python runtime
satisfies the contract, and inconsistent premises can still prove a goal
vacuously. This closes the grounding of verification inputs only; authoritative
cache integration, runtime-semantics validation and planner admission gates
remain separate work. The additive applicability sidecar below checks entry
premises and requested domains without changing this historical schema. It
performs no model fitting and starts no planner service.

The existing narrowed `python-integer-offset@1` API remains compatible:
[CodebaseIntegerVerifier](../../ipfs_datasets_py/logic/software_contracts/codebase_integer_verification.py),
[IntegerOffsetContract](../../ipfs_datasets_py/logic/software_contracts/codebase_integer_profile.py)
and [CodebasePropertyCache](../../ipfs_datasets_py/logic/software_contracts/codebase_property_cache.py)
retain their roles. The new sidecar extends conditional Int/Bool VC evidence
and historical replay; it does not replace that API or promote its historical
candidates into authoritative cache entries.

## Requested-domain checks and durable conditional lookup

[RequestedInputDomain](../../ipfs_datasets_py/logic/software_verification/applicability.py)
names an explicit function entry domain using Int/Bool parameter predicates.
`True` means the complete admitted typed domain. Each contract derives four
separate queries: satisfiable preconditions, a nonempty requested domain, the
requested domain implying the preconditions, and the source property restricted
to that requested domain. The first three omit body equations, return values
and postconditions. Locals, result values, old state, unknown variables and
unsupported operations cannot be substituted for entry inputs.

[verify_current_codebase_applicability](../../ipfs_datasets_py/logic/software_contracts/codebase_applicability.py)
links its immutable `codebase-input-applicability@1` sidecar to an exact native
verification CID and current source head. It records the complete four-query
inventory, native Z3/CVC5 observations, classifications, tools and canonical
keys. A conditional proof or refutation requires all three input gates. An
empty domain or contradictory premise remains vacuous even if a theorem query
returns UNSAT; an uncovered request domain remains ineligible. A counterexample
to the parent's wider contract does not refute a narrower requested domain.
Only the fourth query establishes the recorded property outcome on that domain.
`load_codebase_applicability` rederives and replays historical records without
launching solvers or asserting current freshness.

[CodebaseVerificationCatalog](../../ipfs_datasets_py/duckdb_control/codebase_verification_catalog.py)
uses a separate `codebase_verification_control` schema on the same native
file-backed DuckDB AST connection. It leaves the structural owner's closed
schema and head authority intact. `publish` atomically projects sealed evidence
references, authored and lowered contract CIDs, complete proof keys and source,
tool, implementation, environment and domain dependencies. `lookup_current`
performs bounded exact lookup and native artifact replay between live source
observations. It rejects corrupt SQL/CAS records, missing artifacts, stale heads
and oversized results. Operation identities bind complete publication requests.
History remains immutable; conservative complete-head matching prevents reuse
across successors, including identical-snapshot republication.

```python
from ipfs_datasets_py.logic.software_contracts.codebase_applicability import (
    verify_current_codebase_applicability,
)
from ipfs_datasets_py.logic.software_verification.applicability import RequestedInputDomain
from ipfs_datasets_py.duckdb_control.codebase_verification_catalog import CodebaseVerificationCatalog

# index, repository, head and verification are explicit native owner artifacts.
domain = RequestedInputDomain("increment", predicates=("n >= 0",))
applicability = verify_current_codebase_applicability(
    index, repository, expected_head=head,
    verification_cid=verification.artifact_cid, domains=[domain],
)
catalog = CodebaseVerificationCatalog(index)
projection = catalog.publish(
    repository, expected_head=head, verification_cid=verification.artifact_cid,
    applicability_cid=applicability.artifact_cid, operation_id="publish:increment-domain",
)
```

Lookup selectors include the authored contract CID and **complete domain CID**;
the logical `domain_id` alone can name different predicate content. A missing
projection means unknown. Multiple exact runs require an explicit verification
CID or native key selector; lookup never silently chooses the newest result.
Neither projection nor lookup writes an authoritative proof cache or attests
the origin of stored process bytes. Resource admission and result bounds use
the existing shared scheduler; general SMT process memory/output declarations
remain cooperative rather than hard RSS/output enforcement.

The accelerator's additive
[conditional IntentIR adapter](../../../ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/planning/conditional_codebase_evidence.py)
joins a reviewed native mathematical atom to those exact contract/domain CIDs.
It retains the original text, complete native IntentIR and source-span ledger.
The complete native document is preserved as its canonical UTF-8 JSON string,
including floating-point confidence metadata that the outer CAS scalar codec
cannot encode directly. Lookup performs no fitting, solver execution or version
probe. Review labels describe authored interpretation; review custody and free
text semantics are unverified. All runtime requirements remain residual,
`current_facts` is empty and behavioral, kernel, authoritative cache, admission
and completion authority remain false.

The retained
[domain/index execution](../../workspace/codebase-domain-index-qualification-20261002/execution.json)
includes real source-model proof/refutation, contradictory premises, an empty
domain and incomplete domain coverage. Its authored positive-domain example
proves `result > 0` for `n >= 0` even though the parent contract fails over all
integers. Fresh-process native DuckDB/CAS lookup reproduces all six outcomes
with checker execution forbidden; a behavior-changing edit refuses the old
head. These checks qualify conditional typed mathematics and exact lookup,
not Python runtime semantics, general instruction interpretation or production
planner admission.

## Source and cache identity

`snapshot_repository` remains the acquisition authority. The new ingestion
entry point consumes its captured bytes without rereading the working tree.
Clean Git, dirty Git, unborn Git and plain filesystem snapshots use their full
snapshot CID as the AST revision identity. Two dirty states at the same HEAD
therefore cannot collide through a shared `+dirty` revision label.

The manifest includes every admitted entry, its disposition, exact source and
AST references, the canonical semantic state and separate coverage counts.
Deleted, oversized and otherwise opaque entries stay visible. Exclusions remain
explicit in the snapshot. Unsupported AST frontends yield unindexed entries.
Paths that cannot be represented exactly by AST provenance fail closed.

AST shard reuse binds source bytes, path/module context, language, parser
capability/toolchain, implementation, configuration and schema. Renames reparse
qualified names. Unknown frontend implementations conservatively reparse.
The wrapper re-extracts semantic state even when a previous manifest is supplied:
a content hash alone cannot authenticate the producer of prior semantic facts.
The `previous` argument currently checks repository lineage; authenticated
incremental semantic-state reuse is future work.

Syntax, encoding and parser-resource failures remain failed AST evidence.
Partial extraction and successful syntax parsing have separate statuses. All
manifest properties remain `structural_only`, with zero formalized or checked
properties in this profile.

## Persistence and cancellation

File-backed `DuckDBASTStore` reads reconstruct the requested AST from its canonical
payload and check its relational projections. It does not hydrate the whole
database into Python dictionaries at startup. `apply_batch` atomically publishes
projection changes and invalidations. Failed SQL transactions leave the prior
active view intact.

Preparation seals source bytes, canonical AST bodies and the manifest in the
immutable CAS before the AST transaction. Artifact-sealing failure or cancellation
before commit preserves the prior SQL view. SQL failure can leave unreferenced
immutable artifacts; their presence alone does not establish an active index.

A cancellation observed after SQL commit can suppress delivery of the returned
manifest even though the successor is fully committed. Retrying the same captured
state recovers idempotently. Restoring an earlier source snapshot also restores its
exact active AST projections instead of returning an invalidated cached receipt.

The optional catalog adds a persistent structural head within the AST transaction.
There is still no distributed transaction, DuckLake publication journal or
supervisor admission record. Historical manifests do not establish that the live
checkout still matches their captured bytes. The explicit observation above and
later planning/admission checks remain necessary.

## Resource policy

Without injection, preparation obtains one lease from the existing default shared
datasets scheduler. A caller may pass `parent_lease` to allocate a child within an
existing datasets reservation. The parent retains ownership and is not released
by preparation. Passing both `scheduler` and `parent_lease` rejects ambiguity.
Accelerate's [explicit shared resource bridge](../../../ipfs_accelerate/docs/agent_supervisor/SHARED_DATASETS_PROVER_RESOURCES.md)
now opens one native datasets envelope and admits supervisor tasks beneath it.
Pass its `datasets_parent_lease` into preparation to share that owner. Separate
standalone supervisor budgets do not silently become datasets authority.
The native propositional SMT task adapter exercises this crossing; broader
logic-family proof composition and full service activation remain open.

The default capture bounds are 256 admitted entries and 64 KiB per file. Exceeding
the entry bound fails; oversized files receive explicit opaque dispositions. A
conservative source-size estimate must fit the memory reservation. Larger bounds
can be requested with `CodebaseScanLimits`, subject to that estimate. Large-tree
paging is not implemented by this wrapper.

Preparation reserves one CPU and one child-process slot for sequential Git work.
Admission observes external memory/CPU/I/O pressure and the scheduler cooldown.
Cancellation and the overall deadline are checked between stages, between AST
ingestion files and before publication. Active Python extraction is not forcibly
preempted. Native database threads, buffers and temporary storage remain the
connection owner's configuration. The reservation is an admission estimate,
not a hard process RSS limit; cgroup enforcement and device accounting are later
qualification work.

## Train a bounded CodebaseIR feature candidate

The [captured CodebaseIR feature training API](CODEBASE_FEATURE_TRAINING.md)
registers the explicit `codebase_ir/codebase_feature_v1` runtime and fits an 8D
candidate from closed integer-model compiler targets. The current-source owner
uses shared resource admission and an isolated single-thread CPU worker by
default. Continuation preserves the feature basis, Adam state, original tuning
and canary targets, and complete bounded split ancestry. Unknown feature atoms
in any role require an explicit basis migration.

This objective reconstructs compiler features. Independent native property
checking remains necessary; learned vectors add no behavioral facts and no
model head is promoted. The [feature qualification](../../workspace/codebase-feature-qualification-20261002/qualification.md)
records real fitting, continuation after a source edit, changed conditional
proof outcomes and fresh-process model/evidence recovery.

## Train source bound ProgramIR feature generations

The additive
[source training coordinator](../../ipfs_datasets_py/logic/software_contracts/codebase_source_training.py)
uses the explicitly registered `codebase_ir/source_bound_feature_v1` runtime.
Its
[target adapter](../../ipfs_datasets_py/logic/software_contracts/codebase_ir_targets.py)
replays captured source, AST, ProgramIR and authored contract documents into the
native immutable domain-target envelope. Program and aggregate-contract
projections retain separate feature namespaces; literal and operator values
remain in the native expressions. This profile is separate from the preserved
`codebase_ir/codebase_feature_v1` integer-model API above. Neither profile is a
published 384D or learned formula runtime.

The current-source coordinator fits 8D structural feature candidates using the
existing CPU float64 backend. Its isolated worker reserves one CPU, limits Torch
and BLAS threads, and uses the native bounded-process lifecycle for cancellation,
wall time, input/output and sampled process-tree RSS. RSS sampling can overshoot;
it is not a delegated cgroup limit. Default shared datasets admission is active.
Source and model catalogs remain separate native owners, with different database
files; training does not publish a structural head or promote a model head.

Inside the current-head connection block, the captured repository must contain
three Python sources with distinct paths and nonduplicate contents, assigned to
the explicit roles below:

```python
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts.codebase_source_training import (
    CodebaseTrainingSelection, infer_current_codebase_features,
    load_codebase_feature_training, train_current_codebase_features,
)

selections = [
    CodebaseTrainingSelection("train.py", "train"),
    CodebaseTrainingSelection("tune.py", "tune"),
    CodebaseTrainingSelection("canary.py", "canary"),
]
with AutoencoderRegistry(cache / "models.duckdb", cache / "model-artifacts") as models:
    candidate = train_current_codebase_features(
        index, "repository-under-test", expected_head=receipt.head,
        registry=models, selections=selections, operation_id="source-features-0001",
    )
    version_id = candidate.to_dict()["version_id"]
    historical = load_codebase_feature_training(index, models, version_id)
    assert historical.observed_live is False
    current = infer_current_codebase_features(
        index, "repository-under-test", expected_head=receipt.head,
        registry=models, version_id=version_id, paths=["train.py"],
    )
    assert current["training_executed"] is False
```

Each immutable root or child binds the complete source head, selected paths and
contracts, split roles, canonical checkpoint bytes, feature contract, numerical
state, producer files and native model-registry ancestry. Source path and content
checks include bounded ancestral training history, so a later generation cannot
reassign an old training sample to tuning or canary. The root training targets
form the frozen vocabulary and replay cohort. A child supplies
`parent_version_id`, preserves the feature basis and complete Adam state, retains
the original tuning, canary and replay envelopes, and combines changed current
training sources with historical replay. Changing evaluation source, contracts,
roles or optimizer settings requires an explicit new lineage.

Tuning selects the numerical candidate. Canary and replay reconstruction are
recorded diagnostics after the selected state is fixed; the original parent
state supplies the child comparison. Repeated canary monitoring is neither an
unseen held-out qualification nor a semantic/property check, and it does not
select or promote the child. Unknown feature atoms remain explicit coverage
counts. They do not expand the frozen basis or establish that the candidate
learned unseen source literals or behavior; learning a new vocabulary requires
a distinct feature variant.

Bootstrap uses the existing native feature-candidate registration. A child uses
native create/claim/stage/complete operations with exact request, parent, attempt
and fence bindings. Exact completed-operation retries recover the recorded
candidate without another fit; a different payload under the same operation
identity rejects. Historical loading replays bounded source/model ancestry,
canonical checkpoint bytes, split bindings and native completion history without
launching a numerical worker, writing artifacts or asserting live freshness.
Replay requires the recorded producer/target implementation generation; a changed
implementation requires explicit migration.
Current training and inference observe the live source and exact structural head
at their boundaries; an edit or successor head refuses the old current binding.
Current inference is restricted to the registered cohort and performs no fitting.

Weights retain the existing native four-field feature checkpoint codec and
content-addressed registry artifact. The immutable CAS training record stores
the report as canonical JSON text, preserving float metadata without extending
the CAS scalar codec. This storage choice is not a binary federation format or a
DuckLake publication protocol. Runtime/source semantics, learned formal decoding,
checked-property objectives, authoritative proof-cache reuse, behavioral facts,
planner admission and completion authority remain unavailable.

The retained
[source-training execution](../../workspace/codebase-source-training-qualification-20261002/execution.json)
records an actual 8D parent with a 53-feature basis and Adam step 1, followed by a
step-2 child with changed parameters on the same contract and basis. The child
uses captured `n + 2` source plus frozen `n + 1` replay; its one unknown literal
atom stays explicit. Original tuning, canary and replay targets remain fixed.
Current child inference succeeds and the old parent is refused. Cancelling an
actual worker leaves a failed native run without completion or another model
version. Fresh-process parent/child replay forbids fitting, inference, source
scanning and CAS writes and preserves all 16 artifact files. No main model head
is selected, authority remains false and the scheduler retains no active lease
or waiter. The retained
[coordinator and independent mutation tests](../../workspace/codebase-source-training-qualification-20261002/source-training-tests.xml)
pass all 32 cases, and the
[target, runtime and compatibility suite](../../workspace/codebase-source-training-qualification-20261002/runtime-targets-tests.xml)
passes all 206 cases: 238 distinct tests, with no failures, errors or skips.

Compatible source-bound federation is now an additive implementation below.
Independent checked-property and behavioral target work remains open.

## Combine compatible CodebaseIR feature updates

The [source-owned federation coordinator](../../ipfs_datasets_py/logic/software_contracts/codebase_federated_training.py)
combines updates into one private model per lineage through the existing
same-parent FedAvg reducer and native registry create/claim/stage/complete
operations. Its [numerical adapter](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_federated_codebase.py)
accepts only the source-bound 8D CPU float64 profile, with an exact common
checkpoint, four parameter tensors, feature contract and vocabulary. Equal
tensor shapes alone do not permit different repositories' learned mappings to
be combined. Existing source-training and runtime files retain their identities.

This bounded executor operates on one captured repository and runs two to eight
private clients sequentially under the shared resource owner. A root must
register at least two training source paths alongside separate tuning and
canary paths. Clients partition **all** inherited training paths exactly once.
The owner derives weights from the actual number of source-target envelopes;
callers supply no sample counts. Original replay stays in aggregate diagnostics
and is not duplicated across local fitting batches. Every client clones the
exact parent weights and Adam state and uses the original fixed tuning targets.

```python
from ipfs_datasets_py.logic.software_contracts.codebase_federated_training import (
    CodebaseFederatedClient, load_codebase_federated_training,
    train_current_codebase_federated_round,
)

clients = [
    CodebaseFederatedClient("worker-a", ("a.py", "b.py")),
    CodebaseFederatedClient("worker-b", ("c.py",)),
]
aggregate = train_current_codebase_federated_round(
    index, repository, expected_head=receipt.head, registry=models,
    base_version_id=parent_record.to_dict()["version_id"], clients=clients,
    operation_id="codebase-round-0001", epochs=1, learning_rate=.002,
)
historical = load_codebase_federated_training(
    index, models, aggregate.to_dict()["version_id"],
)
assert historical.observed_live is False
```

The aggregate combines parameter deltas with approved counts. It resets all
Adam moments, steps and completed epochs to zero, preserving optimizer settings
and fixed tuning identity; private optimizer histories are never averaged.
This differs from the exact Adam continuation of the source-training API.
Later federated rounds can use the previous aggregate through this coordinator.
Use its own load and current-inference APIs for native federated candidates;
the earlier source-training loader retains its original meaning.

Each client record binds the complete captured head, authored selections,
actual target batch/count, configuration and producer identities. Updates use
the existing binary float codec, verified SHA-256 and raw CIDv1 before
reduction. The aggregate checkpoint retains the native four-field feature
codec. Historical loading replays source/native completion history, derives
every delta from the local state and common parent, and recomputes the exact
weighted aggregate and optimizer reset without fitting, inference, live scans
or artifact writes. Explicit `recover_codebase_federated_training` republishes
derived provenance after interrupted metadata publication, including after a
source successor; it asserts no current freshness. Completed same-request
retries perform no new numerical work. Competing claims use distinct invocation
identities; cancellation leaves no completed candidate or model promotion.

After local fitting, separate bounded numerical processes evaluate the parent
and aggregate on original canary/replay targets. These repeated reconstruction
diagnostics do not select the aggregate or qualify source behavior. Current
inference checks the registered cohort and exact live source/head. Unknown atoms
remain explicit coverage gaps. No proof, runtime theorem, planner admission or
completion authority follows from an aggregate or materialization verification.

The [typed synchronization boundary](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/codebase_federated_sync.py)
binds round/base/source/client/count/attempt/fence and exact float64 buckets.
It supplies artifact-reference descriptors for the canonical accelerator
`p2p_taskqueue_submit` route without submitting work or transferring tensors in
JSON. Federation is the default. The executor explicitly refuses gradient
mode; the separate native controller seam requires an independently qualified
backend and never silently falls back. Remote dispatch, parallel fleet training
and a running collective remain unqualified.

The [retained federation fixture](../../workspace/codebase-federation-qualification-20261002/execution.json)
executes two 2:1-weighted rounds with four real local fits on a frozen 55-feature
basis, source successor/unknown-atom controls, current/stale inference, actual
cancellation, completed retry recovery and fresh-process replay preserving all
28 artifact files. The focused federation suite passes 97 cases and native
regressions pass 215: [312 distinct passing tests](../../workspace/codebase-federation-qualification-20261002/qualification.md).
All 32 production
acceptance gates remain open. The additive native dispatch implementation below
extends this bounded lifecycle; remote fleet dispatch and
independent checked-property/behavioral targets remain open. Features remain advisory.

## Dispatch bounded CodebaseIR artifact jobs

The additive [dispatched owner](../../ipfs_datasets_py/logic/software_contracts/codebase_dispatched_federation.py)
uses the canonical sibling accelerator's
[explicit dispatcher](../../../ipfs_accelerate/ipfs_accelerate_py/p2p_tasks/codebase_federated_dispatch.py)
with a native local `TaskQueue`. Each claim has a unique worker identity and an
exact request commitment. Queue attempt, lease and deadline checks surround the
handler; the datasets owner also checks the live source head and native training
round attempt/fence. Only that owner materializes and registers the aggregate.
The existing source/federation producer files and model checkpoint schema are
unchanged; transport provenance occupies a separate immutable sidecar.

The [artifact worker](../../ipfs_datasets_py/logic/software_contracts/codebase_federated_artifacts.py)
receives verified CIDv1/SHA-256 references for the exact round, base checkpoint,
captured client targets and inherited tuning/canary/replay context. It opens no
source index or model registry and executes no repository-under-test code. A
bounded isolated CPU float64 process fits the client; the worker returns a binary
delta and private checkpoint references. A locked, durable exact-request receipt
lets retries recover the result without fitting, after rechecking all artifacts,
scope, cancellation and deadline. These receipts grant no execution attestation,
qualification, promotion or proof authority.

```python
from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import CodebaseQueueDispatcher
from ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts import CodebaseFederatedArtifactWorker
from ipfs_datasets_py.logic.software_contracts.codebase_dispatched_federation import (
    train_current_dispatched_codebase_round, load_dispatched_codebase_round,
)

# Use the canonical external/ipfs_accelerate checkout, alongside datasets.
queue = TaskQueue("private-worker-queue.duckdb")
worker = CodebaseFederatedArtifactWorker(transfer_cas, "private-worker-receipts",
                                        scheduler=scheduler)
dispatcher = CodebaseQueueDispatcher(queue, worker)
record = train_current_dispatched_codebase_round(
    index, repository, expected_head=current_head, registry=registry,
    base_version_id=parent_version_id, clients=clients, operation_id="dispatch-1",
    dispatcher=dispatcher, scheduler=scheduler,
)
historical = load_dispatched_codebase_round(
    index, registry, record.to_dict()["version_id"], queue=queue,
    artifacts=transfer_cas, artifact_cid=record.artifact_cid,
)
```

Historical loads verify the old compatible model, native completion, exact
terminal queue rows and returned artifact bytes without fitting or durable
artifact publication. Pass the sidecar CID to load its exact task IDs; discovery
without it examines at most 1,000 completed tasks and can report missing history
in a long-lived queue. Explicit `recover_dispatched_codebase_round` republishes
sidecar provenance after durable completion and performs no fitting.

Use the additive
[indexed recovery API](../../ipfs_datasets_py/logic/software_contracts/codebase_indexed_dispatch_recovery.py)
when the sidecar CID is unavailable. It reconstructs exact request references
from committed work, original parent bytes and inherited evaluation context,
then uses the canonical accelerator's
[native request lookup](../../../ipfs_accelerate/ipfs_accelerate_py/p2p_tasks/codebase_federated_history.py)
against the existing unique idempotency index. It performs one lookup per client
and runs the same full model, queue-row, artifact and snapshot verifier. The new
API defaults to indexed discovery; `use_request_index=False` restores the legacy
bounded scan. Caller feature/history limits apply on indexed, sidecar-CID and
opt-out paths. Historical results remain `observed_live=False`.

```python
from ipfs_datasets_py.logic.software_contracts.codebase_indexed_dispatch_recovery import (
    load_indexed_dispatched_codebase_round, recover_indexed_dispatched_codebase_round,
)

historical = load_indexed_dispatched_codebase_round(
    index, registry, version_id, queue=queue, artifacts=transfer_cas,
)
# Explicitly repair missing provenance after a verified durable completion.
recovered = recover_indexed_dispatched_codebase_round(
    index, registry, version_id, queue=queue, artifacts=transfer_cas,
)
```

The [indexed qualification](../../workspace/codebase-indexed-recovery-qualification-20261002/qualification.md)
retains exact recovery among 10,000 older same-type tasks, a native index-scan
plan, component lookup timings and fresh-process replay preserving the original
sidecar identities and 70 retained files. It makes no inference or full-replay
speedup claim. The protected original training entrypoint retains legacy
discovery. The new training entrypoints below integrate exact completed retry
recovery. Remote queue/Quack reads remain outside this local qualification.

The [retained qualification](../../workspace/codebase-dispatch-qualification-20261002/qualification.md)
records two native 2:1 rounds/four client fits, a changed-source successor, lost
response/private receipt recovery, real numerical cancellation and fresh-process
replay preserving 70 artifact, lock and receipt files. This qualifies the authored
five-file local queue path with sequential clients. Remote peer delivery, the
generic worker loop, a parallel fleet, gradient collectives, model promotion and
learned proof/property targets remain unqualified. No production acceptance gate
is closed, and this run measures no inference latency speedup.

## Train with exact retries and bounded parallel clients

Use [the indexed training wrapper](../../ipfs_datasets_py/logic/software_contracts/codebase_indexed_dispatched_training.py)
for sequential fitting with exact completed retries:
`train_current_indexed_dispatched_codebase_round` accepts the original trainer's
arguments and defaults to `use_request_index=True`. Before recovering a completed
round it checks the live source, original parent, complete client partition and
optimizer configuration against the native idempotent creation payload. It
performs no queue claim, dispatch or fit. Both discovery policies check parent
feature width and prospective training history before creating a run.
`use_request_index=False` selects the original bounded history scan.

For local parallel fitting, use the additive
[parallel owner](../../ipfs_datasets_py/logic/software_contracts/codebase_parallel_dispatched_federation.py)
with the same native index, registry, worker, transfer CAS and dispatcher:

```python
from ipfs_datasets_py.logic.software_contracts.codebase_parallel_dispatched_federation import (
    train_current_parallel_dispatched_codebase_round,
    load_parallel_dispatched_codebase_round,
)

record = train_current_parallel_dispatched_codebase_round(
    index, repository, expected_head=current_head, registry=registry,
    base_version_id=parent_version_id, clients=clients, operation_id="parallel-1",
    dispatcher=dispatcher, scheduler=scheduler,
    # Defaults: parallel=True, max_workers=2, use_request_index=True.
)
historical = load_parallel_dispatched_codebase_round(
    index, registry, record.to_dict()["version_id"], queue=queue,
    artifacts=transfer_cas, artifact_cid=record.artifact_cid,
)
```

`parallel=False` opts out of concurrent fitting; `max_workers=1` also executes
one client at a time. `use_request_index=False` opts out of indexed discovery.
These settings, worker/control memory and the actual worker count are immutable
execution policy: changing them requires a new operation ID. The fixed native
creation key rejects changed policy, parent, source, clients or optimizer inputs
on the same operation. Defaults reserve 1,024 MB per worker and 1,024 MB for
control work. With `W=min(max_workers, client_count)` parallel workers,
[resource admission](../../ipfs_datasets_py/logic/software_contracts/codebase_parallel_resources.py)
reserves `W + 1` CPU/process slots and
`W * worker_memory_mb + control_memory_mb` under the shared scheduler. Capacity
must be admitted before work starts; the trainer does not silently reduce `W`.

Each executor thread establishes its own dispatcher and worker scopes. At most
`W` client futures are submitted concurrently; native source observations and
training-fence checks are serialized in the control envelope. Numerical workers
remain isolated CPU float64 processes with one Torch/BLAS thread. Completion order
does not affect canonical client-order validation or deterministic weighted
reduction. An error, cancellation, source change or expired/replaced native lease
stops peers and joins all workers before owner failure or reservation release.
This is shared admission plus the existing process memory enforcement; it adds
no aggregate cgroup or remote fleet pressure qualification.

The immutable policy CID is bound into the native run identity. A separate
`codebase-parallel-dispatched-federation@1` sidecar links it to the original
compatible transport sidecar. Model checkpoints, historical producer pins,
fixed evaluation ancestry and aggregate Adam reset remain compatible. Historical
loads validate policy/model/queue/artifact history without live scans, fitting or
publication. Explicit `recover_parallel_dispatched_codebase_round` repairs
sidecar provenance after durable completion; completed training retries use that
route by default. Interrupted attempts retain their old fence, so a newly claimed
attempt does not reuse private fits from that older attempt.

The [parallel qualification](../../workspace/codebase-parallel-dispatch-qualification-20261002/qualification.md)
records real native subprocess/lease overlap, failure and cancellation cleanup,
source/fence rejection, exact retries and fresh-process replay preserving 186
artifact, lock and receipt files. Three matched trials per mode on an authored
five-file, 8D/55-feature fixture produced identical aggregate states: median
whole-round time was 15.738 seconds sequentially and 13.428 seconds with two
workers (1.172 times the rate). These small instrumented, startup-dominated local
rounds establish neither inference latency nor large-workload/remote throughput.
All authority flags remain false; semantic/property targets, model promotion,
gradient collectives and all production acceptance gates remain open.

## Check a conditional integer contract

The additive [integer verifier](../../ipfs_datasets_py/logic/software_contracts/codebase_integer_verification.py)
joins the current structural owner to a closed source profile, the existing
source/VC/SMT compiler, native Z3/CVC5 execution and a historical property cache.
It leaves the structural manifest's coverage and authority unchanged.

```python
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract
from ipfs_datasets_py.logic.software_contracts.codebase_integer_verification import CodebaseIntegerVerifier
from ipfs_datasets_py.logic.software_contracts.codebase_property_cache import CodebasePropertyCache

verifier = CodebaseIntegerVerifier(index, CodebasePropertyCache(cache / "properties"))
checked = verifier.verify(
    "repository-under-test", expected_head=receipt.head,
    contract=IntegerOffsetContract("counter.py", "increment", "n", 1),
)
print(checked["status"], checked["cache_history_hit"], checked["solver_replayed"])
```

`python-integer-offset@1` admits a single synchronous function per source file,
with one parameter and return both annotated `int`, and one return expression:
that parameter, or its addition/subtraction by a bounded integer literal. Source
is ASCII, at most 64 KiB and 64 AST nodes. The guard rejects defaults, decorators,
extra definitions, imports, calls and unsupported effects without importing the
target. It independently compares native typed body/goal terms to the guarded
source, then regenerates the compilation before checker execution.

The theorem assumes the argument is an **exact builtin Python integer** (excluding
bool and subclasses) and ideal unbounded integer arithmetic. An annotation does
not enforce that assumption. Module loading/rebinding, concurrent mutation,
resource exhaustion and asynchronous exceptions remain outside this model.
`proved` and `refuted` describe agreement by both native SMT solvers on this
conditional model. They are neither kernel certificates nor Python runtime
proofs/counterexamples. Unsupported, unavailable, timeout, error, unknown and
disagreement results supply no positive evidence.

Both native Linux executables run sequentially in shared validation child leases.
The default enclosing reservation is 1 GiB; each checker has a 256 MiB address
space limit and sampled process-tree RSS guard, with 64 KiB input/output/workspace
bounds and a shared ten-second check budget. Safety and pressure backoff use the
default datasets scheduler. The Python reservation remains cooperative; sampled
RSS can overshoot. Cancellation and expiry withhold a completed result. Only ELF
executables and the existing installer's exact launcher shape are admitted.
Installed tools and their owner-controlled discovery path are trusted; recorded
binary/version/implementation hashes identify them without authenticating their
provenance. Ambient shared libraries are outside the fingerprint coverage.

The cache binds source, snapshot, full contract, compilation, assumptions,
implementation, environment and bounds through the canonical proof key. Durable
entries have leased `UNKNOWN` receipts and remain historical candidates. Every
supported verification compiles and runs fresh checks, including a cache hit.
`solver_check_attempted` records entering the check path; `solver_replayed`
requires completed verdicts from both native tools. This single-call historical
cache supplies no proof-execution speedup or durable DuckDB evidence projection.
Source/head observation before
checking and after sealing withholds the result on drift; later consumers still
need their own live observation.

The accelerate [typed intent adapter](../../../ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/planning/checked_integer_codebase.py)
accepts an explicit native `integer_offset` requirement. Its optional exact
sentence grammar is:

```text
Under python-integer-offset@1, counter.py::increment(n) must return n + 1.
```

`build_integer_offset_intent(text)` builds that native document;
`match_checked_integer_intent(index=index, repository=..., repository_id=view_id,
expected_head=receipt.head, intent_document=document, source_text=text, cache=...)`
validates it and invokes the verifier within entry/exit structural observations.
The outcome is `conditional_contract_matched`, `conditional_contract_refuted` or
`unknown`. Free text has no independently checked alignment outside the closed
grammar. Runtime requirements remain residual, current behavioral facts stay
empty, and planner task removal/execution/completion authority stays false.
Public supervisor service activation, broad source semantics, learned CodebaseIR
training and the production proof-index/admission join remain separate work.

The [conditional integer qualification](../../workspace/codebase-integer-qualification-20261002/qualification.md)
records focused tests, native checker identities and a bounded current-source →
IntentIR → SMT benchmark, including fresh-process cache history and edited/restored
source. Run that benchmark with both repositories on the import path:

```bash
IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS=0 IPFS_TEST_PROOF_REUSE_MODE=off \
PYTHONPATH="$PWD/../ipfs_accelerate:$PWD" \
python benchmarks/bench_codebase_integer.py \
  --output workspace/codebase-integer-local/benchmark.json
```

## Check and index a bounded batch

`CodebaseIntegerVerifier.verify_many` checks independent contracts concurrently
and publishes their terminal conditional observations to the native
[`CodebaseEvidenceIndex`](../../ipfs_datasets_py/duckdb_control/codebase_evidence_index.py)
by default. The index shares the structural catalog's DuckDB connection and CAS.
Workers receive captured bytes and declarative contracts; only the calling owner
thread reads or writes SQL, cache entries and CAS artifacts.

```python
batch = verifier.verify_many(
    "repository-under-test", expected_head=receipt.head,
    contracts=[
        IntegerOffsetContract("counter.py", "increment", "n", 1),
        IntegerOffsetContract("counter.py", "increment", "n", 2),
    ],
    max_workers=4,
)
print([result["status"] for result in batch["results"]])

from ipfs_datasets_py.duckdb_control.codebase_evidence_index import CodebaseEvidenceIndex
evidence = CodebaseEvidenceIndex(index.catalog)
first = batch["results"][0]
history = evidence.lookup(first["cache_binding"], expected_head=receipt.head)
dependents = evidence.dependents("source", first["source_cid"], expected_head=receipt.head)
```

The default upper bound is four workers, capped by distinct contracts and the
configured scheduler/parent CPU, process and memory capacity. An explicit upper
bound may range from one to 32 workers. The batch admits at most 64 contracts,
retains their input order and duplicate requirements, and executes each distinct
contract once. At most one future per effective worker is submitted; pending
work does not build an unbounded executor queue. Unsupported source remains an
explicit result and receives no terminal evidence entry.

The default enclosing reservation is `512 + 512 * workers` MiB with one CPU/process slot
per worker. Each worker obtains a 512 MiB child before compilation; its sequential
Z3/CVC5 calls use 256 MiB descendants. New worker and solver admissions observe
external pressure. Active processes retain their memory/output/time bounds.
Cancellation, deadline expiry and unexpected worker failure cancel and join
siblings before returning an error. Python parsing and file reads remain bounded
cooperative stages. Linux process launch uses the installed native `prlimit`
helper to apply limits without a Python pre-exec hook in threaded workers; a
missing helper fails closed and its identity is included in checker metadata.

The batch seals complete compiled artifacts and verification receipts, observes
current source, then atomically publishes terminal receipts with reverse source,
snapshot, contract, compilation, profile, environment and compiler dependencies.
Publication fences the head row against concurrent structural writers. Final
source/head observation withholds delivery if anything changes. Late refusal may
leave historical artifacts or indexed observations; neither grants current
authority. Exact publication retries are idempotent. A fresh interpreter can
validate indexed metadata and immutable artifacts without compiler/solver calls.

Lookup requires the exact current durable head and full binding. It is a bounded
historical query, not a live checkout observation or an execution-bypass API.
Receipt and compilation artifacts and evidence SQL rows have byte caps. Active
AST verification uses the existing AST store's row-bounded reconstruction;
arbitrary hostile SQL contents have not been qualified as memory-safe. Configure
DuckDB limits and owner admission separately.
Result-cap overflow rejects the query instead of silently truncating it. The
initial index has a finite 2,048-record capacity and preserves history; retention,
paged large indexes, migrations and DuckLake publication remain later work.

The accelerate
[`checked_integer_batch`](../../../ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/planning/checked_integer_batch.py)
adapter builds and checks up to 32 explicit requirement envelopes, including
duplicate contracts and unsupported atoms. `build_integer_offset_requirements`
accepts a list of exact sentences; `match_checked_integer_requirements` invokes
one owner batch and returns a complete conditional outcome ledger. Every runtime
requirement remains residual and behavioral facts remain empty. This adapter
does not interpret arbitrary full prompts or activate the public planning service.

The [batch qualification](../../workspace/codebase-batch-qualification-20261002/qualification.md)
records native execution, bounded queues, pressure recovery, cancellation,
publication integrity, restart queries and the 1/2/4-worker benchmark. Reproduce
the benchmark with:

```bash
IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS=0 IPFS_TEST_PROOF_REUSE_MODE=off \
python benchmarks/bench_codebase_integer_batch.py \
  --output workspace/codebase-batch-local/benchmark.json
```

## Qualification

The [2026-10-02 source-verification execution](../../workspace/codebase-conditional-verification-20261002/execution.json)
records 482 distinct focused cases with passing latest outcomes. The combined
481-case run preceded the final executable/launcher pin refinements; a separate
43-case bridge run qualifies those changes and one additional regression.
The retained [authored fixture](../../workspace/codebase-conditional-verification-20261002/fixture-report.json)
captures one Git repository file and genuine Z3/CVC5 agreement: `n + 1` is proved
and `n + 2` is refuted in the explicitly typed model. Both immutable sidecars,
their source/AST/head bindings and raw observations remain available in its CAS.
This is conditional-model qualification. It establishes no runtime theorem,
authoritative proof-cache hit, IntentIR satisfaction, training benefit or
supervisor admission.

The [current-head qualification](../../workspace/codebase-current-qualification-20261001/qualification.md)
records 346 passing tests across datasets and accelerate, including native writer
races, postcommit recovery, corruption, planning-context drift and bounded CAS
reads. Its separate sequential benchmark measures publication and live observation
with the default shared scheduler. It does not qualify real host-pressure loading,
hard RSS enforcement, proof throughput or many-core scaling.

The [2026-10-01 qualification report](../../workspace/codebase-ir-qualification-20261001/qualification.md)
records 196 passing tests, the bounded benchmark, runtime/source fingerprints and
the remaining qualification limits. Its resource-pressure cases use controlled
telemetry; they do not establish behavior under real host memory exhaustion.

The new integration tests exercise real Git snapshots, native DuckDB, canonical
CAS artifacts and a fresh interpreter for replay. They cover dirty edits at
unchanged HEAD, additions/deletions, snapshot restoration, forged manifests and
prior state, native parse failures, resource pressure, nested accounting, artifact
failure, cancellation before/after commit and retry. Dedicated store tests cover
corruption and atomic rollback; resource tests cover deferred admission and recovery.

From the datasets checkout, run the new end-to-end tests with:

```bash
IPFS_TEST_PROOF_REUSE_MODE=off \
PYTHONPATH="$PWD/../ipfs_accelerate:$PWD" \
python -m pytest -q \
  tests/integration/logic/software_contracts/test_codebase_ir.py \
  tests/unit/logic/software_contracts/test_codebase_ir_untrusted_previous.py \
  tests/unit/logic/software_contracts/test_codebase_resources.py \
  tests/unit/logic/software_contracts/test_duckdb_ast_store_persistence.py
```

The bounded structural benchmark is
[bench_codebase_ir.py](../../benchmarks/bench_codebase_ir.py). It measures cold,
unchanged, edited and restored snapshots plus native restart lookup. AST-ingestor
parse counters do not include the separate semantic extraction. Benchmark results
do not qualify neural training, proof throughput or many-core scaling.

The later [shared prover scaling qualification](../../workspace/shared-prover-scaling-qualification-20261002/qualification.md)
measures the shared datasets/supervisor resource path independently of repository
semantics. Healthy scheduler reads skip unchanged durable writes; a bounded
dependency-ready queue admits work with current pressure and weighted capacity.
Its larger authored SMT fixture reaches 2.42× execution speedup at four workers
(1.87× including preparation), while the tiny fixture still slows at higher
width. A closed native Lean Nat profile shares the same owner and rejects stale
or contradictory result metadata. Source capture, conditional integer batches,
current-head operations and feature training are rerun as regressions. These
observations add no source correspondence, learned decoder, authoritative proof
cache reuse or cross-family proof-composition guarantee. The
[API guide](../../../ipfs_accelerate/docs/agent_supervisor/SHARED_DATASETS_PROVER_RESOURCES.md)
describes the resource and evidence contracts.

The subsequent [bounded TLC qualification](../../workspace/shared-prover-tlc-qualification-20261002/qualification.md)
adds a closed finite-counter model-check task alongside SMT and Lean under that
same owner. Native counterexamples block dependent tasks, and exact result
bindings preserve finite safety-only scope. Model/version process bounds and
streaming installer-download limits receive native and failure-path tests.
These reusable execution components do not establish correspondence between a
repository function, IntentIR requirement and TLA model; that admission gate
remains open.

The subsequent [Isabelle and task-sized bundle qualification](../../workspace/shared-prover-isabelle-qualification-20261002/qualification.md)
adds a generated Isabelle/HOL Nat theorem and a bundle entry point that derives
one shared envelope from the tasks' declared costs. Default admission and live
backoff remain active; installed TLC runtime preparation now has its own
admitted, bounded probes. These checks preserve separate generated-theorem and
finite-model scopes. They do not establish source/IntentIR correspondence,
general proof composition or production repository-evidence admission.

The earlier [installer and runtime preparation milestone](../../workspace/shared-prover-installer-qualification-20261002/REPORT.md)
extends default admission with PID/task headroom backoff. Visible host and
cgroup counters include OS threads; conservative reservation estimates defer
new work when that capacity is scarce. This adds an admission check, not a hard
process/thread ceiling or a guarantee that external workloads cannot exhaust
the host.

[`prepare_isabelle_runtime`](../../ipfs_datasets_py/logic/backends/installers/isabelle_preparation.py)
offers bounded `command`, `hol` and `smoke` observations under the shared owner.
Each native phase obtains a fresh child and rechecks pressure, cancellation and
the remaining deadline. Private JVM/ML settings apply to discovery as well as
checking. The existing setup utility now uses this path for default inspection
and smoke; the closed Nat adapter shares its launch profile while retaining
exact theorem acceptance. Smoke follows a no-build HOL preflight, with the
explicit caveat that changed trusted inputs can trigger a bounded private
rebuild afterward. Readiness remains historical runtime evidence, with no
repository or proof authority.

Archive handling now bounds streamed downloads, extracted bytes, members, paths
and metadata, rejects unsafe archive entries, and checks cancellation/deadlines
while waiting for installation locks and processing data. These checks remain
cooperative. The fresh-archive qualification harness uses retained official
bytes through loopback HTTP and contains installation in an admitted bounded
worker; it does not establish fresh remote-download behavior or universal
installer containment. Explicit legacy install/build operations and their
separate probes retain lifecycle gaps. Final qualification totals belong to the
linked report; this partial milestone adds no source/IntentIR correspondence,
general proof composition or public service activation.

The final selected suites passed **900 tests with zero failures, errors or skips**.
They also cover two repaired supervisor races: cancellation/deadline checks at
native result publication, and queue refill when admission finishes before an
active task. Earlier failed attempts and live external-pressure backoff remain
in the qualification record; the fixes do not relax admission limits.


The [bounded production installation qualification](../../workspace/shared-prover-installation-runtime-qualification-20261002/REPORT.md)
adds default shared admission for the ordinary Isabelle setup/lazy/registry route.
`ensure_isabelle_installation` runs download/hash/extraction in a bounded worker,
then fresh bounded kernel smoke before and after controller publication. The old
runtime and launcher remain recoverable until validation; ordinary cancellation
or failure restores them. Partial downloads stay in private staging even if a
worker is killed. Large cleanup is bounded and unfinished paths remain explicit
in `cleanup_pending`. Publication is not crash-atomic; filesystem rollback can
overrun the operation deadline. Custom/direct legacy installers and some outer
discovery/lock paths retain separate limits; persistent HOL builds now have the
additional staged path below.

`SolverPortfolio` also defaults to one finite overall deadline, derived from its
hammer policy. Admission waits, queued work, probes and native solver work consume
that budget; explicit per-admission and per-solver caps can shorten it. Late
conclusive outputs are suppressed. This narrows resource-lifecycle gaps without
adding source semantics, authoritative proof reuse, general mixed-family
composition, broad many-core measurements or public planner admission.

The [persistent HOL build measurement](../../workspace/isabelle-hol-build-qualification-20261002/official-hol-build-6g/result.json)
completed a real rebuild from retained pinned archive bytes with downloads
disabled. The default shared parent reserved four CPU credits, twelve process
credits and 6,400 MiB; the native build's sampled RSS budget was 6 GiB. Staged
HOL artifacts were removed while Pure was preserved, a new successful build UUID
was produced, and the published heap manifest matched the rebuilt output.
Bounded build-worker time was 286.896 seconds, the full cold transaction took
329.660 seconds, warm verification took 10.319 seconds, and the benchmark took
347.482 seconds including admission and hashing. Descendants peaked at 5,222.87
MiB, twelve processes and 85 OS threads; all sampled descendants and owned
leases drained. This is one runtime fixture, not scaling or aggregate cgroup
qualification. The earlier smaller-JVM attempt failed and was recovered in
separate retained follow-ups. The
[final phase qualification](../../workspace/isabelle-hol-build-qualification-20261002/REPORT.md)
records 1,217 distinct cases with passing latest results and no latest errors
or skips; raw execution retains 1,219 runs, including two timeout failures that
passed exact unchanged-source retries without relaxing limits.
These remain partial RPI-022/024/025 inputs; no source/IntentIR or general
cross-family proof acceptance gate closes.

A separate [native cancellation control](../../workspace/isabelle-hol-build-qualification-20261002/native-cancel/result.json)
passed all sixteen checks after observing active Java and two Poly/ML processes
in distinct groups. All sampled PID/birth identities stopped before return,
publication was refused, and a separate admitted cleanup removed the stage
without rewriting the cancelled receipt. Observed ancestry tracking covers this
native fixture; it is not a hostile-process sandbox or aggregate cgroup limit.

The subsequent [public Isabelle adapter measurement](../../workspace/isabelle-hammer-execution-qualification-20261002/native-public-input-bounds/result.json)
qualifies the ordinary `IsabelleFrontend` and `IsabelleReconstructor` paths under
default shared admission. Each adapter operation covers its own preparation and
theory execution; native phases receive fresh child leases. The 51.014-second
fixture passed twenty checks, accepted a true reconstructed theorem, rejected
a false one, and cancelled an active public capture after observing its admitted
theory child and live Poly/ML. All owned leases and sampled live descendants
drained. This run observed no admission backoff; the earlier 71.395-second run
retains its own pressure observations and prior source hashes. Early source
bounds and unexpected-controller-exception cleanup are included in the selected
generation. The native profile reserves three CPU credits, twelve process
credits and 2,304 MiB; sampled descendants peaked at 591.09 MiB. Controller memory
is recorded separately and is not capped by the coordination allowance.
The [phase report](../../workspace/isabelle-hammer-execution-qualification-20261002/REPORT.md)
records 1,460 passing latest outcomes and ten legacy Coq cases skipped by
PATH-based availability gates, across 1,470 distinct cases. Raw execution
retains 1,480 cases and one obsolete executable-path assertion failure; the
entire corrected ten-case file passed without a production change. Native Coq
coverage remains unqualified; the skips do not establish that no managed runtime
is installed. This is trusted HOL with a
named-theorem no-oracle audit, not general source behavior or HOL-axiom freedom.
Composed MCP calls retain separate operation deadlines; direct generic canonical
backend callers still need shared-admission integration, as does Lean/Coq legacy routing.
Aggregate cgroups and broader proof composition remain open. The next separate
IR query gap is normalized exact proof-key membership and reverse dependencies
with source-head and evidence-inventory-bound cursors; this milestone does not
implement that projection or close any RPI production exit.

## Normalized conditional evidence queries

The subsequent [query qualification](../../workspace/codebase-evidence-query-qualification-20261002/REPORT.md)
adds `CodebaseVerificationCatalog.query_current` and a separate closed
`codebase_verification_query` DuckDB domain on the existing owner connection.
New publications update full canonical key membership, typed reverse
dependencies and an immutable inventory in the same transaction as the existing
conditional catalog. Ordinary `lookup_current` uses this path by default.
The narrower integer evidence index retains its own schema and owner.

```python
from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
    CodebaseVerificationSelector,
)

selector = CodebaseVerificationSelector(
    dependency_kind="snapshot", dependency_value=head.snapshot_cid,
)
cursor = None
while True:
    page = catalog.query_current(
        repository, expected_head=head, selector=selector,
        page_size=16, cursor=cursor,
    )
    for entry in page.entries:
        consume_historical_projection(entry.projection)
    if page.complete:
        break
    cursor = page.next_cursor
```

The default owner admits each call, observes current source at entry and exit,
and includes admission waiting in its finite deadline. CPU, memory and I/O
pressure defer admission. Cancellation/deadline checkpoints cover inventory
derivation and native replay boundaries. The caller must handle a failed page
without claiming a complete traversal. `complete` means that this page is
terminal; only a traversal starting with no cursor and preserving every
continuation establishes complete consumption. Detached receipts include both
starting and next cursors, the selector CID, full structural head, consumed
entry IDs, sealed inventory CID and a durable monotonic evidence epoch.
Same-head additions, rebuilds and changed heads invalidate old continuations.

Selectors conjunctively match path, contract ID/authored CID, verification CID,
full canonical key ID, requested-domain ID/CID and an optional typed dependency.
Reverse kinds include `source`, `snapshot`, `manifest`, `head`, `ast`,
`ast_revision`, `verification`, `applicability`, `authored_contract`,
`lowered_contract`, `domain`, `environment`, `profile`, `compiler`,
`implementation`, `canonical_key` and the sixteen `canonical_*` dimensions.
No model dependency is invented when the producer has none. Authored and
lowered contracts remain distinct.

Existing databases with conditional records but no normalized inventory require
one explicit, resource-admitted `catalog.rebuild_current(repository,
expected_head=head)`. It replays native evidence and publishes the entire
bounded inventory atomically. Startup does not hydrate evidence, and lookup
does not silently repair missing or corrupt rows. Every query checks the
complete current-head inventory against sealed projection artifacts before
filtering, so omitted memberships cannot become a successful absence result.
Selected entries then receive the existing native artifact replay without
solver/version launches. Limits default to 64 entries per page, 131,072 keys,
262,144 dependencies and 64 MiB of inventory bytes, in addition to the existing
record/evidence/result limits. Overflow raises an error; it does not truncate.

The supervisor matcher requests at most two entries from an initial page.
Only a complete singleton reaches conditional classification; missing,
ambiguous or incomplete evidence remains unknown. Runtime requirements remain
residual and all behavioral, kernel, admission and completion authority stays
false. This is a bounded local inventory scan, not constant-time indexed
retrieval or many-core scaling qualification. DuckDB/native calls are not
preemptively interrupted, and admission/byte limits are not hard RSS limits.
DuckLake delivery, scalable retention, semantic decoding and production
planner activation remain separate work.

## Bounded conditional SMT generation

The [bounded execution qualification](../../workspace/codebase-smt-execution-qualification-20261002/REPORT.md)
adds the version-2 conditional verification and requested-domain applicability
profiles. These are the default producers. Each native Z3/CVC5 call uses the
existing bounded process runner and the producer's actual shared resource lease.
This bounded profile requires Linux resource limits; other platforms fail before
a native launch.
A fresh child admission precedes each version, verdict and applicable-artifact
phase, so external pressure can defer the next phase. One finite call deadline
covers all admissions and phases within the producer's overall deadline.
Cancellation reaches active native processes and is checked again after receipt
validation, before returning or publishing evidence.

The protocol preserves the compiled assertions and its single `check-sat`.
It first requests only the verdict, then reruns those assertions with only
`get-model` for SAT or `get-unsat-core` for UNSAT. UNKNOWN has no artifact phase.
The second verdict must agree. This avoids the errors caused by requesting both
artifacts regardless of the verdict. Nonzero exits, truncation, unexpected
stderr, failed cleanup, resource exhaustion and malformed/mismatched responses
abort production; a partial `sat` or `unsat` prefix cannot become a completed
sidecar. Failed calls expose a bounded execution receipt on the exception.
The producer preserves that first exception through the semantic pipeline's
diagnostic conversion and prevents later solver launches for the failed call.

The existing default envelope remains 5 seconds per logical backend call,
128 MiB per-process address space and a sampled 128 MiB process-tree RSS guard,
with 256 KiB output and script bounds. Version output is capped at 4 KiB and its
execution at 2 seconds within that same call budget. Each process receives a
private workspace, finite CPU/file bounds and a restricted environment. Capture
is bounded per stream; combined retained bytes are also checked. A flood is
drained/discarded until process exit, cancellation or timeout rather than killed
at the first over-limit byte. The protocol reader additionally caps text at
1 MiB, 65,536 tokens and depth 64. No limits are silently widened.

Successful version-2 observations retain actual phase scripts' hashes, argv,
integer bounds, outputs, lifecycle flags and timing. Replay validates those
bindings without launching tools, including exact equality between every phase's
input cap and the sidecar's script limit. An explicit compatibility adapter also
accepts the exact reviewed version-1 producer/dependency inventory while every
unchanged semantic dependency still matches. It preserves old CAS objects,
canonical keys and projections byte-for-byte, rejects other historical
generations, and does not claim that old executions had the new protections.

Per-process address-space enforcement and sampled process-tree RSS do not
provide a hard aggregate cgroup memory limit. Ancestry tracking covers observed
descendants, not deliberate daemon escape between samples. Parent Python RSS
and DuckDB allocations remain separate. This upgrade is confined to the private
conditional producers; generic SMT backend entry points and legacy prover
routes still need their own admission integration. Conditional mathematical
evidence remains distinct from Python runtime behavior, a kernel certificate,
model/core semantic validation, and planner admission.

## Restart recovery and unknown memory telemetry

The [restart safety qualification](../../workspace/codebase-restart-safety-qualification-20261002/REPORT.md)
adds boot identity to new shared-scheduler leases and waiters. A confirmed change
of Linux boot ID invalidates those old owners even if a PID and process start
tick are reused. Same-boot owners and independently live descendants keep their
reservations until they drain. Legacy records without usable boot identity stay
conservative; missing or malformed boot telemetry alone cannot establish death.
When a requested scheduler configuration differs, ordinary stale-owner recovery
runs before deciding whether the pool is idle enough to reopen. Active work
still prevents a capacity change.

Only explicit scheduler construction or reconfiguration can make that idle
transition. An existing facade that encounters a different saved configuration
refuses the operation before changing the file. Even telemetry reads, renewal,
release and recovery cannot silently restore a stale client's cached limits.
The client must reopen with the intended current configuration.

Known finite cgroup-v2 `memory.high` and `memory.max` constraints now require
valid, bounded usage counters at every visible ancestor. Unreadable or malformed
controls cause the existing unknown-telemetry admission backoff; they cannot be
silently discarded. Missing optional controllers and unlimited values remain
distinct from unusable finite controls. This applies to fresh child admission
as well as root requests. Healthy telemetry permits admission again after the
existing cooldown. No host-wide exhaustion is needed to test this behavior.

These scheduler/probe changes preserve the conditional producer's version-1 and
version-2 artifacts and execution schemas. The post-restart benchmark explicitly
pins the currently saved pool in both parent and fresh replay child. Its
configuration guard refuses drift under the state lock, and its accounting
distinguishes its own work from other active owners. It never resets the shared
pool or stops another workload. Boot recovery
and memory telemetry are admission protections, not aggregate cgroup enforcement.
Cgroup-v1 sampling, stricter optional CPU/PSI telemetry and kernel aggregate
limits remain separate work. Bounded query batching is described below;
authenticated sublinear index validation remains open.

## Bounded multi-selector evidence queries

`CodebaseVerificationCatalog.query_many_current` accepts an ordered, nonempty
tuple of `CodebaseVerificationQueryRequest(selector, page_size=16, cursor=None)`.
It returns an ordered tuple of the existing native query pages. The single-page
`query_current` API delegates to this path; page receipts, cursor identities and
historical proof schemas retain their existing forms.

```python
from ipfs_datasets_py.duckdb_control.codebase_verification_queries import (
    CodebaseVerificationQueryRequest, CodebaseVerificationSelector,
)

pages = catalog.query_many_current(
    repository, expected_head=head,
    requests=tuple(CodebaseVerificationQueryRequest(
        CodebaseVerificationSelector(path=path), page_size=2,
    ) for path in ("first.py", "second.py")),
)
```

One batch uses one shared resource admission and query transaction, one pair of
source observations and one complete sealed inventory validation. The integrity
scan includes unselected rows, so missing keys or changed dependency rows cannot
hide evidence. Repeated selections share native projection replay only inside
that call. Each later call validates again. A failure anywhere, including the
final source observation, withholds the whole tuple.

Defaults cap a batch at 32 requests, 1,024 total requested entries, 1 MiB of
encoded requests, 64 MiB of retained native evidence and 64 MiB of serialized
page receipts. The existing default page cap is 64. Byte ceilings must fit the
resource reservation; requests exceeding their limits fail before admission.
Large custom page sizes must also fit `max_query_batch_entries`. These admission
and retention budgets are separate from hard process or cgroup memory limits.

The supervisor's sibling `conditional_codebase_batch` module exposes
`match_conditional_codebase_requirements` for 1–32 explicit requirement envelopes.
It uses one structural source context and one native query batch for supported
requests, validates page order and shared inventory, and preserves duplicate
mathematical requests as separate requirement rows. Unsupported requests and all
runtime requirements remain in the residual ledger. Existing individual matcher
receipts are preserved, and batch results confer no planning admission or task
removal authority. This explicit API does not activate a public service path.
Raw input snapshots and prepared requests each have a 4 MiB aggregate ceiling;
the complete supervisor result is capped at 8 MiB. Inputs are detached before
decoding, and cancellation/deadlines are checked between rows and at final exit.

The [batch qualification](../../workspace/codebase-query-many-qualification-20261003/REPORT.md)
records native solver generation, individual/batch page equality, cold cursor
replay, corruption/source-race controls, and finite inventory-size benchmarks.
This amortizes the full scan across selectors; it does not make that scan
sublinear or introduce a cache across calls.

## Default direct prover admission (2026-10-03)

The canonical Lean, Rocq, Isabelle and TLC execution paths now use
`ResourceAdmittedToolRunner` by default. It joins the existing shared scheduler,
requires a finite memory budget, includes queueing and workspace preparation in
the execution deadline, and releases after bounded subprocess cleanup. Actual
parent leases can provide child reservations without charging the envelope
twice. Plain injected runners retain their caller-owned admission contract.

Lean's selected native profile explicitly limits workers and thread stacks,
separates finite virtual address space from requested sampled RSS, and records
that profile in its toolchain metadata. Isabelle retains its reviewed 3 CPU /
12 process requirement; an undersized pool refuses it without being enlarged.
The [qualification report](../../workspace/generic-prover-admission-qualification-20261003/REPORT.md)
records native fixtures, concurrency measurements, pressure tests, failed
attempts and current source hashes. Prior CodebaseIR native producer sources and
proof artifacts are preserved; this adds no source-semantics or planning authority.

Remaining resource work includes aggregate memory/PID containment, legacy SMT
and Apalache admission, whole-operation deadlines spanning setup, and supervisor
owner integration. The initial cgroup feasibility review identified a usable
user-systemd delegation but also a required startup gate, actual service-process
ownership and verified whole-cgroup drain. Killing a service launcher alone
cannot establish cleanup. No cgroup service was created for this increment.

## Public SMT admission (2026-10-03)

Public Z3/CVC5 adapters, standard registry factories and V2 execution defaults now
use the shared admitted runner. Query, applicable artifact replay and version
observation share a per-solver deadline/output budget. Both model/core requests
work without accepting failed subprocess output. Native execution accepts a
bounded single-check profile and refuses worker-setting/incremental commands.
The [qualification](../../workspace/generic-smt-admission-qualification-20261003/REPORT.md)
records real concurrent runs, cancellation, nested ownership and historical replay.

Frozen compiler/differential modules and CodebaseIR producer sources stay unchanged;
their explicit legacy APIs remain a separate admission migration. Historical
v2 receipts are replayed as historical evidence and cannot discharge successor
source claims. This increment adds no learned semantics or planner authority.

## SMT consumers and source pipeline (2026-10-03)

The verification API differential operation and classical SMT parser routes now
use admitted defaults. The public `logic.software_verification` package exposes
an admitted `SourceToVerificationPipeline` and convenience helper; the underlying
source/VC/compiler module remains byte-identical for historical replay. Public
`logic.backends.smt` differential helpers likewise preserve typed reports while
selecting admitted defaults. Explicit backend injection keeps caller ownership.

The [consumer qualification](../../workspace/smt-consumer-admission-qualification-20261003/REPORT.md)
covers native source-to-solver execution and compatibility. Per-solver budgets
remain separate across obligations and differential participants. Direct legacy
modules and the self-hashed security header derivation still need migration;
this changes neither source semantics nor planner admission.

## Aggregate proving operation control (2026-10-03)

Public differential, source-pipeline and verification-API operations now share a
default aggregate deadline across their solver work and return validation. It
defaults to the effective bounds timeout and can be set with `operation_timeout_ms`;
`cancellation` revokes the operation. Nested scopes cannot extend a parent budget.
Interrupted operations return no partial proof or counterexample result, including
when the legacy pipeline catches an inner exception. Native cleanup precedes
lease release; arbitrary Python callbacks are checked cooperatively.

The [qualification](../../workspace/smt-operation-control-qualification-20261003/REPORT.md)
records current runtime source evolution separately from unchanged historical
CodebaseIR semantic source pins and immutable proof artifacts. This improves
execution control without changing translation, proof authority or source
eligibility. V2 aggregate control is covered by the subsequent increment below.
Remaining legacy/header operations, hard containment and supervisor ownership
still need integration.

## V2 execution and replay operation control (2026-10-03)

Standalone V2 execution now applies a default aggregate deadline and cancellation
scope across normalization, compilation, solver participants, automatic primary
replay and evidence construction. Explicit replay includes its nested execution
and final receipt. Late results and matched replay receipts are withheld through
typed operation exceptions. Runtime controls remain outside serialized requests
and evidence; minimal bounds/control coercion precedes the cooperative scope.

The [V2 qualification](../../workspace/smt-v2-operation-control-qualification-20261003/REPORT.md)
records the V2 runtime preimage and changed source separately from frozen
CodebaseIR semantic producers, and compares successful wire records with the
original implementation. Native default solvers remain under shared admission.
Legacy/header/setup integration, hard aggregate containment and supervisor
ownership remain open; this adds no source-semantics or planner authority.

## Default JVM identity probe admission (2026-10-03)

The Java identity probe used by default TLC/Apalache construction now joins
shared admission with finite JVM memory/output/CPU settings, deadline and
cancellation handling. Explicit probe APIs accept actual parent ownership and
inherit an active proving-operation budget. Local probe failure stays unusable;
an interrupted enclosing operation propagates its typed stop after cleanup.
The [qualification](../../workspace/jvm-probe-admission-qualification-20261003/REPORT.md) distinguishes native Java identity observations
from pressure/deadline controls. Existing constructor setup still has a separate
root reservation from its later model-check runner. Installer/tool-specific
probes, setup-to-proof ownership and aggregate containment remain open. Frozen
CodebaseIR producers, historical receipts and proof authority stay unchanged.

## Admitted state-model startup probes (2026-10-03)

TLC help and Apalache version checks used during installation now join shared
admission with finite JVM and output limits. A single local deadline includes
TLC fallback and final parsing; actual parent leases and cancellation can be
passed to the probe APIs. Interrupted or incomplete output cannot establish tool
usability, including TLC help whose clean exit code is 1. Exact managed TLC
launchers are expanded into truthful bounded Java commands without rewriting
launcher bytes or manifests. The [qualification](../../workspace/state-model-probe-admission-qualification-20261003/REPORT.md) records native startup
observations separately from proof/model-check authority. Whole-install budgets,
setup-to-proof ownership and model-runner lifecycle fixes remain open; frozen
CodebaseIR producers and historical evidence are unchanged.

## TLA outcome integrity increment (2026-10-03)

TLC and Apalache model-runner results now reject incomplete native lifecycles
before inspecting success or counterexample markers. Truncation, resource/workspace
limits, incomplete cleanup, signal exits and process errors cannot become bounded
conclusions. Combined UTF-8 stdout and stderr must also fit the accepted output
budget. Unsafe model runs do not launch a follow-up version process. Unsafe
version execution also revokes the local conclusion; a clean unsupported version
exit only makes descriptive version metadata unavailable. Valid TLC invariant
violations with exit 12 and complete TLC help with exit 1 remain supported.

Cancellation and the existing check deadline are rechecked through trace parsing,
source-map replay and final outcome construction. A late stop clears both the
receipt counterexample and the result witness. This control is local to each call;
Python parsing and callbacks are checked cooperatively. See the [qualification](../../workspace/tla-outcome-integrity-qualification-20261003/REPORT.md)
for regression coverage, admitted native TLC checks and retained wire comparisons.

This closes the interrupted-counterexample classification gap identified above.
Constructor setup, compilation before `check()`, later TLA V2 evidence construction
and installation still need unified ownership/deadlines. Native Apalache model
execution admission, hard aggregate memory/PID containment and supervisor ownership
remain open. This adds no source semantics, training eligibility or planner authority.

The final source-preservation audit found independent changes to
`software_verification/pipeline.py` and `software_verification/source_adapters.py`
during qualification. Those changes are retained without adoption or reversal.
The joined tests and native benchmark bind their actual stable source generation;
historical source preservation remains unresolved. Prior qualification artifacts
and the original proof cache remain byte-identical. See the linked report's drift
record before relying on historical compatibility.

## Source mirroring and proof-generation compatibility (2026-10-03)

The public admitted source pipeline, its convenience helper and the source adapter
object accept the per-call `mirror` option. `mirror=False` suppresses the optional
supervisor's metadata-mirroring attempt while retaining source evidence and
translation. The default remains enabled and preserves calls to legacy supervisors.
Only actual booleans are accepted. A legacy supervisor without the keyword
fails without retrying a call that could mirror data. The option does not
control arbitrary import side effects or make default best-effort mirroring durable.

The [qualification](../../workspace/source-mirroring-compatibility-qualification-20261003/REPORT.md) reviews the prior pipeline,
source-adapter and integer-profile mirroring additions and completes the public
routes. Historical source bytes remain a distinct generation. Identical selected
source/ProgramIR/VC/SMT encodings do not authorize reuse of old receipts under new
implementation hashes. Existing exact-generation validators and legacy compatibility
tables remain unchanged: stale records are rejected, while fresh conditional
verification/applicability records bind the actual current module inventory and
receive new cache keys. Prior database, CAS objects and qualification artifacts
remain immutable. The expanded inventory includes the integer-profile dependency
that earlier runtime manifests omitted.

This resolves the previously unreviewed mirroring change through explicit generation
qualification, not by declaring old source pins current. Fresh observations retain
conditional authority. This increment does not implement training or activate
planner execution. Whole-install budgets, Apalache admission, hard aggregate containment,
supervisor scheduling ownership, DuckLake delivery and learned semantic IR remain
separate work.

Provider selection is explicit in the qualification. The default test environment
resolves an older nested supervisor that lacks the mirroring keyword and correctly
refuses `mirror=False`. Positive parser tests inject the reviewed sibling parser
and record its actual supporting dependencies; they do not silently upgrade the
installed provider. `include_supervisor_evidence=False` supports native-only
verification without that optional dependency. Production provider-version
selection and negotiation remain open.

## Optional program-AST provider capabilities (2026-10-03)

The source adapter now checks the selected optional provider before running its
language detector or parser when `mirror=False` is requested. The provider must
explicitly declare a keyword-capable `mirror` parameter. Legacy signatures,
`**kwargs` alone, positional-only parameters and uninspectable signatures do not
establish that capability. A `ProgramASTProviderCompatibilityError` (also a
`TypeError`) explains the incompatibility without a trial call or retry. Default
and explicit-enabled calls retain their previous behavior.

`inspect_program_ast_provider()` in `software_verification.source_adapters`
reports the provider selected by normal imports and its advertised capability.
Inspection may import the optional package, but does not call the detector or
parser. The diagnostic is separate from source/proof result encodings and does
not attest a provider's behavior or absence of arbitrary side effects. Capability
checks use the callable pair captured for that request, without a global support
cache, provider replacement or changes to import paths. Native-only execution
continues to use `include_supervisor_evidence=False`.

The [qualification](../../workspace/program-ast-provider-qualification-20261003/REPORT.md) records selected regression tests,
separate-process checks of the actual nested and sibling providers, and fresh
conditional proof generation under the changed source hash. Prior evidence remains
immutable; no compatibility aliases or authority promotion are introduced.
Runtime capability negotiation is implemented within this scope. Installing or
selecting a compatible provider remains deployment work, and the older nested
provider continues to reject the opt-out. Whole-install budgets, hard aggregate
containment, supervisor scheduling ownership, authenticated index scaling,
DuckLake, learned semantic IR and production planner admission remain open.

## Bundled program-AST provider deployment (2026-10-03)

The bundled source-tree supervisor now implements the reviewed per-call `mirror`
control already present in the sibling checkout. Normal imports from the datasets
repository accept `mirror=False` while retaining source evidence and translation.
The default remains enabled. Exact booleans are validated before detection or
parsing, and the opt-out applies to every return path, including malformed input,
unsupported languages, source-size rejection and fact truncation. Other provider
APIs and their mirroring policies are unchanged.

This is a narrow source-tree backport, with the old file preserved and the result
compared against the reviewed sibling implementation. It does not change import
selection or upgrade an external installation. The capability diagnostic still
rejects legacy or ambiguous providers before executing callbacks. The
[qualification](../../workspace/bundled-program-ast-provider-qualification-20261003/REPORT.md) records regression tests and coherent cold
processes using both actual source-tree providers with an in-memory metadata sink.
Real metadata persistence remains outside that test scope.

The closed native-only proof producers omit optional supervisor evidence; their
74 recorded runtime sources and 27/29 producer dependency inventories remain
unchanged. Existing conditional receipts therefore retain their source bindings,
cache keys and CIDs, and are checked through solver-free current-head queries and
intent matching against a copied catalog with its original CAS binding. No proof
hashes are aliased, old artifacts rewritten or authority flags promoted. The
earlier 60-phase native benchmark remains historical evidence; this increment
does not count or repeat those solver executions.

Deploying compatible external packages remains separate from this bundled-checkout
fix. Whole-install budgets, setup-to-proof ownership, Apalache admission, hard
aggregate containment, supervisor scheduling, authenticated index scaling, DuckLake,
learned semantic IR and production planner admission remain open.

## TLA aggregate operation control (2026-10-03)

TLA `compile_and_check` and `run`, plus the V2 execution engine and helpers, now
use a shared cooperative operation deadline. The default is the request's timeout
bound (30 seconds where no request supplies one); `operation_timeout_ms` provides
an explicit aggregate override. A caller cancellation signal and any enclosing
proof operation also apply. Compilation, request normalization, selected-provider
setup, model checking, descriptive version probes and final evidence publication
are checked under that operation. Interrupted aggregate calls raise the existing
typed proof-operation exception without returning partial or late conclusions.
Original request bounds and evidence schemas retain their meanings.

Native qualification also exposed oversized TLC help metadata at the V2 boundary.
V2 now summarizes a complete bounded provider version banner, or records `unknown`
when none is available. The raw backend receipt remains intact.

V2 engines construct default provider backends lazily, so a TLC request need not
probe the unused Apalache provider. The selected JVM validation inherits the
active deadline. Low-level `check` retains its original standalone result behavior
and consumes a tighter ambient operation when present. Existing shared resource
admission remains responsible for each native phase; this change does not add a
root reservation across the whole operation or transfer a caller-owned setup lease.

The [qualification](../../workspace/tla-operation-control-qualification-20261003/REPORT.md) records regression and bounded native
TLC tests, source identities, interruption controls and process cleanup. Apalache
aggregate behavior is covered with controlled fixtures; its native process profile
and admission remain separate work. Direct standalone backend/facade construction
retains its separate support-probe budget. Python callbacks and optional lazy
installation are checked before and after each call. Installer internals, including
locks, downloads and extraction, are not newly checkpointed or forcibly preempted
and still require whole-install budgets.

Stored proof evidence and prior qualifications remain immutable. This increment
does not activate training or production planner admission. Hard aggregate cgroup
containment, supervisor scheduling ownership, authenticated index scaling, DuckLake
and learned semantic IR retain their acceptance gates.

## Apalache default execution admission (2026-10-03)

Apalache model checks and descriptive version commands now use shared resource
admission by default. Each phase reserves one CPU, three process slots for the
reviewed launcher helpers, and the caller's requested resident-memory bound.
The reviewed solver loads Z3 through JNI inside the JVM; no separate Z3 executable
is required by that profile. Shared admission applies existing pressure backoff
before launch. Cancellation and aggregate operation deadlines remain active
during native execution.

The managed profile limits the Java heap to half the requested RSS budget,
rounded down to whole MiB, with serial GC and an active-processor setting
matched to the admitted CPU reservation.
It requires at least 256 MiB requested RSS without increasing that request.
Native-library extraction stays in the private workspace under explicit 64-MiB
per-file and 128-MiB workspace limits. The existing finite address-space bound
remains separate from RSS. These reservations and sampled guards do not provide
hard aggregate cgroup CPU, memory or PID containment.

Managed execution isolates Java user configuration, supplies its own empty
Apalache runtime configuration and routes output to a fixed private directory.
For the reviewed stock launcher and default environment, this prevents ambient
configuration from changing the solver defaults. Arbitrary custom launchers and
custom base environments remain caller-trusted.
An explicitly admitted runner needs at least three process slots and receives
the managed profile; an injected plain runner keeps its caller-owned contract.
TLC's execution profile and the request/receipt schemas remain unchanged.

The preceding Apalache qualification recorded a separate registry defect
(repaired by the subsequent registry increment below):
its protocol enum has no `TIMEOUT` member, so a completed delegate can become
an `ERROR` receipt. The new regression records that existing failure explicitly;
native success in this qualification covers the V2 engine and helper routes.
Fixing registry conversion without promoting bounded or candidate evidence
remains a follow-up.

The [qualification](../../workspace/apalache-execution-admission-qualification-20261003/REPORT.md)
records private-scheduler pressure tests, real installed-tool runs, selected source
and tool identities, and cleanup. Native violations retain their raw Apalache
witness. Its `State0 ==` output is not parsed into TLC-style `State 1:` blocks;
this increment does not claim a parsed or semantically replayed Apalache trace.
The legacy `replayed` flag does not establish replay when `states` is empty.

The accepted qualification passed 1,708 selected regression tests, including 47
new admission tests, and 60 native phases across a smoke run and a full batch.
The full batch took 23.418 seconds. Requested caller widths of one, two and four
all dispatched one operation at a time under the unchanged four-process pool;
these measurements do not establish many-core speedup. Earlier capacity-wait
and resource-limit attempts remain recorded separately from accepted results.

Earlier proof receipts and qualifications remain immutable. Whole-install budgets,
setup-to-proof parent ownership, standalone facade operation controls, Apalache
trace parsing, hard aggregate containment, supervisor scheduling ownership,
DuckLake scaling, learned semantic IR and production planner admission remain
separate acceptance work.

## Foreign solver outcomes in the generic registry (2026-10-03)

Validation passed: **1,914 selected regression tests**, including **82 new
foreign-outcome cases**, and two real Apalache registry cases in **3.54 seconds**.
The accepted run contains six admitted native phases with complete owned-resource
cleanup. An earlier three-phase attempt is retained separately; its fixture
assertion exposed the artifact-decoding gap described below. All 1,341 artifact
bodies from 16 earlier qualifications remain unchanged. These serial cases
qualify result conversion and resource lifecycle, with no many-core throughput claim.

The generic registry conversion now uses its own protocol status vocabulary.
A completed foreign adapter outcome produces a bound `UNKNOWN` result and retains
the original typed result, status and authority as descriptive payload. A tool's
`proved`, `satisfied`, `candidate` or reconstruction status does not become a
positive generic protocol conclusion. The existing protocol-pair path remains
unchanged. Provider-specific typed and V2 routes retain their scoped semantics.

Timeout, unavailability, cancellation and malformed/unsupported outcomes retain
explicit execution classifications. The normalizer records its authority limit
in diagnostics. This repairs the enum mismatch recorded in the preceding Apalache
qualification while preserving the original bounded model-check evidence.

The [qualification](../../workspace/registry-foreign-outcome-qualification-20261003/REPORT.md) records regression tests,
actual installed Apalache execution through the registry, exact source and tool
identities, and preservation of earlier receipts. Native qualification supplies
an explicit outer operation budget in the harness; it does not add automatic
aggregate setup budgeting to the production registry.

At the registry qualification above, the TLA payload reader substituted the
compiler's default bounds and dropped source-map/loss metadata (repaired below). The native
conversion qualification uses a matching default 64-step fixture; general
serialized-artifact round-tripping remains a separate gap. The retained initial
attempt exposes the three-step payload becoming a 64-step checker command.

Python getters and serializers remain cooperative callbacks. The output cap
bounds the serialized payload; it does not hard-limit callback memory or runtime.
Extremely small output budgets can still fail in the existing terminal helper
when even its fallback envelope cannot fit.

This increment changes result conversion. Apalache trace parsing and its legacy
replay label, whole-install budgets, hard aggregate resource containment, wider
concurrency qualification, learned CodebaseIR and production planner admission
remain separate work. Earlier proof-cache producer inventories stay unchanged.


## Serialized TLA artifact preservation (2026-10-03)

Validation passed on the first attempts: **2,015 selected regression tests**,
including **101 new artifact cases**, and **531 focused tests**. Two installed
Apalache registry cases completed in **3.47 seconds** with six admitted native
phases, exact three-step artifact preservation and complete owned-resource
cleanup. All 1,420 artifact bodies from 17 previous qualifications remain
unchanged. Focused and joined test counts overlap and are not additive.

The typed runner, generic registry route and V2 mapping route now share artifact
payload decoding. Full generated records preserve their declared compilation
bounds, source maps, projection losses, property lists, translator/version data,
and exact model/configuration text. Model, configuration and supplied artifact
digests are checked before model checking. Canonical records with malformed or
missing fields, unsupported versions or mismatched digests are rejected instead
of being silently repaired. Use the complete text-bearing `artifacts.to_dict()`
record when transferring compiled artifacts between these APIs.
The standalone reader also accepts an omitted outer artifact digest and
recomputes it; V2 callers should keep that digest because the existing compact
request identity reads the supplied value. That identity scheme is unchanged.

Minimal legacy model/configuration payloads keep their separate default-bounds
path. Adding bounds, source-map/loss or canonical identity fields requires a
complete canonical record. This avoids silently discarding declared semantics.
Deserialization establishes record consistency; it does not independently verify
the supplied source mapping or translation claims. Existing request identity,
authority classification, resource admission and operation-budget behavior remain
unchanged. V2 capability/setup work can precede artifact rejection.

The [qualification](../../workspace/tla-artifact-payload-qualification-20261003/REPORT.md) records exact round trips, malformed-input rejection,
and installed Apalache execution with a non-default three-step bound and nonempty
source-map/loss metadata. The native cases retain generic `UNKNOWN` results with
original bounded checker evidence. The harness supplies its explicit 30-second
outer operation budget; production aggregate setup budgeting is unchanged.

Apalache's raw counterexample parser/replay-label gap, whole-install cancellation,
hard aggregate resource containment, many-core scaling, learned IR and planner
acceptance remain separate work.


## Apalache counterexample parsing and structural validation (2026-10-03)

The counterexample reader recognizes Apalache's `State0 == ...` definitions as
well as TLC's `State 1:` blocks. It preserves the raw trace and original state
labels while exposing positive state indexes through the existing schema.
Assignment values remain text; parsing does not evaluate TLA expressions.

The legacy `replayed` flag now reports successful structural source-symbol
validation only. Empty, malformed, incomplete or unmapped traces cannot report a
successful replay. Parser diagnostics survive supplemental counterexample-file
handling, and V2 no longer promotes a raw-only trace into `REPLAYED`. A structural
match does not independently check transitions, the violated invariant, fairness,
liveness or the truth of supplied source-map metadata.

The [qualification](../../workspace/tla-counterexample-replay-qualification-20261003/REPORT.md) records regression coverage and installed Apalache
execution through the default generic registry. Its invalid three-step model
retained parsed values 0, 1 and 2, its original raw witness, the complete artifact
and bounded checker evidence. Generic conclusions remain `UNKNOWN`. The harness
keeps the existing shared-pool guard and finite resource profiles, with its own
explicit 30-second outer operation budget per serial case.

Validation passed **2,089 selected tests**, including **74 new cases**; the focused
subset passed 605 tests. Fifteen legacy native tests remain explicitly deselected.
The two real Apalache cases completed in **4.230 seconds**, with six admitted
native phases, cleaned workspaces and no remaining owned leases or waiters.
An initial duplicate-diagnostic failure with long source identifiers was fixed;
its source snapshot and failed run remain in the qualification alongside the
passing rerun. All 1,509 prior artifact bodies from 18 qualifications are unchanged.

Parsing is bounded to 512 states, 262,144 characters and nesting depth 128.
Unsupported or incomplete syntax keeps raw evidence and prevents structural
replay; the implementation does not evaluate arbitrary TLA expressions.

Semantic counterexample replay, production registry setup budgeting, whole-install
cancellation, hard aggregate resource containment, many-core scaling, learned IR
and planner acceptance remain separate work. Earlier qualification artifacts keep
their historical zero-state/legacy-flag observations unchanged.


## Automatic generic registry operation budgets (2026-10-03)

Generic registry execution and direct callable/lazy wrappers now use one
cooperative operation deadline by default. It covers setup, availability checks,
compilation, execution and result conversion. The default is the request timeout,
capped at the operation helper's maximum; `operation_timeout_ms` can tighten it.
Nested scopes inherit the earliest deadline. The original request, bounds and
digests remain unchanged. `cancellation` joins any inherited cancellation signal.

An observed interruption produces a bound `TIMED_OUT` or `CANCELLED` attempt with
an `UNKNOWN` result. A late Python callback cannot publish a conclusive result.
A stopped parent scope remains stopped even if a nested adapter returns a terminal
pair or a cancellation event is later cleared. Interrupted lazy initialization
can be retried by a fresh call; concurrent callers wait under their own controls
and cannot observe a partially initialized delegate.

The [qualification](../../workspace/registry-operation-budget-qualification-20261003/REPORT.md) records tests and installed Apalache execution through
the default registry without a benchmark-owned outer scope. Existing shared-pool
policy, real pressure sampling and per-phase resource profiles remain in use.

Validation passed on the first runs: **2,215 selected tests**, including **126 new
cases**, and **747 focused tests**. Fifteen legacy native tests remain explicitly
deselected. The two real Apalache cases completed in **3.917 seconds** with six
admitted native phases. Recorded factory/setup/model/version observations share
one production-created deadline per case; all workspaces cleaned up and no owned
leases or waiters remained. All 1,618 prior artifact bodies from 19 qualifications
are unchanged. Focused and selected counts overlap and are not additive.

This is cooperative control at Python callback boundaries. The admitted SMT/TLA
paths consume the remaining deadline; other native adapters still require their
own propagation audit. Explicit standalone availability probes, hard callback
preemption, whole-installer cancellation, hard aggregate containment and many-core
scaling remain separate work. The prior qualifications' benchmark-owned scopes
remain unchanged historical evidence.


## Ambient budgets for admitted native execution (2026-10-03)

`ResourceAdmittedToolRunner` now inherits the current proof operation's deadline
and cancellation signal. Registry-created budgets reach existing admitted kernel,
SMT, TLA and JVM launches without each adapter forwarding a new argument. The
effective wall deadline is the earlier of the tool request and ambient deadline.
Admission and workspace preparation consume that same budget; an existing CPU
ceiling is tightened to remaining time when an ambient operation is present.
Original requests, memory/output/storage limits and reservation profiles remain
unchanged. CPU limits retain their operating-system rounding behavior.

Stops are checked before scheduler resolution, during queued admission, before
native launch, after output/workspace cleanup and after lease release. The final
check uses caller/operation signals rather than the released lease. Observed stops
are sticky, and late results retain their raw evidence and existing failure flags
while becoming non-successful. An ambient timeout may accompany a native
cancellation flag because the process polls a stop signal. The registry/outer
scope retains the logical interruption reason. Runner-local stops do not revoke
a separate, still-live ambient operation. Cleanup failures continue to propagate.

The [qualification](../../workspace/native-operation-inheritance-qualification-20261003/REPORT.md) records actual Lean and Rocq positive/negative registry
cases plus separate Python transport timeout/cancellation controls. Python controls
exercise the admitted transport; they are not native solver cancellation proofs.
The benchmark retains the saved shared-pool guard and real pressure sampler.

Validation passed: **2,314 joined tests**, retaining all 2,215 prior cases and
adding 58 new inheritance cases plus 41 previously unselected kernel cases;
**818 focused tests** also passed. These populations overlap. Fifteen legacy
native cases remain deselected. Four real Lean/Rocq cases and two owned Python
transport controls passed in **2.270 seconds** with six admitted launches. The
one-second deadline control completed in 1.028 seconds; the cancellation control
completed in 0.187 seconds. All owned PIDs/workspaces cleaned up and owned leases
and waiters drained. This serial benchmark does not measure parallel speedup.

The qualification retains all attempts: nine initial failures were fixed by
aligning three synthetic-clock fixtures, with every assertion unchanged. A first
native attempt was rejected by the source-import guard before pool access or
solver execution; a one-line benchmark entry-point correction selects the sibling
checkout consistently, and static preflight now checks that ordering. Production
code was unchanged during those corrections. All 1,708 artifact bodies from the
20 prior qualifications remain unchanged, alongside their reports and manifests.

This increment changes admitted launches. ATP, ProVerif, Tamarin and hyperproperty
defaults still using plain runners need a separate admission/profile migration.
Explicit plain injected runners retain caller-owned behavior. Native Isabelle
execution, whole-install cancellation, hard aggregate containment, semantic trace
replay and many-core scaling are not established by this qualification. Python
callbacks remain cooperative and cleanup may finish after a deadline expires.


## Default resource admission for Vampire and E (2026-10-03)

Canonical Vampire/E adapters and the V2 live-solver fallback now select
`ResourceAdmittedToolRunner` when no runner is supplied. Their finite request
memory, wall/CPU, output and workspace limits feed the existing shared admission
policy. Registry operation deadlines and cancellation reach the native lifecycle
automatically. Explicit runners keep caller-owned behavior; hermetic V2 mode
still requires an injected fixture runner. Discovery remains inert.

Vampire's command now requests `--output_mode szs --proof tptp`; the former
`--output_mode=tptp` value is unsupported by the installed 5.0.1 release.
Every option/value pair, including `--time_limit`, uses separate argv tokens.
The [tagged options source](https://raw.githubusercontent.com/vprover/vampire/v5.0.1/Shell/Options.cpp)
separates the status-output mode from the proof format. One existing regression
assertion was corrected to require both option/value pairs; other assertions and
case identities are retained.

Unsafe lifecycle results are rejected before SZS parsing and proof/model
reconstruction: workspace-limit failures, process errors, unclean cleanup,
terminated trees and combined UTF-8 output overruns return `ERROR`. Process
metadata now retains the tree/workspace flags and termination reason. Existing
cancellation/timeout precedence remains intact.

The qualification covers isolated pressure/backoff fixtures and four serial real
ATP calls with the installed Vampire/E binaries. It does not establish native V2
execution, many-core speedup or hard aggregate containment. Unreconstructed ATP
success remains candidate evidence. E's existing nonzero satisfiable exit remains
an error at the typed adapter boundary; the raw SZS result is retained.

See the [qualification](../../workspace/atp-default-admission-qualification-20261003/REPORT.md) for exact scope and retained evidence.

Next runner migrations require separate checks: ProVerif already supplies finite
profiles; Tamarin needs a reviewed Haskell/Maude process profile; Hyper requires
finite memory/CPU limits, guarded version probing and complete failure handling.

Standalone V2 parsing/reconstruction still lacks an aggregate operation budget;
its inherited default version label is not installed-version verification.
One CPU/process reservation is an estimate, not an enforced process-tree ceiling.

Registry requests should bind `requested_backend_id="eprover"`; selection may use
`backend_id="e"`. An alias stored in the bound request still conflicts with the
canonical attempt identity when constructing the result. That existing alias
compatibility gap remains open.

Validation passed: **2,408 joined tests**, including all 2,314 previous cases,
**53 new ATP admission cases** and **41 additionally selected existing ATP cases**;
**370 focused tests** also passed. These populations overlap. Fifteen legacy
native cases remain deselected. The four actual ATP cases completed in
**0.344 seconds**, each with one CPU/process reservation, 128 MiB address-space
bound and a five-second request budget reduced by preceding registry work.
All four workspaces and owned PIDs cleaned up; owned leases and waiters drained.
Three results remained unverified candidates. E's satisfiable case retained its
raw SZS result and exit 1 while returning the documented typed error.

All attempts are retained, including the initial test-fixture failures, the
superseded static preflight, and Vampire's first native argument rejection.
The final tests assert exact separate option/value tokens. All **1,902 prior
artifact bodies from 21 qualifications**, and their reports/manifests, remain
unchanged. This serial benchmark establishes neither many-core speedup nor
native cancellation/stress behavior of these two solvers.


## E satisfiable exit normalization (2026-10-03)

The E adapter now recognizes integer exit code 1 with an exact, unambiguous
`Satisfiable` or `CounterSatisfiable` SZS status. E 3.2.5 documents this
[exit convention](https://raw.githubusercontent.com/eprover/eprover/E-3.2.5/BASICS/clb_error.h)
and uses it in its [satisfiable return path](https://raw.githubusercontent.com/eprover/eprover/E-3.2.5/PROVER/eprover.c).
Lifecycle failures and combined UTF-8 output overruns are still rejected before
parsing. Other E exits, inconsistent statuses and Vampire nonzero exits remain
errors. Raw exit codes, termination reasons and request/source bindings survive
normalization. No executable-name heuristic is used.

Default direct, registry and V2 routes retain unvalidated candidate authority;
only an explicitly supplied validator can establish the existing validated-model
contract. E exit 1 cannot establish a proof or bypass reconstruction. This closes
the exit-normalization gap recorded in the preceding ATP admission increment.
See the [qualification](../../workspace/eprover-satisfiable-exit-qualification-20261003/REPORT.md)
for tests and native measurements.

ProVerif is the next runner migration: its finite profile can use shared admission,
but its result handling first needs workspace/error/cleanup and combined-output
gates. Tamarin/Haskell/Maude and Hyper profiles remain separate work. Registry
alias-valued request bindings, standalone V2 aggregate budgets, native ATP
cancellation, hard aggregate containment and many-core scaling remain open.


Validation passed: **2,458 joined tests**, retaining all 2,408 previous cases and
adding **50 new exit-status cases**; **420 focused tests** also passed. Counts
overlap. Fifteen legacy native cases remain deselected. Six real serial ATP
cases (UNSAT, SAT and counter-SAT for both providers) completed in **0.474 seconds**
(**0.816 seconds** including the benchmark wrapper). All six results remained
candidates with generic `UNKNOWN`; both E model cases preserved raw exit 1 and
`nonzero_exit`. Each used one CPU/process reservation, 128 MiB address-space
bound, five-second request budget, 64 KiB input/output and 128 KiB workspace
limits. Every owned process/workspace cleaned up and owned leases/waiters drained;
shared policy and real pressure sampling were unchanged.

The current qualification pins 98 native and 185 selected source files and
preserves all **2,109 artifact bodies from 22 prior qualifications**, alongside
their reports and manifests. The only existing regression adjustment permits
bounded status parsing for the E exit-1/Theorem rejection fixture; its error and
no-callback assertions remain intact. This serial benchmark measures integration
latency; native V2, solver stress/cancellation, many-core speedup and hard aggregate
OOM/PID containment are not established by this increment.


## ProVerif default admission and lifecycle checks (2026-10-04)

ProVerif now selects `ResourceAdmittedToolRunner` when the caller supplies no
runner. The default registry and protocol V2 paths inherit that choice. Explicit
runners remain caller-owned, including falsey runner instances. Construction,
capability discovery and default toolchain metadata do not acquire resources or
start version/OPAM probes. The existing finite wall/CPU, address-space, input,
output and workspace limits feed shared resource admission and pressure backoff.

Native output reaches claim classification only after a clean lifecycle and an
integer zero exit status. Workspace limits, process errors, unclean cleanup,
terminated process trees and combined UTF-8 overruns now stop interpretation.
Unavailable, cancellation and timeout precedence is retained. Actual executions
also retain process flags, exit codes and stream digests in typed metadata;
unsafe output cannot establish protocol security or an attack receipt.

The [qualification](../../workspace/proverif-default-admission-qualification-20261004/REPORT.md)
records default-path tests and native admission checks. The native profile uses
the existing installed ProVerif ELF directly, with no compiler, installer or
probe substitution. Default toolchain labels remain descriptive metadata.

Query/result correspondence is a separate open gap: a secrecy query such as
`attacker(s)` may be reported as `not attacker(s[])`, while the current
parser compares literal normalized strings. Fixing this requires explicit query
identity and polarity handling, with tests that reject foreign or ambiguous
claim results. Existing attack replay emits normalized step tokens and may use
a false-result marker; it does not establish semantic trace execution. The
admission increment leaves these semantics unchanged.

Tamarin and Hyper still need reviewed default admission profiles. Standalone
protocol V2 aggregate budgets, native cancellation/stress, many-core scaling and
hard aggregate memory/PID containment remain separate work. One CPU/process
reservation remains an estimate of demand, not a process-tree ceiling.


Validation passed: **2,556 joined tests**, retaining all 2,458 previous cases and
adding **59 new admission/lifecycle cases** plus **39 existing protocol adapter/V2
cases**; **374 focused tests** also passed. These populations overlap. Fifteen
legacy native cases remain deselected. Existing test sources are unchanged.
The new cases exercise CPU/RAM/PID and unknown-telemetry backoff, recovery,
queued deadline/cancellation, reservation ownership and rejection before parsing.

Two actual serial ProVerif calls passed their admission/lifecycle assertions in
**0.192 seconds** (**0.565 seconds** including the benchmark wrapper). They
reported `not attacker(s[])` as true for an undisclosed private constant and
false after public disclosure. Both canonical and generic results remained
`UNKNOWN`, with the requested `attacker(s)` claim unmatched and quarantined;
this benchmark does not establish working native claim normalization. Each call
used one CPU/process reservation, 128 MiB address-space, a five-second request
budget, 64 KiB input/output and 128 KiB workspace limits. Owned PIDs/workspaces
cleaned up and leases/waiters drained; saved policy and real sampling were retained.

The first native attempt used the reserved identifier `secret` and exited 2.
The fixture now uses `s`, as in installed release examples. That failed run,
its reviewed source generation and every test attempt are retained separately;
production and tests did not change during the fixture correction. The final
qualification pins 107 native/dependency and 194 selected sources and preserves
all **2,209 artifact bodies from 23 prior qualifications**, including their reports
and manifests. Native V2, native cancellation/stress, many-core speedup and hard
aggregate containment remain unqualified by this increment.


## ProVerif source-qualified secrecy binding — 2026-10-04

[Qualification report](../../workspace/proverif-query-binding-qualification-20261004/REPORT.md).

The canonical ProVerif backend now binds native `not attacker(s[])` results
to the requested `attacker(s)` claim when the exact compiled source has a
complete, unambiguous population of ground secrecy queries over declared free
names. The supported source shape is single-name `bitstring`/`channel` free
declarations, followed by attacker queries before `process`, with whitespace and
nested comments. Successful native parsing/execution remains required; the
binding helper does not validate reserved words or process-body syntax.

Identifiers remain case-sensitive, empty name brackets have a specific meaning,
and verdicts are not inverted. Missing, foreign or ambiguous results remain
nonconclusive; duplicate verdicts are deduplicated and conflicting verdicts are
quarantined. Native `cannot be proved` output is recognized. Other source/query
forms retain legacy exact matching and are outside this native qualification.

A qualified true result produces an accepted `SECURE` protocol receipt with
`PROTOCOL` authority and a `BOUNDED` symbolic ceiling. A qualified false result
retains its native query, source claim ID and false verdict, with no attack trace
or replay witness. Disclosed-secret results remain `UNKNOWN` with
`malformed_output` quarantine; mixed true/false results remain `UNKNOWN` with
`disagreement` quarantine. Generic theorem projections remain `UNKNOWN` in every
case. Legacy synthetic trace behavior is unchanged and does not establish
semantic attack replay.

Validation passed **2,612 joined tests**, retaining all 2,556 previous
cases and adding **56 query-binding cases**; **430 focused tests** passed. These
populations overlap. Fifteen legacy native cases remain deselected. Controlled
tests exercise direct, registry and protocol V2 paths using private admission
state and retained native stdout. One existing synthetic disagreement fixture
was corrected to match its submitted queries, with stronger claim-ID assertions.
The initial 429-pass/one-failure run and static evidence remain preserved.

Three actual serial ProVerif cases passed in **0.275 seconds**
(**0.615 seconds** including the wrapper): private `s`, disclosed
`s`, and mixed private `s`/`t` with only `s` disclosed. Their typed statuses were
`SECURE`, `UNKNOWN`, `UNKNOWN`; every generic result was `UNKNOWN`. Each launch
retained the default admitted runner and registry budget, one CPU/process
reservation, 128-MiB address-space bound, five-second request, 64-KiB input/output
and 128-KiB workspace bounds. Real sampling and the exact saved policy remained
in use; owned leases/waiters drained and workspaces were cleaned.

The qualification pins 109 native/dependency and 196 selected sources and
preserves **2,394 artifact bodies from 24 prior qualifications**, plus their
reports and manifests. The preservation guard detected an independently changed
resource scheduler before native execution. Its current exact body was captured
and separately reviewed; accepted static/tests/native all use that generation.
Earlier scheduler bodies were unavailable, so no historical diff or behavioral
equivalence is claimed. The refused capture and initial diagnostic generation
remain in the report.

Remaining work includes broader query/compiler handling, validated semantic
attack reconstruction, verified toolchain identity, standalone protocol V2
aggregate budgeting, and reviewed Tamarin/Hyper defaults. This increment does
not establish native V2 execution, native cancellation/stress, installer safety,
many-core throughput or hard aggregate memory/PID containment. CodebaseIR's
closed producer inventories remain 27 verification and 29 applicability modules;
this change adds no learned IR, proof-cache replay, indexing or planner authority.


## Standalone protocol V2 operation budget — 2026-10-04

[Qualification report](../../workspace/protocol-operation-budget-qualification-20261004/REPORT.md).

`ProtocolExecutionEngineV2.execute`, `execute_split_providers` and the
`execute_protocol` / `execute_proverif` / `execute_tamarin` helpers now use a
cooperative operation budget by default. The budget covers request/document
normalization, capability callbacks, backend execution and final evidence
construction. Split-provider execution shares one deadline and publishes no
partial result after interruption.

The default is the declared request timeout (1,000 ms when bounds are omitted),
clamped to the shared operation maximum. Constructor defaults and per-call
`operation_timeout_ms` controls may tighten that request timeout; a per-call
override replaces the constructor default, while a tighter parent deadline still
wins. Constructor and per-call cancellation signals combine with the parent.
An observed cancellation stays latched, even if its event is subsequently cleared.
Interruption raises the existing `ProofOperationTimeout` or
`ProofOperationCancelled` exception before evidence publication. Runtime controls
do not change serialized request bounds, receipt identities or evidence schemas.

Canonical backend methods receive the current operation signal. ProVerif's
default admitted runner consumes the remaining wall/CPU budget; Tamarin's existing
plain runner can poll the signal but still needs a separate admission migration.
Explicit runners remain caller-owned. Legacy `run(request)` and
`execute(request)` overrides are called exactly once, with their original
signatures and checks around the call. Opaque Python callbacks and backend-internal
compilation/probes remain cooperative and cannot be forcibly preempted.

Validation passed **2,702 joined tests**, preserving all 2,612 previous
cases and adding **90 operation-control cases**. **578 focused tests** also passed;
these populations overlap. Fifteen legacy native cases remain deselected.
Controlled tests cover deadline exhaustion, cancellation and clearing, split
budgets, final evidence construction, private pressure queues, concurrent engine
reuse and complete healthy evidence serialization. One retained V2 runner test
now expects the exact forwarded operation signal instead of `None`; direct-call
signal identity, runner ownership, no-admission behavior and declared native
limits remain asserted. The initial 577-pass/one-failure attempt is preserved.

Three real standalone V2 ProVerif calls passed in **0.414 seconds**
(**0.766 seconds** including the wrapper). Private `s` yielded
bounded `SECURE` protocol evidence. Disclosed `s` and mixed private `s`/`t` with
only `s` disclosed yielded V2 `QUARANTINED`, retaining canonical `UNKNOWN` results
and no attack replay. Fourteen observations per case bind one engine-owned
deadline across setup, compilation, canonical execution and evidence packaging;
native invocation shares that deadline. No benchmark-created outer operation or
registry call supplies it.

The serial native profile remains one CPU/process reservation, 128-MiB address
space, a five-second request, 64-KiB input/output and 128-KiB workspace bounds.
Actual native wall/CPU limits consume the remaining budget. Saved policy and real
pressure sampling remain unchanged; owned leases/waiters drain and workspaces
are cleaned. The qualification pins 111 native/dependency and 198 selected
sources and preserves **2,519 artifact bodies from 25 prior qualifications**,
including their reports and manifests. The scheduler is unchanged this turn.

This closes the standalone protocol V2 aggregate-operation gap within the
cooperative contract. Native validation covers successful standalone ProVerif
execution; real cancellation, split-provider native execution, stress tolerance,
many-core speedup and hard aggregate memory/PID containment remain unqualified.
Semantic attack reconstruction, broader query/compiler coverage, verified
toolchain identity and Hyper admission remain open.

The next Tamarin increment needs complete lifecycle/output gates and a reviewed
admission profile. Installed source enables Haskell `-N` threading and launches
Maude subprocesses. Its runtime capability count, explicit Maude selection and
process allowance must be reviewed before native migration; a one-CPU/one-process
assumption is insufficient. This V2 qualification constructs its default Tamarin
object inertly and never probes or executes Tamarin. The static report's
`test_only_dependency_pins` field does not exclude that Python constructor from
the dependency graph.

CodebaseIR producer inventories remain 27 verification and 29 applicability
modules. This increment adds no proof-cache replay, learned representation,
DuckLake indexing or planner authority.

## Tamarin default admission and lifecycle integrity — 2026-10-04

The canonical Tamarin backend now uses resource admission by default, including
registry, protocol V2 and helper calls. This completes the implementation of the
Tamarin default-runner migration described in the preceding increment; successful
native execution of the new profile remains unqualified.

The default runner requests two CPU slots and eight process slots to account for
one Haskell capability, overlapping Maude handles and launcher helpers. It passes
`+RTS -N1 -M<max(1, floor(requested bytes / 2))> -RTS` and selects Maude explicitly
with `--with-maude`. The Maude path must be a shell-safe ASCII token because
Tamarin also uses it in a shell command. The default environment excludes
`GHCRTS` and `DEBUG_MAUDE`. Constructor, discovery and default metadata probes
remain inert; explicitly supplied runners, including falsey objects, remain
caller-owned and retain their previous arguments and memory limits.
Use a name available on `PATH` or an absolute Maude path; relative paths resolve
inside the private workspace.

Memory admission and sampled Linux process-tree RSS use the requested memory
bound. The separate per-process address-space limit is `max(2 GiB, 4 × requested
memory)`. At the standard 512-MiB request this gives a 256-MiB Haskell heap limit
and 2-GiB address-space limit. Matching GHC 9.6.7 source adapts its virtual
reservation to finite `RLIMIT_AS`; newer GHC's `-xr` option is unsupported here and
is not passed. Runtime startup sufficiency still needs native qualification.
These reservations are estimates, RSS sampling can overshoot, and neither this
profile nor the Haskell heap limit provides hard aggregate OOM/PID containment.
Custom oracle processes remain outside the ordinary-stock process estimate.

Result parsing now requires a clean lifecycle, an exact integer zero exit status
and combined stdout/stderr UTF-8 bytes within the requested output bound.
Cancellation, timeout, resource/workspace exhaustion, reported errors and forced
process-tree termination cannot produce accepted protocol evidence. Every runner
result carries lifecycle metadata and stream digests; early unsupported or missing
tool results retain their previous shape. Claim matching and structural attack
trace parsing are unchanged and remain separate semantic qualification gaps.

Validation passed **2,771 joined tests**, retaining all
2,702 previous cases and adding **69 cases**.
The **647 focused tests** overlap with the joined population.
Fifteen legacy native cases remain deselected. Controlled private schedulers cover
pressure backoff, recovery, cancellation, deadline exhaustion, default routes,
caller-owned injection and complete cleanup without adding host load.

The end-to-end benchmark exercised actual production admission against the saved
pool. Its four process slots cannot fit the eight-slot reservation, so both cases
returned unaccepted capacity errors with **zero native launches and zero input
workspaces**. This qualifies refusal behavior, not successful native Tamarin
proving, native stress tolerance or many-core speedup. The benchmark took
**0.355 seconds** inside the driver and
**0.716 seconds** including the wrapper.
Pool policy and the real sampler configuration remained unchanged; owned leases
and waiters drained. Capacity refusal does not establish pressure sampling during
that acquisition. All 2,648 artifact bodies from 26 prior qualifications remain
unchanged.

Next work is native qualification under a separately reviewed adequate capacity
policy, complete Tamarin claim-set/source binding, semantic attack reconstruction
and the remaining Hyper default-runner migration. No pool widening, tool downloads
or installer changes were performed. CodebaseIR producer inventories remain
27 verification and 29 applicability modules; this increment adds no cache replay,
DuckLake indexing, learned representation or planner authority.

Evidence: `workspace/tamarin-default-admission-qualification-20261004/REPORT.md`
and its `qualification.json` in the datasets repository.

## Tamarin source and lemma binding — 2026-10-04

The canonical Tamarin backend now binds results to a nonempty, unique and complete
claim/lemma mapping derived from the actual compiled source. It ignores quoted and
commented pseudo-declarations, rejects duplicate/unsupported declarations and checks
trace quantifiers. Identical verdicts deduplicate; conflicting, unknown, missing or
malformed results remain quarantined. Diagnostic IDs cannot impersonate declared
claims, and quarantine IDs remain unique. Source text, request bounds and digest
bindings remain intact.

Native parsing reads the last summary per stream with complete result rows and a
closed metadata format. Echoed source cannot supply missing results; malformed rows,
unexpected summary text and wellformedness warnings block acceptance. Every parsed
falsified result now carries no attack trace, including existential failures that
report no trace found. Rule/marker text therefore cannot produce automatic attack
replay authority through the canonical backend or V2. The separately called legacy
trace utility remains structural only.

The binding scanner supports ordinary ASCII lemma names, `(modulo E)`, the
`sources`, `reuse`, `use_induction` attributes and universal/existential trace modes.
Preprocessing and other syntax conservatively refuse binding. This scanner does
not replace native syntax or semantic validation. Expected names `analyzed` or
`output` may conservatively conflict with summary metadata. Direct parser calls
without source retain map-only compatibility; complete legacy rows remain supported
when neither a native summary nor a theory echo is detected. These compatibility
paths do not attest native output authenticity.

Validation passed **2,858 joined tests**, retaining all 2,771
previous cases and adding **87 new cases**.
The **734 focused passes** overlap the joined population;
15 legacy native cases remain deselected. Four retained fixture files now assert
UNKNOWN/no replay for unvalidated falsification, preserving resource and identity
checks.

All **15 controlled E2E cases** passed across direct, registry and standalone V2
routes. Synthetic availability, solver output and healthy pressure used an isolated
scheduler, while the default runner, compiler, parser, workspace lifecycle and
evidence projections executed unchanged. Native launches and shared-pool access
were zero; workspaces and leases drained. The benchmark took
**0.556 seconds** in the driver and
**0.916 seconds** including the wrapper.

The benchmark also recorded **36 serial parser timing samples** across 10, 100 and
1,000 lemmas with complete, unknown, conflicting and missing outputs. The complete
1,000-lemma case had a median of **7.251 ms**. Timings include source/claim
binding and output parsing, excluding classification and serialization. They do
not establish native proving speed, native stress tolerance or many-core scaling.
The full table and raw samples are retained in the qualification.

All **2,764 artifact bodies from 27 earlier qualifications** remain unchanged.
The shared pool was not accessed or resized. Successful native Tamarin startup and
summary qualification under an adequate reviewed policy remain open, alongside
broader syntax/compiler coverage, semantic attack reconstruction and the Hyper
default-runner migration. The previous four-slot saved pool still cannot fit the
eight-slot Tamarin estimate. CodebaseIR producer inventories remain 27 verification
and 29 applicability modules; this increment adds no learned representation,
index/cache replay or planner authority.

Evidence: `workspace/tamarin-claim-binding-qualification-20261004/REPORT.md` and
`qualification.json` in the datasets repository.

## Hyper engine default admission and V2 bounds — 2026-10-04

HyperLTL, AutoHyper and MCHyper now use lazy shared admission for their owned
default runners: two CPU slots, four process slots, and the caller's requested
memory as the reservation and sampled process-tree RSS ceiling. Admission waits
consume the same native invocation deadline, and ambient proof-operation stops
remain effective. Discovery creates no scheduler state or native processes.
Standalone V2 now forwards caller bounds to `check`, aligning actual limits with
its evidence. Default version access is inert; declared identity versions remain
available without an extra `--version` subprocess.

Owned profiles set finite CPU and per-process address-space limits. Address space
is `max(2 GiB, 4 × requested RSS)`, or `max(4 GiB, 4 × requested RSS)` for AutoHyper.
AutoHyper uses `DOTNET_PROCESSOR_COUNT=1`, `DOTNET_gcServer=0` and a hexadecimal
`DOTNET_GCHeapHardLimit` equal to half the requested memory (minimum one byte).
Conflicting GC aliases/per-heap overrides are removed; required runtime paths are
preserved. CPU/process reservations are estimates, GC heap is not total memory,
and RSS sampling can overshoot. Native startup under these profiles is unqualified.
AutoHyper retains its documented `RLIMIT_FSIZE` compatibility exception: workspace
size is checked after execution, with no live disk-write ceiling.

Unsafe resource, cancellation, timeout, cleanup, process-tree, error, output-limit
or malformed-stream conditions block verdict/witness interpretation. Conclusive
verdicts require an exact integer zero exit status. A clean unsupported-fragment
exit remains nonconclusive `UNSUPPORTED`. Results retain lifecycle metadata and
stream digests. NUL-containing output is rejected and sanitized in receipt text;
metadata and byte usage retain the original stream binding. Explicit plain,
falsey and admitted runners retain caller-owned resource/environment profiles;
an explicit admitted runner must supply finite limits itself. Safe explicit-runner
version probes remain a separate three-second metadata call. Custom backend
`check` overrides must accept the new `bounds` keyword for V2.

Validation passed **2,993 joined tests**, retaining all 2,858 previous
cases and adding **80 new admission cases** plus 55 existing Hyper
integration cases. The **469 focused passes** overlap that population;
15 legacy native cases remain deselected. The retained initial focused attempt
found the exit-2 compatibility regression, which was corrected before final runs.

All **26 controlled end-to-end cases** passed: direct and V2 execution for every
engine, the actual HyperLTL registry delegate, resource-failure rejection,
impossible-capacity refusal and nine pressure/recovery samples. Each uses an
isolated private scheduler, synthetic engine output/discovery and synthetic host
pressure. Actual admission queues backed off before any workspace/executor work,
then recovered after pressure release; owned leases, waiters and workspaces drained.
Median controlled admission waits: hyperltl **20.71 ms**, autohyper **20.72 ms**, mchyper **20.85 ms**. These timings include an intentional
20-ms fixture backoff and do not measure native proving or many-core scaling.
Driver time was **1.970 seconds**, or **2.418 seconds**
including the wrapper. Native launches and shared-pool accesses were zero.

All **2,883 artifact bodies from 28 previous qualifications** remain unchanged.
CodebaseIR producer inventories remain 27 verification and 29 applicability
modules, with no additional cache/index, learned-IR or planner authority.

Remaining gaps: registry AutoHyper/MCHyper aliases currently select HyperLTL;
standalone V2 whole-operation budgeting/cancellation; explicit-runner version
budgeting; native Hyper startup/stress/scaling; hard aggregate containment and
AutoHyper live disk bounds; semantic witness qualification. Tamarin native startup,
broader syntax and semantic attack reconstruction also remain open.

Evidence: `workspace/hyper-default-admission-qualification-20261004/REPORT.md`
and `qualification.json` in the datasets repository.

## Independent Hyper engine registry routing — 2026-10-04

`hyperltl`, `autohyper` and `mchyper` now select their own lazily constructed,
independently cached backends through the default registry. Previously those IDs
were aliases for the combined family and all selected HyperLTL. Each engine keeps
default resource admission, caller bounds, request identity and typed engine
evidence. Generic bounded results remain UNKNOWN and confer no theorem authority.

The legacy `hyperltl_autohyper_mchyper` ID still executes HyperLTL, and implicit
provider ordering is preserved. To select an engine, set its canonical ID in the
request, or leave the request ID empty and pass that engine as the explicit
selector. If both are present they must agree. A legacy-family request paired
with an individual-engine selector is now a conflict, rejected before delegate
construction. Missing engines do not silently select a peer.

The provider catalog, conformance axes, alignment PATH probes and source audit now
agree on 18 executable provider IDs (20 including advisory entries). Three current
generated JSON catalogs were refreshed with retained before/after bytes. These
declarations and source observations do not establish installed native capability.

Validation: **3,195 joined tests passed**, retaining all 2,993 previous cases and
adding **41 new routing cases** plus 161 existing catalog/API checks. The final
selection deselects 19 native cases. Earlier focused validation passed 519 tests;
518 overlap the final joined population, so counts are not added. The first
attempt's two fixture errors and stale generated audit were corrected and retained.

All **29 controlled E2E benchmark cases** passed. With three concurrent engines
and a private pool sized for two jobs, the scheduler observed two active leases
and one waiting request, then drained all leases, waiters and workspaces. The pool
had four CPU slots, 256 MiB and eight process slots; each request reserved two CPU
slots, 128 MiB and four process slots. The driver took **0.694 seconds**
(**1.166 seconds** including its wrapper). Discovery, engine output
and pressure samples were synthetic; the registry, admission, workspace and result
binding paths executed. This measures controlled routing, not native proof speed.

Validation scope: earlier focused attempts inadvertently included uninstrumented
legacy API tests capable of native/portfolio execution. Their native and shared-pool
activity is **unmeasured**. All four such API cases are excluded from the final
joined selection. Zero native launches/shared-pool accesses applies only to the
guarded new routing fixtures and controlled benchmark, not the entire turn.

All **3,014 artifact bodies from 29 prior qualifications** remain unchanged.
CodebaseIR producer inventories remain 27 verification and 29 applicability modules;
this increment adds no learned representation, cache/index replay or planner authority.
Remaining gaps include standalone Hyper V2 whole-operation budgets/cancellation,
explicit-runner version budgets, native startup/stress/many-core scaling, aggregate
containment, AutoHyper live disk limits and semantic witness qualification. Tamarin
native startup, broader syntax and semantic attack reconstruction also remain open.

Evidence: `workspace/hyper-registry-routing-qualification-20261004/REPORT.md`
and `qualification.json` in the datasets repository.

## Hyper whole-operation budgets and cancellation — 2026-10-04

Standalone Hyper V2 execution now establishes a cooperative operation deadline by
default from the request timeout. The engine constructor, `execute`,
`execute_split_capabilities` and convenience helpers accept `operation_timeout_ms`
and `cancellation`. A per-call timeout overrides the constructor default, capped by
the declared request timeout; a tighter enclosing operation still wins. Constructor,
call and enclosing cancellation signals combine, and observed stops remain latched.

One budget covers normalization, capability callbacks, translation, admission,
native execution, metadata, witness handling and evidence construction. A split
shares that budget across all three engines; interruption raises
`ProofOperationTimeout` or `ProofOperationCancelled` without returning a partial
mapping or late evidence. Python callbacks are checked at boundaries and cannot be
forcibly preempted. Cleanup may extend beyond the deadline.

Native and explicit-runner version invocations use the remaining enclosing budget.
Requests, declared bounds and receipt timeouts retain their original values;
effective invocation limits are recorded separately. Default admission and memory
profiles remain in place. Falsey injected backends/engines retain ownership, and
legacy callback signatures are called once without retry. Direct adapter checks
and standalone capability probes do not create a new operation scope themselves;
they observe an existing enclosing scope.

Validation passed **3,290 joined tests**, including **95 new cases** and all
3,195 previously retained cases. The **594 focused passes** overlap this population;
19 native cases remain deselected. The first full run passed, but an external
scheduler edit occurred during it. That edit only adds timeout diagnostics; both
generations were retained and reviewed, and the complete suite was rerun with
stable source hashes. A subsequent diagnostic-only edit bounds the timeout lane
text; the benchmark used that later stable generation. The full suite ran against
the preceding generation. Owned Hyper code was identical in both runs, and the
exact dependency hashes and review of both deltas are retained.

All **19 controlled E2E benchmark cases** passed, including six queued stops,
three external-pressure recovery fixtures, successful splits and two interrupted
splits. All eight stopped calls returned no result. Private leases, waiters and
workspaces drained. Driver time was **3.153 seconds**, or
**3.672 seconds** including its wrapper. Discovery, solver
output and pressure were synthetic; native launches and shared-pool accesses were
zero in this benchmark. These measurements do not establish native preemption,
real host-pressure resilience, proof throughput or many-core speedup.

All **3,150 artifact bodies from 30 earlier qualifications** remain unchanged.
CodebaseIR inventories remain 27 verification and 29 applicability modules; no new
learned representation, cache/index replay or planner authority is established.
Remaining work includes native Hyper startup/stress/scaling, hard aggregate
containment, AutoHyper live disk limits and semantic witness validation. Explicit
runner metadata outside an enclosing scope still uses its separate three-second
limit. Tamarin native startup, broader syntax and semantic attack reconstruction
also remain open.

Evidence: `workspace/hyper-operation-control-qualification-20261004/REPORT.md`
and `qualification.json` in the datasets repository.

## Hyper counterexample structural validation — 2026-10-04

Native Hyper witness parsing now requires exact declared trace labels and complete,
unique approved assignments. It rejects ambiguous fields, inconsistent DIFF rows,
malformed Unicode/control records and inputs exceeding finite byte/line/field/trace
limits. Differences and digests are recomputed; no missing difference is fabricated.
Context-bound validation requires exactly two forall traces, equal low-input and
subject projections, and a genuine approved observation difference. Native bundles
require explicit `observation_map`, `quantifier_order` and `formula_id`; manual replay
also requires expected `formula_id`. V2 rechecks the actual request, including
reconstructed positive witness claims. Incomplete legacy witness fixtures must be
updated to include every approved public, observation and subject field.

Validation: **3390 selected tests passed**, retaining all **3290** previous
cases and adding **100**; **694** focused tests passed. The same
19 native-capable legacy cases remain deselected. **36 controlled end-to-end cases**
cover three engines, three routes and valid/malformed/equal-observation/unequal-low
witnesses, using default managed runners and a private 2-CPU / 128-MiB / 4-child-slot
pool. All leases and workspaces were released; guarded native launches and shared
pool accesses were zero. Timings measure synthetic-executor orchestration and
structural validation; they do not establish native throughput or many-core speedup.

Engine-reported `VIOLATED` remains separate from witness validation; generic registry
results retain `UNKNOWN` and no theorem authority. The legacy `replayed` flag means
only structural projection validation. Native reachability, temporal semantics,
high-input variation and output authenticity remain unvalidated. The bounded
self-composition evaluator retains its separate non-authoritative bundle path.
Canonical witness raw text retains approved assignments only; original receipt
stdout/stderr are still captured separately. Earlier qualifications and 27 verification
/ 29 applicability producer inventories are preserved. Native startup/profile,
real external-pressure stress, aggregate containment and scaling gaps remain open.

Evidence: `workspace/hyper-counterexample-validation-qualification-20261004/REPORT.md`.

## Default live workspace guard — 2026-10-04

The shared bounded subprocess runner now inspects private workspace logical bytes,
entry count and directory depth before launch, about every 100 ms between completed
samples, and after execution. This is enabled by default, including AutoHyper's
explicit per-file-limit opt-out. Entry/depth defaults are 16,384/64, with configurable
hard ceilings of 1,000,000/256. POSIX traversal uses no-follow directory descriptors;
symlinks and special files count as entries without reading their targets or bodies.
Non-transient inspection errors fail conservatively. Cancellation/deadlines are
checked between scan steps and immediately before launch. A normalized executor
exception is preserved without calling a failed cancellation callback again.

Observed workspace overruns terminate through the existing process-tree cleanup
and remain latched even when a SIGTERM handler removes files and exits zero. Final
checks cover injected executors too; stopped or failed runs can interrupt that scan.
The admission lease remains held through process/workspace cleanup. Per-file limits,
AutoHyper runtime settings and scheduler capacities are unchanged. A previous test
expecting an over-budget process to exit zero now permits earlier termination while
still requiring resource/workspace failure.

Validation: **3522 selected tests passed**, retaining all **3390** previous
cases, adding **56** new guard tests and selecting **76** existing
process tests. **477** focused tests passed; the same 19 native-capable
legacy cases remain deselected. The retained first focused attempt exposed three
callback-error cleanup regressions, which were fixed before the accepted runs.
**12 real Python-process benchmark cases** passed in **2.397s**,
with one owned child and two waves of two concurrent jobs. The private pool had capacity
2 CPU / 256 MiB / 4 child slots; each job reserved 1 CPU / 128 MiB / 2 child slots,
with finite wall/CPU/AS/RSS/output limits and an 8-KiB workspace budget. Scheduled writes totalled 242,688 bytes across all cases.
Healthy/exact-budget runs succeeded; all eight overruns and the cancellation were
refused, including two delete-on-shutdown cases. Processes, workspaces and leases
drained; shared scheduler access was zero. These are real process-lifecycle tests
with synthetic healthy resource samples, not installed solver or pressure tests.

This is sampled logical-size protection, not a disk quota. Between-sample overshoot,
external-path writes and open-unlinked files are outside the guarantee; hard links
are conservatively counted per entry and sparse files by logical size. Filesystem
calls/cleanup are not forcibly preemptible. The portable path-based fallback is not
a hostile-race security boundary; native qualification here is Linux only. Native
solver startup, real-pressure stress, hard aggregate containment, temporal witness
replay and many-core scaling remain open. A separate Hyper follow-up is immutable
evidence plus complete request-ID/digest/bounds binding during reconstruction.

All **3440 artifact bodies from 32 prior qualifications** remain unchanged. Current
CodebaseIR producer inventories still contain 27 verification / 29 applicability
modules; only the process module hash changes. Historical records retain their
original pins, and strict current-generation cache checks are not relaxed. This
increment adds no proof-cache migration, learned representation or planner authority.

Evidence: `workspace/process-workspace-guard-qualification-20261004/REPORT.md`.

## Hyper V2 evidence integrity — 2026-10-04

Hyper V2 request/evidence payloads and attached translation mappings now freeze
nested containers, and public JSON exports return detached values. Supplied
evidence content digests are checked against the existing digest preimage; the
schema and digest algorithm are unchanged. Reconstructing a result checks its
request ID/digest/source references, document/formula/system, declared execution
bounds, typed backend result, translation and receipt links. Structural witness
validation remains bound to the actual request; a path declaring no evidence
cannot carry a counterexample or witness bundle. Each payload copy is limited to
16 MiB of UTF-8 string content, 65,536 nodes and depth 64, with cooperative
operation checkpoints.
Existing UTF-8 and ASCII digest encodings are preserved. Receipt identity checks
restore the declared timeout float from the request bounds before hashing.
Attached translations must match the canonical engine renderer, projection maps
and auxiliary files for the retained request; internally consistent custom
translations that differ from those canonical bindings are rejected. Callers
editing payloads must use detached public `to_dict()` values to rebuild records.
No existing test files changed.

Validation: **3652 selected tests passed**, retaining all **3522** previous
cases and adding **130**; **608** focused tests passed. The
same 19 native-capable legacy cases remain deselected. **12 controlled end-to-end
cases** passed in **0.445s**: three engines with satisfied
and violated outputs, three capability probes, mock/fallback-payload rejection,
and bounded evaluator fallback through an explicitly unavailable discovery
fixture. Six production managed-runner paths executed against private
2-CPU / 128-MiB / 4-child-slot pools with synthetic outputs and healthy host samples.
All **108 binding mutations** and **93 nested mutation attempts** were
rejected; all 12 records retained stable public wire projections and digests.
Workspaces and leases drained; guarded native launches and shared pool access
were zero. Timings measure these mixed controlled paths, not native throughput.

Reconstruction retains the typed request/source/model: the existing request wire
contains digests and trace counts, not complete raw documents, models or private
trace contents. This adds no standalone full-result JSON decoder or private-trace
content binding. Public `to_dict()` exports are the supported detached snapshots;
no `deepcopy(MappingProxyType)` contract is added. Consistent records and valid
digests do not establish solver authenticity, signatures, model membership or
temporal witness replay. Mock, supplied fallback and capability-only paths retain
no proof or theorem authority. Bounded evaluator fallback remains separate from
native structural replay. Real external-pressure stress, hard containment and
many-core scaling remain open.

All **3523 artifact bodies from 33 prior qualifications** remain unchanged,
including every retained earlier attempt. The 27 verification / 29 applicability
producer inventories are unchanged. No cache authority, learned CodebaseIR or
planner authority is added by this increment.

Evidence: `workspace/hyper-evidence-integrity-qualification-20261004/REPORT.md`.

## Hyper bounded fallback applicability — 2026-10-04

V2 fallback result construction now re-evaluates the retained traces with the
canonical bounded evaluator and checks the resulting disposition, redacted
counterexample, witness bundle and successful evaluator reason suffix. A same-count trace substitution can no longer
retain a violation witness that the supplied traces do not support. Equivalent
private-value renaming and trace permutation remain accepted when these public
outcomes agree. This establishes outcome applicability, not private-trace identity.
The V2 wire format and digest algorithms remain unchanged; the request descriptor
still binds trace count rather than private contents, and no public private-input
hash is added. Generic `BackendRequest` payload redaction is unchanged.
The generic registry retains its availability veto: a missing tool stops before
the fallback delegate runs. Missing-tool registry fallback remains an integration
gap; the actual fallback qualification here covers the direct/V2 paths.

Trace normalization has finite limits of 16,384 records, 262,144 nodes, 16 MiB of
UTF-8 string content, depth 32 and 4,096-bit integers. Normalization, bounded
selection, pair evaluation and witness publication have cooperative checkpoints.
Direct backend normalization and fallback use separate bounded operation scopes,
with discovery between them; this is not a single aggregate deadline for the
whole direct run. V2 reconstruction uses bounded operation control, and nested
validation inherits a tighter parent deadline and cancellation.
These limits bound input traversal/copy work, not process RSS or opaque callback
execution. They do not establish hard preemption or aggregate memory containment.

Validation: **3738 selected tests passed**, retaining all **3652** previous
cases, adding **70** new tests and selecting **16** existing
core evaluator tests; **694** focused tests passed. The
same 19 native-capable legacy cases remain deselected. **15 controlled end-to-end
cases** passed in **0.730s**: all three providers exercise
violated, clean and limited fallback evaluations, followed by three managed
engine paths with synthetic SAT output and three typed cooperative stops.
The nine fallback cases invoke the actual evaluator and canonical revalidation.
**21 changed outcomes were rejected**, **18 equivalent outcomes were accepted**,
and all **three interrupted operations withheld results**. The interruption
fixture sets cancellation or consumes the deadline at entry to the actual
evaluator, including a second-evaluation stop during result validation.

The managed paths retain private 2-CPU / 128-MiB / 4-child-slot pools. Discovery,
native-shaped output and healthy host samples are synthetic. Three synthetic
executor calls ran; actual native launches and shared pool accesses were zero.
Workspaces and owned leases drained. Private fixture sentinels were absent from
recorded results and errors. Mixed-path timings include an intentional deadline
delay and are not a native proof-throughput or parallel-scaling measurement.

Clean and limited fallback results remain UNKNOWN; fallback violations remain
bounded and do not establish external-engine or theorem authority. Successful
evaluations require the canonical reason suffix; the unsupported branch does not
claim exact canonical reason binding. Exact private values remain unbound. Broader
declassification behavior, missing-field semantics, whole-private-map comparison
and `max_steps` disclosure semantics are unchanged. Native authenticity,
model membership, general temporal replay, real external-pressure stress and
many-core scaling remain open.

All **3695 artifact bodies from 34 prior qualifications** remain unchanged,
including every retained earlier attempt. The 27 verification / 29 applicability
producer inventories are unchanged. No existing test files changed. No cache,
learned CodebaseIR or planner authority is added by this increment.

Evidence: `workspace/hyper-fallback-validation-qualification-20261004/REPORT.md`.

## Request-scoped Hyper registry fallback — 2026-10-04

The default registry can now use bounded local fallback when the selected Hyper
tool is missing, the request opts in with exact boolean `allow_fallback=True`,
and nonempty traces are supplied. Eligibility is checked for that request and
the matching canonical HyperLTL, AutoHyper, MCHyper or legacy-family delegate.
Public native availability remains false. Caller-defined availability contracts
remain in force; their refusals, probe failures and explicit vetoes do not acquire
the missing-tool exception. The delegate rechecks discovery. With default
adapters, a newly available tool uses the ordinary resource-admitted native
runner; caller-provided runners keep their existing contract.

This closes the narrow missing-tool registry fallback gap recorded in the prior
qualification. The six existing gate tests now expect the opted-in behavior;
their original bodies and case IDs are retained as historical evidence. Prior
qualification reports and artifacts remain unchanged.

Validation: **3809 selected tests passed**, retaining all **3738** previous
cases and adding **71**; **989** focused tests passed. The
same 19 native-capable legacy cases remain deselected. **20 controlled results**
passed in **0.535s**: the four selectors each cover
violated, clean and limited fallback; paired negatives cover disabled opt-in,
empty traces, an explicit availability veto and a discovery failure. Two stops
produce bound CANCELLED/TIMED_OUT attempts with generic UNKNOWN results. Two
overlapping calls on one registry demonstrate that an opted-in fallback does not
enable a concurrent request lacking opt-in.

The actual bounded evaluator produced **13 fallback outcomes**, with **five
unavailable refusals** and **two normalized stops**. The registry preserves typed
redacted outcomes while every generic result remains UNKNOWN. Private fixture
sentinels are absent from recorded outcomes and errors. Full generic requests
are not persisted by this benchmark: their existing payload format contains
trace inputs, so artifacts store only safe descriptors, trace counts and request
digests. This artifact policy does not change generic request redaction or remove
the existing request digest's commitment to its payload.

Discovery is synthetic; availability is never forced true and evaluator results
are not injected. Actual native launches, transports and scheduler accesses were
zero. Pure Python fallback does not acquire scheduler leases or provide host
pressure backoff. It retains finite input/evaluation bounds and cooperative
operation cancellation, without hard RSS containment or opaque callback
preemption. Timings include controlled deadline and rendezvous delays and do not
measure native proving throughput or many-core scaling. V2 outcome applicability,
private-trace identity limitations and broader evaluator semantics are unchanged.

All **3856 artifact bodies from 35 prior qualifications** remain unchanged,
including retained earlier attempts. The 27 verification / 29 applicability
producer inventories are unchanged. This increment changes two production files
and the six expectations in one existing test file. It adds no theorem, cache,
learned CodebaseIR or planner authority.

Evidence: `workspace/hyper-registry-fallback-qualification-20261004/REPORT.md`.


## Hyper installer hardening and Python admission — 2026-10-04

Hyper fallback and V2 applicability reevaluation now use default scheduler
admission: one CPU, the requested finite memory reservation, and zero process
slots. Admission waits under external pressure and honors cancellation and the
aggregate deadline. This supersedes the earlier note that Python fallback has
no scheduler admission. Already admitted Python work is not paused by subsequent
host pressure, and reservations do not impose a hard Python RSS ceiling.

The Hyper installer now streams digest-checked downloads into unique temporary
files; limits compressed/expanded bytes, archive structure and hashing; rejects
unsafe members and redirects; serializes same-tool installations; and retains
the previous tree and launcher through identity audit and publication. Build
and probe subprocesses acquire scheduler capacity by default. Their CPU, memory,
output, workspace and time controls also apply during cancellation and cleanup.
AutoHyper output and its temporary package cache stay inside the guarded source
workspace. Lazy setup supports reviewed dependency roots and retry after an
interrupted attempt. Missing dependencies remain explicit blockers.

Validation: **4,060 selected tests passed**, including all 3,809 prior cases,
177 new cases and 74 newly selected existing setup tests; **1,163 focused tests
passed**. The same 19 legacy native cases remain deselected. Nine controlled
installer benchmark groups passed in **1.035 s**, using eight actual small
Python subprocesses, with concurrent requests, rollback, pressure recovery and
cancellation. Eight Python admission cases passed in **0.454 s**, including
three queued cancellations and two overlapping reservations. All owned leases,
waiters and subprocesses drained. Pressure was injected through private sampler
fixtures; these timings are not many-core proving throughput measurements.

Fresh official pinned EAHyper, AutoHyper and MCHyper main-source archives all
passed actual download, digest and extraction checks (19,723,238 compressed
bytes total). Full fresh upstream compilation and native Hyper proving remain
unqualified; required toolchains are not on this host's PATH. Automatic
provisioning of those dependencies and real many-core proving benchmarks remain
follow-up work. Sampled process limits can overshoot; no hard aggregate memory
or disk guarantee is claimed. Import/discovery does not initiate installation.
No proof-cache, learned CodebaseIR, or planner authority is added.

Evidence: `workspace/hyper-installer-resource-qualification-20261004/REPORT.md`.
All 3,975 artifact bodies from 36 earlier qualifications and the 27/29 producer
inventories are preserved. Earlier failed attempts remain in the new report.


## Native Hyper setup validation — 2026-10-04

The native Hyper gap is now narrower: EAHyper, AutoHyper and MCHyper were built
from fresh pinned main-source downloads into an isolated prefix, using the
existing managed compiler/runtime dependencies outside PATH. The actual shared
scheduler and default installer limits governed all 42 top-level build/probe
launches. All three installations passed identity audits and cached reuse
without additional native commands. The complete build run took **43.867 s**
(EAHyper 11.817 s, AutoHyper 11.191 s, MCHyper 20.805 s).

Five native smoke checks passed through the default admitted adapters in
**6.316 s**: EAHyper satisfiability, plus holding and violating models for
AutoHyper and MCHyper. Each check reserved two CPUs, 512 MiB and four process
slots, with a 30-second operation budget. Owned leases, processes and workspaces
were released, and vendor identities were unchanged. This supersedes the prior
absence of fresh native build/check evidence; these small cases do not establish
many-core speedup or a complete semantic certification.

New setup utilities provide an inert dependency plan and explicitly authorized
repair of MCHyper's three pinned provenance archives. The actual missing AIGER,
ABC and Python source archives were downloaded into a separate cache and
checksum-verified. Filesystem candidates remain unvalidated until normal
installer probes and audits pass. Invalid explicit executable roots now fail
before probes instead of silently selecting a PATH tool; explicit archive
paths remain authoritative during repair.

**4,137 selected tests passed**, preserving all 4,060 previous cases and adding
77 (42 resolver and 35 setup cases); **1,063 focused tests passed**. The same
19 legacy native cases remain deselected; this increment's five native checks
ran separately. All **4,561 artifact bodies from 37 prior qualifications** and
the 27/29 producer inventories remain preserved.

Remaining work includes reviewed compiler/runtime provisioning on a clean
machine, larger mixed-solver parallel workloads, and pressure-response/scaling
qualification. The native builds reused existing compiler installations; the
setup utility repairs provenance archives and does not bootstrap those
compilers. Reservations and sampled process guards remain estimates rather
than hard aggregate memory/disk limits. This adds no learned CodebaseIR,
proof-cache or symbolic-planner authority.

Evidence: `workspace/hyper-native-setup-qualification-20261004/REPORT.md`.


## Hyper setup integrity and bounded parallel validation — 2026-10-04

MCHyper preparation now rejects conflicting archive destinations before any
transfer, rehashes the final archive set under the original operation budget,
and refuses a verified result if files change during validation. Explicit GHCup
aliases also retain precedence over automatically discovered managed roots.
Three fresh official provenance archives passed actual download, final hashing
and cache-reuse checks in **4.366 s**. Verification records observed bytes; it
does not lock the cache against later writers or provision missing compilers.

The native benchmark ran the same ten EAHyper/AutoHyper/MCHyper fixtures serially
and with two workers through unchanged default admitted adapters and the actual
shared scheduler/host sampler. The serial phase took **1.812 s** and the parallel
phase **0.896 s**, with sampled live native-root peaks of one and two. All twenty
native cases passed, and owned processes, workspaces and leases drained. The
**2.022** elapsed ratio is one sequential-then-parallel trial on small repeated
fixtures, not evidence of general many-core scaling or CPU utilization.

A separate scheduler-only check filled a 4-CPU/1-GiB/eight-process parent
envelope with two children, observed its uniquely identified third child wait,
and released capacity. Admission resumed in **0.058 s**; all four leases and
the owned waiter drained. This exercises parent-capacity contention, without
manufacturing host pressure or reserving the whole shared pool.

The first native attempt encountered actual kernel memory-stall pressure
(**20.89%** at the retained refusal, above the default **2%** threshold).
Default admission launched no solver, and the request timed out after its
30-second budget with no leaked waiter or reservation. After three unmodified
sampler readings below the stall thresholds, a separate retry completed the
native benchmark. This establishes an observed natural-pressure refusal and a
later successful retry; it does not establish the cause of that pressure or
recovery of the original timed-out request. No safety threshold was relaxed.

**4,215 selected tests passed**, retaining all 4,137 previous case IDs and adding
78 (29 setup-integrity and 49 benchmark cases). **1,141 focused tests passed**;
the same 19 legacy native cases remain deselected. Both native attempts and the
superseded focused test generation remain recorded. All **4,796 artifact bodies
from 38 earlier qualifications** and the 27/29 producer inventories are intact.

Next work is to pin compiler/runtime distributions per supported platform,
provide bounded runtime-specific extraction and installation recipes, and
qualify a clean-machine bootstrap. Larger mixed-solver trials need repeated
measurements and a safely isolated pressure environment. Existing reservations
and sampled guards remain estimates; no hard aggregate containment, semantic
witness certification or additional proof/planner authority is introduced.

Evidence: `workspace/hyper-parallel-setup-qualification-20261004/REPORT.md`.


## Bounded .NET SDK bootstrap for AutoHyper — 2026-10-04

The separate `plan_dotnet_sdk_setup` / `ensure_dotnet_sdk` API provisions the
fixed .NET SDK 8.0.300 distribution used by the current AutoHyper vendor recipe,
with runtime 8.0.5 and reviewed Linux glibc ARM64/x64 archive pins. Planning and
`yes=False` remain inert. Provisioning requires `yes=True`; this API is not yet
connected to automatic lazy dependency installation. The fixed version is a
vendor compatibility target, not a recommendation to use it for other workloads.

The SDK archive is authenticated with its pinned SHA-512 before extraction.
Finite byte, member, path and depth limits constrain acquisition and extraction;
publication is transactional, and cache reuse derives a fresh archive inventory
and audits the installed tree. Staged and published version probes use owned
first-use directories and an isolated environment. The receipt identifies a
support dependency and grants no proof authority. Verification observes current
bytes; it does not make a writable installation immutable.

The default operation budget is 30 minutes. Native install commands retain the
existing one-CPU, 1-GiB sampled RSS, four-process admission request and finite
8-GiB address-space limit. These controls inherit cancellation and parent
deadlines; sampled guards and reservations do not guarantee aggregate process
containment. SDK acquisition reuses the host OS loader/libraries, and the
AutoHyper recipe still requires an existing reviewed Spot installation. OCaml,
GHC and other compiler provisioning remain separate work.

The cold-bootstrap driver uses fresh SDK/cache/engine destinations, then performs
AutoHyper build, cache reuse and two default-runner native smoke checks under one
operation. Large live trees stay outside the qualification artifact directory.
“Cold” describes fresh filesystem destinations, not cold OS or network caches;
these checks do not establish clean-machine portability, semantic witness
certification, many-core scaling or new proof-index/planner authority.


Current qualification is **blocked by host pressure**. All **4,393 selected
tests passed**, retaining all 4,215 previous case IDs and adding 178 cases
(SDK 40, archive 77, command controls 17, benchmark 44). **1,299 focused tests
passed**; the existing 19 native deselections remain. This establishes the
regression checks, not completion of the full fresh native pipeline.

The final fresh attempt authenticated and extracted the 217,385,231-byte SDK
archive and completed one staged native version probe. Its published-version
probe could not obtain admission: the observer retained 15 actual matching
memory-stall refusals against the unchanged 2% threshold, with the last sample
at 20.71%. The operation stopped after **49.637 seconds**; the transaction
removed the published SDK and staging payload, leaving only coordination-lock
metadata. No AutoHyper build or native solver ran in that final attempt.
Healthy preflight samples had preceded this attempt; they did not guarantee
continued headroom. These observations establish refusal and rollback, not
recovery of a timed-out request or the source of the host pressure.

Earlier attempts are retained. Two exposed an extra empty SDK metadata directory
created by the CLI restore/build route, correctly rejected by cache validation.
The recipe now uses direct MSBuild Restore/Build targets, owned caches and
explicit workload/signature controls. An earlier generation completed all seven
SDK/build commands and both authenticated cache checks, then timed out before
launching a native smoke solver. Its matching historical refusal record is not
uniquely bound to that smoke waiter. The final signature-control generation has
not completed the whole native pipeline. The first attempt's deciding admission
cause was not captured and is not inferred from later samples.

Full final-generation SDK bootstrap, AutoHyper build/reuse and two native smoke
checks remain pending a sufficiently healthy host. No safety threshold was
relaxed and no failed attempt is presented as complete end-to-end qualification.

Current status and retained evidence:
`workspace/hyper-dotnet-bootstrap-qualification-20261004/STATUS.md`.
