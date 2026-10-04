# Repository scanning proof indexing and intent grounded planning

Build a repeatable loop from the repository under test to source-bound Codebase
IR, formal obligations, checked evidence and a current Intent IR planning
context. The `ipfs_accelerate_py` supervisor can then select an admitted change,
measure its result and refresh the index. A parallel training queue adapts a
private Codebase decoder from existing compatible weights and embeddings.
Training candidates and formalization candidates receive separate evaluations.

This is the operational companion to the [comprehensive improvement plan](codebase_ir_proof_index_improvement_plan.md),
the [eighteen implementation work items](codebase_ir_proof_index_work_items.json)
and the [twelve family and dimension inventories](ir_family_dimension_inventory_plan.json).
The [pipeline contract](codebase_ir_repository_pipeline_plan.json) specifies
proposed stage dependencies and handoffs. Its identifiers and record names are
design targets for reviewed adapters, not newly deployed APIs or schemas.

The [first grounding pilot](pilots/intent_codebase_grounding/README.md) supplies
exact authored source, native reference contracts, a closed specification schema
and seven adapter handoffs. Its first milestone is read-only capture,
conditional evidence and grounded intent. Expected outcomes remain separate
from runtime observations, and model availability is optional for this milestone.

## What each subsystem learns and establishes

Repository-specific IR content consists of that repository's exact source,
symbols, relationships, contracts and effects under a versioned native schema.
Its private model learns representations and supported mappings over that
content. Adding a new file or feature does not silently redefine the shared
Codebase IR schema. Changes to the feature basis, grammar or span contract use
an explicit migration and preserve their inherited lineage.

Keep `codebase_ir`, `intent_ir`, `legal_ir` and `security_ir` separate. Each has
8D, 384D and 768D cells, task-specific heads, its own registry/index databases,
DuckLake catalog/data and proposed Hugging Face repository. A repository
adaptation is a variant inside its owning cell. Capture source once; reference
that capture from the cells. Request only the cells needed for a particular
plan, and keep the other cells independently usable.

Autoencoders propose native IR or logic candidates within an admitted task.
Independent native targets, source correspondence and formal checks establish
their scope. A parse, a model prediction, a conditional solver result, a test
result and a kernel-checked certificate have different meanings. The proof
index stores these distinctions and their dependencies.

## Existing implementations and the required additions

The [current inspection](../../../../artifacts/codebase-ir-repository-pipeline-plan-20261002/inspection.json)
pins the exact files used for this plan. Historical release observations in the
main guide remain historical; release integration must select fresh reviewed
code and artifacts through C00.

| Existing component | Actual inspected scope | Proposed operational addition |
| --- | --- | --- |
| [RepositoryCodebaseIndex](../../ipfs_datasets_py/logic/software_contracts/codebase_ir.py) | Bounded structural capture and durable heads; `observe_current` checks current admitted bytes and active ASTs | Registration, explicit clean/overlay modes, paged aggregate capture and replay reobservation |
| [DuckDB AST ingestor](../../ipfs_datasets_py/logic/software_contracts/duckdb_ingest.py) | Source shard and previous-publication reuse includes process-local state; semantic preparation rescans facts | Separate warm-cache, restart-hydration, semantic-rescan and embedding-reuse measurements |
| [Evidence index](../../ipfs_datasets_py/duckdb_control/codebase_evidence_index.py) | Durable exact historical conditional receipts under a closed integer-offset profile | Owner migrations for broader obligations/outcomes, fresh applicability and history delivery |
| [Integer verifier](../../ipfs_datasets_py/logic/software_contracts/codebase_integer_verification.py) and [property cache](../../ipfs_datasets_py/logic/software_contracts/codebase_property_cache.py) | Positive historical cache hits still require fresh native solver checks and current source observation | Explicit cache classes and truthful work-saved counters; portable-certificate reuse only after a separate adapter |
| [Source feature trainer](../../ipfs_datasets_py/logic/software_contracts/codebase_source_training.py) | Structural 8D; frozen cohort/basis and compatible Adam continuation; absent parent can create fresh weights | Mandatory inherited mode, unknown-atom gate and reviewed cohort/basis expansion |
| [Federated trainer](../../ipfs_datasets_py/logic/software_contracts/codebase_federated_training.py) | Fits current inherited client paths; replay is diagnostic; aggregate Adam moments/progress reset | Distinct update policy, historical retention gate and federated lineage recovery |
| Source384 and strict corpus/model-generation wrappers | Narrow Security-payload source384 bridge and separately pinned worktree modules; some are absent from the active checkout | C00 integration and explicit selection; no general Codebase decoder claim |
| [Obligation compiler](../../ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/planning/obligation_graph_compiler.py) and [symbolic planner](../../ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/planning/symbolic_candidate_planner.py) | False matching facts block goals; unknown facts require review; planner selects supplied candidates | State-qualified repair goals, approved observation workflow and real producer/runner catalog |
| [Intent constraint adapter](../../ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/proof/intent_constraint_adapter.py) | Requires verified Intent and Formalization artifacts; conformance fields include ID-presence checks | Typed Codebase/formalization bridge and owner-derived satisfaction evidence |
| [Verification executor](../../ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/verification/executor.py) | Missing observations can default to plan/pre-state identities; missing runners reject execution | Trusted live observer before/after checks and exact runner/environment bindings |

Supervisor findings above refer to the inspected nested checkout. The sibling
checkout has a different planner implementation. Compare both with the chosen
release before porting changes; matching filenames do not select a lineage.

## Pipeline and artifact handoffs

~~~mermaid
flowchart TD
    R[Registered repository and scan policy] --> S[Captured source inventory]
    S --> N[Native Codebase IR and dependency graph]
    N --> A[Authenticated model and embedding inputs]
    A --> F[Formalization candidates and source mappings]
    N --> F
    F --> V[Trusted checks and scoped evidence index]
    I[Versioned Intent IR] --> G[Current symbol and evidence grounding]
    V --> G
    G --> P[State qualified goals and reviewed producers]
    P --> W[Symbolic plan and isolated worker]
    W --> O[Measured post state and fresh checks]
    O --> S
    N --> C[Frozen eligible corpus and replay]
    C --> T[Private inherited training candidate]
    A --> T
    T --> E[Independent evaluation and promotion policy]
    E --> A
    V --> H[Per cell DuckLake history]
    E --> H
~~~

| Stage | Required handoff and acceptance | Existing work items |
| --- | --- | --- |
| R00 Register and select | Stable repository ID, source-mode policy, declared scope/environment, cell/task profiles and authenticated selectors | C00 C01 C12 C15 |
| R01 Capture | Exact source manifest, exclusions/opaque/failure ledger, observed head and bounded completeness | C02 |
| R02 Derive native IR | AST/native units, source maps, symbol versions, dependency edges and unresolved semantics | C02 C04 |
| R03 Admit model inputs | Actual checkpoint/vector receipts or explicit unavailable state; deterministic native path remains usable | C03 C13 |
| R04 Autoformalize | Separate candidate/native targets, typed logic obligations, correspondence and unsupported facets | C04 C13 |
| R05 Check and index | Trusted attempt/outcome receipts, canonical keys, exact dependencies and current eligibility | C05 C06 |
| R06 Ground intent | Intent/source versions, exact symbol bindings, current facts, state-qualified desired goals and unresolved requirements | C07 C17 |
| R07 Compile plan | Verified IR adapters, reviewed producers, real task metadata, checks, leases and authority | C07 C10 |
| R08 Execute and refresh | Fresh pre-observation, measured diff/effects, fresh post-observation/checks and new source/index head | C06 C10 |
| R09 Freeze training corpus | Source-bound targets, coverage gate, inherited splits/replay, exposure ledger and pre-fit evaluation contract | C08 C09 |
| R10 Adapt in shadow | Compatible parent, explicit update policy, finite leased work and immutable private candidate | C08 |
| R11 Evaluate and promote | Absolute fidelity, coverage, replay retention, independent evaluation and fresh owner-side head CAS | C08 C09 C14 |
| R12 Deliver and recover | Local receipts, idempotent lake/Hub deliveries and independently recoverable journals | C11 C16 |

R09 can proceed from admitted native units before any repair is executed.
Training never runs inside an active planning request. Every stage records an
operation ID, exact immutable inputs, owner incarnation, outcome and referenced
artifacts. Retry loads an authenticated completed receipt, then reobserves its
source applicability. `current()` reads a stored head; `observe_current()`
establishes current admitted bytes. Historical completion cannot imply current
success after a repository change.

## Register and scan the complete declared scope

For the first pilot, propose a strict-clean gate over the existing committed
Git-root policy. The inspected policy itself admits both `git-clean` and
`git-working`. An explicit overlay profile must include HEAD/index dispositions,
captured working bytes, admitted untracked/ignore semantics and nested-root
boundaries. Neither a branch name nor a selected file list establishes a source
snapshot.

The existing pilot bounds are 256 nonexcluded inventory entries and 64 KiB per
file. Training/proof selections reference that inventory; they do not filter
it. Register exclusions and inspect the entire effective inventory before
admission. Oversized, undecodable, opaque, missing or unsupported entries get
explicit dispositions. A bounded pilot cannot claim whole-repository coverage.

Before expanding, add deterministic paging and a sealed aggregate manifest
covering all admitted shards under one consistent root observation. Record
page ownership, duplicates, missing pages and concurrent-change rejection.
Do not treat separately successful pages from different trees as one complete
scan. Parse captured bytes without importing repository modules.

Report file-entry, AST-unit and property-obligation denominators separately:
captured entries, parsed units, supported native units, decoded units,
formalized obligations, checked outcomes and currently eligible claims. Account
for unsupported units and missing expected obligations. A high success rate
over only emitted formulas does not establish complete formalization coverage.

## Reuse artifacts and index proof evidence

The later [normalized query qualification](../../workspace/codebase-evidence-query-qualification-20261002/REPORT.md)
implements a bounded part of the conditional index work: full exact canonical
key membership, typed reverse dependencies, atomic projection publication and
inventory-bound pagination on the existing DuckDB owner. The public
`lookup_current` route uses it by default; legacy records require explicit
admitted `rebuild_current`. Query receipts record their starting position,
consumed entries and a durable evidence epoch, so a terminal tail cannot imply
unique evidence and a same-head append invalidates an old cursor. The
supervisor consumes an initial page of at most two entries and keeps all runtime
requirements residual. See the [API and bounds](../software_contracts/CODEBASE_IR_FOUNDATION.md#normalized-conditional-evidence-queries).
This is partial RPI-007/032 work. Full-inventory integrity scans remain bounded
linear work; DuckLake delivery, broader semantics, independent learned targets,
retention and production admission remain open.

The subsequent [bounded conditional execution qualification](../../workspace/codebase-smt-execution-qualification-20261002/REPORT.md)
closes the private producer's unbounded subprocess-capture and active-cancellation
gaps with a default version-2 transport. Every version/verdict/artifact phase
uses fresh child admission, one shared deadline and the existing bounded
process lifecycle. The unchanged 128 MiB native envelope is enforced as a
per-process address-space cap and sampled tree-RSS guard. Clean two-stage SMT
responses and replayable phase receipts replace opposite-artifact errors.
An explicit exact-generation adapter preserves reviewed version-1 history
without assigning it version-2 execution properties. Aggregate cgroups, generic
backend admission, full index scaling and broader source semantics remain open.

The [post-restart safety increment](../../workspace/codebase-restart-safety-qualification-20261002/REPORT.md)
then adds boot-bound scheduler ownership, conservative stale recovery before an
idle configuration transition, and admission refusal when known cgroup-v2 memory
limits lack usable counters. Its qualification pins each currently saved pool,
refuses configuration drift and independently replays pre-restart version-2 history. This is partial
RPI-022/024/025 work; existing producer schemas, semantic pins and proof authority
are unchanged. Existing scheduler facades also refuse changed configuration
before ordinary operations can restore their stale limits; only explicit idle
reconfiguration can change the pool.

The [bounded query batch increment](../../workspace/codebase-query-many-qualification-20261003/REPORT.md)
amortizes complete inventory checks across up to 32 selectors under one source
observation pair, query transaction and admission. Count, requested entries and
aggregate request/receipt/evidence bytes are bounded; projection replay reuse
lasts only for the call. Single-page receipts and cursors remain compatible,
and any failure withholds every page. A separate supervisor batch matcher maps
explicit requirements to those pages while retaining unsupported and runtime
residuals. This supplies partial RPI-007/012/032 evidence without activating
public preparation. Caching integrity across calls by head/epoch alone would
weaken missing-membership detection. Kernel aggregate containment, authenticated
sublinear indexing and DuckLake delivery retain their separate exit conditions.

Use four separately reported cache classes: source/AST/native artifacts,
vectors, model candidates and checked evidence. Reuse an old vector only for
identical captured input/span/context and encoder/tokenizer/code/pooling/
normalization/precision profile. Model candidate reuse also binds the exact
decoder, codec, generation policy and output budget. Future unseen inputs need
new authenticated entries; preserve old embedding files and weights unchanged.

Warm-process AST reuse, cold-restart artifact loading, semantic rescanning and
embedding reuse have separate counters. Durable shard hydration is an explicit
C02 addition if restart scan savings are required. Parser/semantic successes
remain structural observations until interpreted and checked.

The current integer evidence index and property cache store historical
conditional evidence. Their current consumer executes fresh native checks even
on a cache hit. Report `history_hit`, `fresh_checker_execution` and
`certificate_rechecked` separately. Lower solver-work cost from certificate
reuse is a later profile requiring a verified portable artifact and exact
current applicability, not a property of today's historical cache.

The current evidence index admits only terminal `proved` and `refuted` receipts
under its closed conditional profile. Nonterminal, unsupported and raised
stale/cancellation outcomes need a separate attempt journal or reviewed owner
extension. A conditional receipt does not automatically become an authoritative
supervisor proof or an unrestricted runtime fact.

Preserve the existing sixteen-field canonical proof key. A dependency slice,
source/environment/policy revision or checker change invalidates affected
applicability. Start with complete-head/tree freshness; introduce cross-tree
dependency-slice reuse only through its reviewed adapter. Similarity results
rank possible evidence and then undergo exact lookup and validation.

Use the per-cell DuckDB index owner for exact/reverse lookups and transactional
control records; use its separate registry owner for models and runs. Workers
return immutable receipts to owners. The proposed serialized writer process
fits DuckDB's [in-process concurrency contract](https://duckdb.org/docs/current/connect/concurrency).
The lake has a separate [metadata catalog and data path](https://ducklake.select/docs/stable/duckdb/usage/connecting)
and [transactional snapshots](https://ducklake.select/docs/stable/duckdb/advanced_features/transactions).
Those contracts do not make CAS, independent cell stores and Hub publication
one atomic operation. Commit local state/outbox under its owner, reconcile
optional deliveries, and fence effect-time reads despite delivery lag. Reuse
the twelve planned routes without creating files during inventory discovery.

## Ground intent against current and desired states

First resolve Intent IR identifiers against current exact symbol versions,
contracts, effects and scope. Semantic/vector retrieval can nominate candidates;
an owner validates the source and typed relation. Ambiguous identifiers or
missing applicability produce unresolved bindings. Legal/Security requirements
include their own source revisions and applicability; their cells remain
separate from observed code.

Introduce a reviewed transition-binding adapter with these fields:

Reuse existing `ProgramTransitionQuery`, candidate/prediction, observation and
admission owners inside that proposed adapter. The repair query requires a
current graph. Observation keeps the H0 query subject and references the measured
H1 successor/mapping; the post-state graph and verification plan are new H1
artifacts. Native transition admission does not authorize effects or completion.
Keep native identity CIDs separate from full-record pinned transport CIDs.

- Intent root/node/constraint, repository/source/semantic roots, exact subject
  source and symbol version, environment/policy and grounding scope.
- Phase `current`, `planned_post` or `observed_post`; distinct semantic subject
  bindings for current and proposed future claims.
- Reviewed producer/template, preconditions, effects, dependencies, allowed
  paths, runner/tool/arguments, required checks and budgets.
- Planned-to-actual subject mapping, measured post-tree/semantic roots and
  eligible post-state evidence before goal discharge.

A planned-post subject is a desired artifact, not an observed tree. The current
compiler semantic key uses predicate type, subject and object; changing only
`predicate_id` does not distinguish states. Preserve an actual false current
claim while scheduling a transition to establish a different future claim.
Mandatory false policy/invariant preconditions still block the transition.

The inspected compiler routes unknown facts to REVIEW and does not turn those
leaves into tasks. Use a separately admitted observation/context-resolution
request with real tools/checks, then rebuild grounding and recompile. Preserve
unsupported scope and unresolved references if evidence remains unavailable.

The Intent adapter requires verified Intent and Formalization artifacts. Its
registry lacks a native Codebase family slot today. Register a reviewed typed
Codebase-to-formalization/native-subject bridge; preserve canonical upstream
types instead of injecting arbitrary Codebase JSON or duplicating those types.
Derive `satisfied_*` and discharged-obligation IDs from owner-validated evidence.
The adapter's ID-presence checks alone do not establish implementation success.

Supply a reviewed `ProducerRule`/`TaskCandidate` catalog for observe, formalize,
check, edit, test and reindex tasks. The symbolic planner schedules supplied
alternatives; it does not invent runnable commands. A fallback validation marker
must resolve to an actual registered check before execution.

## Execute a change and establish the post state

A trusted observer measures current repository/semantic roots, leases and scope
immediately before dispatch and before checks. Bind actual runners, tool
binaries, arguments, environment, timeout and cancellation. Dispatch only when
required source, policy and evidence bindings remain applicable.

After execution, capture the actual diff and post-tree, observe roots again
after verification, reindex affected units and independently validate outcomes.
The existing executor's fallback pre/post identity values are not measurements;
use a reviewed observer callback/envelope adapter. Missing runners and
unavailable/timeout/cancelled checks retain their outcomes. Completion requires
the requested postcondition and checks under the measured post-state contract.

## Adapt the repository model through a separate queue

Admitted source successors, reviewed counterexamples and measured supported
reconstruction/retrieval failures may enqueue candidates. Freeze trigger
thresholds, minimum cohort, cooldown/coalescing, priority, retries, supersession
and resource budgets before fitting. Key requests by cell/task/profile, exact
source and corpus/replay roots, parent checkpoint and update-policy digest.
An intent request or an unchecked prediction cannot supply a training label.

Model unavailability is recorded per lane during repository registration. It
does not block deterministic capture, native semantics or supported checks.
Require inherited weights when admitting that model-dependent branch.

Require an authenticated compatible parent in inherited mode. Missing parents
or incompatible basis/codec profiles yield unavailable/migration work. Existing
source8 root creation can initialize weights when its parent is absent, so the
reuse adapter must explicitly exclude that call path. Reuse compatible bodies
and heads; declare and evaluate any newly required initializer components.

Ordinary source8 successors retain cohort paths/contracts/roles, frozen
tune/canary content, original replay and compatible saved Adam state. Its
inference is restricted to the registered current head/cohort. Unknown feature
atoms are reported and omitted by the numerical matrix; add a coverage gate so
new constants or symbols cannot disappear into a misleading reconstruction.
Expanding paths, basis, evaluation data or grammar requires an explicit
migration/new compatible variant with inherited replay and exposure history.
The current ordinary source8 fit includes current training rows plus original
root replay. Intermediate ancestor rows remain in the exposure ledger; they
are not all automatically replayed by that fitting policy.

The saved source8 parent already reports an unknown program atom in tuning;
its child reports an unknown atom in current training, tuning and canary
diagnostics. Original-root training replay has zero unknowns. These checkpoints
remain reusable artifacts, but the new `counter.py` pilot is outside their
registered cohort and requires reviewed basis/cohort migration. Their repeated
canary diagnostics are explicitly not an independent holdout.

FedAvg has a separate policy: current inherited paths are partitioned across
clients, original replay is diagnostic, and aggregate optimizer moments and
progress reset. Specify historical retention coverage before promotion and use
the federated lineage reader. It does not implement exact Adam continuation,
source384 ridge aggregation or presently unavailable synchronized gradients.

For source384, preserve the actual narrow Security-payload bridge and fit its
compatible readout using original rows/vectors or sufficient statistics. Ridge
weights alone cannot reconstruct old fitting statistics. Other Codebase-native
heads and a native 768D initializer require explicit compatible transfer and
source/codec/span qualification; the existing Legal 768D initializer remains a
separately scoped possible donor. Wider-cell readiness is independent of 8D/384D.

Separate queued/admitted work, client receipt, queue acknowledgment, completed
producer run, durable candidate, provenance delivery, evaluated candidate and
promoted serving head. Recover completed artifacts and acknowledgment gaps
without fitting again. A completed producer run is terminal; later rounds use
new operation IDs and exact parents. Stop at ancestry/history/cohort/resource
limits and request a reviewed anchor/migration instead of pruning evidence.

An owner-side versioned promotion validator checks absolute task fidelity,
unknown/unsupported coverage, inherited short-span retention, preregistered
independent evaluation and fresh source/model head bindings. Registry promotion
requires its validator and head compare-and-swap. Loss reduction, candidate
completion and training diagnostics do not close proof or Intent obligations.
Switch only the owning task/profile serving head; retain rollback receipts,
rebuild that candidate-index view and keep proof applicability independently
validated. Lake/Hub delivery may remain pending after a valid local switch.

## Worked repair and evaluation panel

Use a declared supported integer-offset function whose captured source returns
`x + 1`, with an intent to return `x + 2` under the same declared assumptions.

1. Capture current tree H0 and exact function source. Record its native
   structure and the conditional integer-offset check outcomes for both offsets.
2. Preserve the refuted current offset2 claim. Bind the desired offset2 to a
   distinct planned-post subject and select an admitted edit producer followed
   by concrete verifier/test/reindex tasks.
3. Reobserve H0 before dispatch. Capture actual tree H1 after the edit and map
   the planned subject to H1's exact function version.
4. Run fresh supported native checks and affected tests against H1. The H0
   receipt remains historical; H1 completion uses owner-derived post-state
   evidence within the accepted verification profile.
5. Reindex and enqueue adaptation only if this exact task/cohort/basis qualifies.
   A new literal outside the 8D basis needs migration. This integer-offset example
   does not establish eligibility for source384's narrower two-operand cohort.

Freeze these minimum acceptance cases before selecting a candidate:

| Case | Required result |
| --- | --- |
| Achievable currently-false postcondition | Edit/check plan exists while current false evidence remains recorded |
| Conflicting true/false facts for one current semantic key | Contradiction blocks |
| False mandatory policy or no applicable producer | Effects block; failure is explicit |
| Unknown or unsupported semantics | Separate admitted observation/review; no invented true fact |
| Old-tree proof, wrong store/root/role or unmapped changed symbol | Cannot discharge post-state goal |
| Oversized scope, missing aggregate page or truncated model input/output | Coverage remains incomplete or admission rejects |
| Warm restart, cold restart and exact operation replay | Reuse counters are accurate; source is reobserved |
| New feature atoms, changed evaluation units or missing parent | Migration/unavailable; no hidden random replacement |
| Crash after fitting but before acknowledgment/provenance delivery | Recover exact candidate without optimizer replay |
| Cancellation, resource exhaustion or stale promotion heads | Serving parent remains selected |
| Lower loss with worse native/critical-field/retention fidelity | Promotion rejects |

## Implementation order and deliverables

First integrate and reproduce the chosen code and actual model assets through
C00, then establish repository identity, native coverage and frozen evaluation.
Deliver bounded capture, exact evidence indexing and read-only intent matching
before an effectful pilot. Add state-qualified producers, typed IR registration
and live observer checks before the first witnessed edit/check/reindex loop.

In parallel, add the eligible-corpus queue, mandatory inherited mode and
unknown-coverage gate. Run 8D and 384D private candidates under their actual update
contracts, preserving old files. Promote only after independent task-specific
gates. Extend span coverage and native 768D transfer separately, then broaden
repository scope through sealed paging and owner migrations.

The deliverable is one auditable intent-to-measured-post-state loop, plus a
separate recovered and evaluated repository adaptation lineage. Report current
scope, supported/unsupported coverage, exact/semantic/surface reconstruction,
historical cache hits, fresh check cost, grounding ambiguities, planning outcomes,
retention, latency and resource use. Until those receipts exist, this document
specifies implementation work rather than a proved or trained whole codebase.

## Direct prover admission increment (2026-10-03)

Default Lean, Rocq, Isabelle and TLC native execution now joins the shared
resource scheduler through bounded root or actual child leases. Missing memory
budgets and oversized profiles fail before launch; pressure backoff and one
admission/execution deadline apply. Lean also has an explicit bounded native
worker/stack profile. See the [qualification](../../workspace/generic-prover-admission-qualification-20261003/REPORT.md)
for observed native outcomes and the preserved failed attempts.

This completes a slice of the shared resource-control work. Legacy SMT,
Apalache, setup deadlines, aggregate cgroups and supervisor owner integration
remain open. No broader production acceptance task is closed. Existing proof
index batches, native source pins, historical database and CAS are preserved.

## Public SMT admission increment (2026-10-03)

Shared admission is now the default for public Z3/CVC5 adapters, registry factories
and V2 execution. Per-solver budgets span verdict, applicable model/core replay
and version discovery. Strict native failure handling and a bounded single-check
profile prevent incomplete output from becoming a successful result. The
[qualification](../../workspace/generic-smt-admission-qualification-20261003/REPORT.md)
separates real native concurrency from controlled pressure tests and records
unchanged historical proof-cache replay. Frozen legacy compiler/differential
entry points, Apalache, aggregate containment and supervisor ownership still
need migration. RPI-022 and all broader production acceptance gates remain open.

## SMT consumer admission increment (2026-10-03)

The verification API and classical SMT parser defaults now join shared admission.
New public differential and source-pipeline facades inject admitted solvers into
the unchanged semantic owners, preserving historical compiler/pipeline pins and
caller-supplied backends. The [qualification](../../workspace/smt-consumer-admission-qualification-20261003/REPORT.md)
records native public source-to-VC-to-SMT runs, controlled pressure/refusal checks,
concurrency and historical cache preservation. Direct legacy modules, self-hashed
header derivations, aggregate operation control, Apalache and supervisor ownership
remain open. No source semantics, training eligibility or planning authority is added.

## Aggregate operation control increment (2026-10-03)

The public differential verifier/helpers, source pipeline and canonical differential
API now enforce one default deadline and cancellation scope across their operation.
Per-solver receipts retain their bounds, while actual native phases receive the
remaining operation time. Interrupted results are withheld at the outer boundary;
earlier negative results cannot escape through the legacy pipeline's `disproved`
property. In-process callbacks remain cooperative, with late-result rejection.
See the [qualification](../../workspace/smt-operation-control-qualification-20261003/REPORT.md)
for native interruption, pressure controls and historical preservation. V2 is
covered by the subsequent increment below. Legacy/header/setup integration,
aggregate cgroups and supervisor ownership remain open. Runtime source evolution
does not rewrite prior qualification evidence
or change pinned CodebaseIR semantic producers. RPI-022 remains partial.

## Standalone V2 operation control increment (2026-10-03)

V2 execute helpers and engines now share one default deadline across solver
participants, automatic replay and evidence construction. Explicit replay also
bounds nested execution and its final comparison/receipt. Constructor/call
cancellation combines, and interrupted calls withhold results. Controls do not
enter serialized request or evidence schemas. Bounds/control coercion precedes
the cooperative scope; arbitrary Python callbacks cannot be forcibly preempted.

See the [V2 qualification](../../workspace/smt-v2-operation-control-qualification-20261003/REPORT.md)
for exact historical wire comparisons, native admission/stop/replay checks and
retained runtime source evolution. Frozen CodebaseIR producers and previous
qualification/cache artifacts remain unchanged. RPI-022 still needs legacy/header/
setup migration, Apalache, hard aggregate containment and supervisor ownership.

## JVM setup probe increment (2026-10-03)

Default TLC/Apalache construction now obtains Java identity through bounded
shared admission. The banner/runtime probe APIs support explicit parent ownership
and cancellation, keep one local deadline and honor an enclosing operation scope.
Native failure cannot supply a usable JVM observation. See the
[qualification](../../workspace/jvm-probe-admission-qualification-20261003/REPORT.md) for real Java calls, private pressure/deadline controls
and preserved source generations. This does not run model checking, migrate
installation/tool probes or connect constructor setup to the later proof owner.
RPI-022 remains open for those paths, hard containment and supervisor integration.

### State-model startup probe admission increment (2026-10-03)

Installer TLC help and Apalache version probes now use shared resource admission
and bounded JVM profiles by default. Their optional parent/cancellation controls
and one local deadline cover discovery, TLC fallback and final normalization.
Unsafe partial help/version output remains unusable. Exact managed TLC launchers
can be expanded into direct bounded Java calls while retaining existing managed
identities; actual commands are disclosed. See the [qualification](../../workspace/state-model-probe-admission-qualification-20261003/REPORT.md).
This advances setup safety without changing source semantics, proof authority or
planner acceptance. Whole-install budgets, parent propagation, generic version
readers, Apalache execution and TLA interrupted-counterexample classification
remain separate work, alongside aggregate containment and learned IR delivery.

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

The native ground secrecy query-binding gap is qualified within the source
profile below. Broader protocol semantics and CodebaseIR planning remain open.

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
